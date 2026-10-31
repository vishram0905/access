"""One calling interface over the free model providers (Gemini, Groq, NVIDIA and local Ollama).

Every agent in every layer goes through call_json() or embed(). We cache each call on disk by model and prompt,
so re-running the pipeline does not spend free-tier quota twice and the results can be reproduced.
"""
import hashlib
import json
import re
import threading
import time

import ollama
from google import genai
from google.genai import types as gtypes
from groq import Groq

from . import resources
from .config import CACHE_DIR, FREE_PROVIDERS, ModelSpec, api_key

_clients: dict = {}
_lock = threading.Lock()
# Minimum seconds between two requests to the same provider. These keep us inside the free-tier rate limits.
_MIN_GAP = {"gemini": 6.5, "groq": 2.2, "ollama": 0.0, "mistral": 1.5, "nvidia": 1.6}
_last_call: dict[str, float] = {}


class LLMError(RuntimeError):
    pass


def _client(provider: str):
    if provider not in FREE_PROVIDERS:
        raise LLMError(f"Refusing to call non-free provider '{provider}'")
    with _lock:
        if provider not in _clients:
            if provider == "gemini":
                # We set a 90 s timeout because without one a stalled Google server leaves a worker waiting forever.
                _clients[provider] = genai.Client(api_key=api_key("GEMINI_API_KEY"),
                                                  http_options=gtypes.HttpOptions(timeout=90_000))
            elif provider == "groq":
                _clients[provider] = Groq(api_key=api_key("GROQ_API_KEY"), timeout=90)
            elif provider == "nvidia":
                import requests as _rq
                _clients[provider] = _rq.Session()
            elif provider == "mistral":
                try:
                    from mistralai import Mistral  # SDK 1.x
                except ImportError:
                    from mistralai.client import Mistral  # SDK 3.x
                _clients[provider] = Mistral(api_key=api_key("MISTRAL_API_KEY"))
            elif provider == "ollama":
                _clients[provider] = ollama.Client(timeout=resources.local_timeout())  # so no agent stalls
            else:
                raise ValueError(provider)
        return _clients[provider]


def _throttle(provider: str):
    with _lock:
        gap = _MIN_GAP[provider] - (time.time() - _last_call.get(provider, 0))
        if gap > 0:
            time.sleep(gap)
        _last_call[provider] = time.time()


def _cache_path(spec: ModelSpec, system: str, prompt: str):
    h = hashlib.sha256(f"{spec.provider}|{spec.model}|{system}|{prompt}".encode()).hexdigest()[:24]
    return CACHE_DIR / f"{h}.json"


def _parse_json(text: str):
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.S).strip()
    text = re.sub(r"^```(?:json)?|```$", "", text, flags=re.M).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}|\[.*\]", text, flags=re.S)
        if m:
            return json.loads(m.group(0))
        raise


_role = threading.local()


def set_role(role: str):
    """Record which pipeline role the current thread is calling for; it decides that role's daily token share."""
    _role.name = role


def current_role() -> str:
    return getattr(_role, "name", "critic")


def _raw_call(spec: ModelSpec, system: str, prompt: str, model: str | None = None) -> str:
    _throttle(spec.provider)
    model = model or spec.model
    if spec.provider == "gemini":
        r = _client("gemini").models.generate_content(
            model=model,
            contents=prompt,
            config=gtypes.GenerateContentConfig(
                system_instruction=system,
                response_mime_type="application/json",
                temperature=0,
                automatic_function_calling=gtypes.AutomaticFunctionCallingConfig(disable=True),
            ),
        )
        return r.text or ""
    if spec.provider == "groq":
        # The default output allowance (1,200) suits the reasoning judges; at low effort the live ranker writes about
        # 430 tokens a batch, and reserving 1,200 made its third batch wait a full minute for nothing.
        est = resources.estimate_tokens(system, prompt, output=spec.out_tokens)
        resources.charge_daily("groq", model, current_role(), est, check_only=True)
        resources.reserve_tokens("groq", model, est, current_role())
        r = _client("groq").chat.completions.create(
            model=model,
            messages=[{"role": "system", "content": system}, {"role": "user", "content": prompt}],
            response_format={"type": "json_object"},
            temperature=0,
            **dict(spec.options),
        )
        used = getattr(r, "usage", None)
        resources.charge_daily("groq", model, current_role(), used.total_tokens if used else est)
        return r.choices[0].message.content or ""
    if spec.provider == "nvidia":  # NVIDIA serves an OpenAI-compatible endpoint
        import requests as _rq
        try:
            r = _client("nvidia").post(
            "https://integrate.api.nvidia.com/v1/chat/completions", timeout=20 if current_role() == "live" else 75,
            headers={"Authorization": f"Bearer {api_key('NVIDIA_API_KEY')}", "Content-Type": "application/json"},
            json={"model": model.split(":", 1)[-1] if model.startswith("nvidia:") else model,
                  "temperature": 0, "max_tokens": 4096,
                  "messages": [{"role": "system", "content": system}, {"role": "user", "content": prompt}]})
        except (_rq.exceptions.Timeout, _rq.exceptions.ConnectionError) as e:
            resources.bench(model, "timeout")  # bench on the first timeout, retrying is too slow
            raise LLMError(f"benched: {model} unreachable ({type(e).__name__})")
        if r.status_code == 429:
            resources.bench(model, "429")
            raise LLMError(f"429 rate limit on {model}")
        r.raise_for_status()
        return r.json()["choices"][0]["message"]["content"] or ""
    if spec.provider == "mistral":
        r = _client("mistral").chat.complete(
            model=model,
            messages=[{"role": "system", "content": system}, {"role": "user", "content": prompt}],
            response_format={"type": "json_object"},
            temperature=0,
        )
        return r.choices[0].message.content or ""
    if spec.provider == "ollama":
        ok, why = resources.local_model_ok()
        if not ok:
            raise LLMError(f"local judge skipped: {why}")
        kwargs = dict(
            model=spec.model,
            messages=[{"role": "system", "content": system}, {"role": "user", "content": prompt}],
            format="json",
            options={"temperature": 0, "num_ctx": resources.LOCAL_CTX},
            keep_alive="2h",  # keep the judge loaded rather than reload it per call
        )
        if spec.model.startswith("qwen3"):
            kwargs["think"] = False
        with resources.local_slot:  # one local call at a time
            r = _client("ollama").chat(**kwargs)
        return r["message"]["content"]
    raise ValueError(spec.provider)


