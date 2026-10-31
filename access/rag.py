"""Question answering about one programme, behind the "Ask about this programme" box (Layer 3).

We retrieve the passages of the programme's official page that best match the question (passages.retrieve,
hybrid BM25 plus dense within the page). A language model then answers only from those numbered passages,
cites them and copies a short verbatim quote for each claim, or says the page does not answer the question.
Finally we check faithfulness: citations must point at retrieved passages and every quote must appear in the
page (critics.evidence_grounded, the same check the judge panel uses). Unverified answers are flagged, not hidden.
"""
import re

from .config import ROLES
from .critics import evidence_grounded
from .llm import LLMError, call_json, set_role
from .passages import page_text, retrieve

NOT_STATED = "The official page does not say."
SYSTEM = ("You answer questions about one funding programme using ONLY the numbered passages from its official "
          "page. You never use outside knowledge. Reply in JSON.")
PROMPT = """Question from an applicant: {question}

Passages from the official page of "{name}":
{passages}

Answer in 1-3 plain sentences, citing passages like [P3]. For every claim copy a short verbatim quote (5-20 words)
from the passages. If the passages do not answer the question, the answer must be exactly: "{not_stated}"
JSON: {{"answer": "...", "cited": [passage numbers], "quotes": ["verbatim quote", ...]}}"""


def ask(programme: dict, question: str, k: int = 4) -> dict:
    """Answer one question from the programme's official page, with citations, quotes and a verified flag."""
    set_role("live")
    text = page_text(programme.get("url", ""))
    hits = retrieve(text, question, k=k) if text else []
    if not hits:
        return {"answer": NOT_STATED, "citations": [], "verified": True, "model": None}
    shown = "\n\n".join(f"[P{n}] {p}" for n, p in hits)
    prompt = PROMPT.format(question=question, name=programme.get("name", ""), passages=shown, not_stated=NOT_STATED)
    data, model = None, None
    for spec in ROLES["advisor"]:  # the first model with free quota answers
        try:
            data, model = call_json(spec, SYSTEM, prompt), spec.label
            break
        except LLMError:
            continue
    if not isinstance(data, dict):
        return {"answer": "The AI services are busy right now. Please try again in a minute.", "citations": [],
                "verified": False, "model": None}
    answer = str(data.get("answer") or NOT_STATED).strip()
    numbers = {n for n, _ in hits}
    # Models return citations as 5, "5", "P5" or only as [P5] markers in the answer text, so we accept all four.
    raw = [str(c) for c in (data.get("cited") or [])] + re.findall(r"\[P(\d+)\]", answer)
    cited = sorted({int(m) for c in raw for m in re.findall(r"\d+", c) if int(m) in numbers})
    quotes = [str(q) for q in data.get("quotes") or [] if str(q).strip()]
    grounded = [evidence_grounded(q, text) for q in quotes]
    verified = answer == NOT_STATED or (bool(quotes) and all(grounded) and bool(cited))
    return {"answer": answer, "citations": [(n, p) for n, p in hits if n in cited] or ([] if answer == NOT_STATED else hits[:1]),
            "quotes": quotes, "verified": verified, "model": model}