def call_json(spec: ModelSpec, system: str, prompt: str, retries: int = 4) -> dict:
    """Call a model and return its parsed JSON answer.

    Answers are cached on disk. On rate limits, overload or malformed JSON we retry, and when a model's quota is
    spent we move on to the next model in spec.fallbacks.
    """
    path = _cache_path(spec, system, prompt)
    if path.exists():
        return json.loads(path.read_text())
    last_err = None
    models = [spec.model, *spec.fallbacks]
    mi, attempt = 0, 0
    while attempt < retries + len(spec.fallbacks) and mi < len(models):
        model = models[mi]
        from . import runtime
        if resources.cooldown_left(model) > 0 or runtime.model_disabled(model):  # out of quota or disabled
            mi += 1
            continue
        attempt += 1
        try:
            data = _parse_json(_raw_call(spec, system, prompt, model))
            path.write_text(json.dumps(data))
            return data
        except Exception as e:  # rate limits, overload, budget, transient errors, bad JSON
            last_err = e
            msg = str(e)
            if "PerDay" in msg or "per day" in msg.lower() and spec.provider == "gemini":
                resources.set_cooldown(model, resources.seconds_until_pacific_midnight())
                mi += 1  # this Google model has used its daily requests, so we try the next Google model
                continue
            if isinstance(e, resources.DailyBudgetExhausted) or "tokens per day" in msg or "(TPD)" in msg:
                wait = resources.parse_retry_after(msg)
                if wait:
                    resources.set_cooldown(model, wait)  # Groq tells us exactly when this model frees up
                mi += 1  # daily quota spent, so we try the same-family backup model
                continue
            if "local judge skipped" in msg:
                break
            if re.search(r"\b500\b|INTERNAL|timed? ?out|Timeout", msg):  # provider-side failure: rest the model
                resources.set_cooldown(model, 600)
                mi += 1
                continue
            if "503" in msg or "UNAVAILABLE" in msg:
                mi = min(mi + 1, len(models) - 1) if spec.fallbacks else mi  # overloaded, move on
                time.sleep(2)
            elif "429" in msg or "RESOURCE_EXHAUSTED" in msg or "rate" in msg.lower():
                if current_role() == "live":
                    # Someone is waiting on screen, so we do not sit out a rate limit: we give up on this call
                    # quickly and let the caller fall back (the results simply stay in similarity order).
                    break
                time.sleep(30)
            else:
                time.sleep(3 * attempt)
    raise LLMError(f"{spec.label} unavailable ({', '.join(models[:mi + 1])}): {last_err}")


_FASTEMBED = {}


def _fastembed(model: str, texts: list[str]) -> list[list[float]]:
    """Embed with the same Nomic model through ONNX, for the public demo where there is no Ollama server.

    The full model gives identical vectors (cosine 1.000). We default to the quantised one because it needs about
    half the memory (~470 MB vs ~900 MB peak) and gives the same hybrid retrieval quality on our known-item
    benchmark (recall@5 0.926 for both, 54 queries).
    """
    import os
    from fastembed import TextEmbedding
    if model not in _FASTEMBED:
        name = os.environ.get("ACCESS_FASTEMBED_MODEL", "nomic-ai/nomic-embed-text-v1.5-Q")
        _FASTEMBED[model] = TextEmbedding(name if model == "nomic-embed-text" else model)
    return [list(map(float, v)) for v in _FASTEMBED[model].embed(texts)]


def embed(spec: ModelSpec, texts: list[str]) -> list[list[float]]:
    """Embed texts with the given model, in batches of 32 through Ollama, or through ONNX on the public demo."""
    from .config import PUBLIC
    if PUBLIC and spec.provider == "ollama":
        return _fastembed(spec.model, texts)
    out = []
    for i in range(0, len(texts), 32):
        r = _client("ollama").embed(model=spec.model, input=texts[i:i + 32])
        out.extend(r["embeddings"])
    return out
