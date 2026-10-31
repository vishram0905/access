"""Shared configuration: paths, public-demo limits and which model runs which pipeline stage.

Every layer imports from here. The one design rule we hold to is that no stage is checked by the model family
that produced its input, and every critic panel mixes families, so the judges do not share one model's blind
spots (the "echo chamber" problem).
"""
from dataclasses import dataclass
from pathlib import Path
import os

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
RAW_DIR = DATA / "raw"
RUNS_DIR = DATA / "runs"
CACHE_DIR = DATA / "cache"
LISTINGS_FILE = DATA / "listings.json"
INDEX_FILE = DATA / "index.npz"

load_dotenv(ROOT / ".env")
# The hosted public demo (Hugging Face Space) has no local models, serves a fixed snapshot of the verified
# library and caps how often visitors can trigger model calls.
PUBLIC = os.environ.get("ACCESS_PUBLIC") == "1"
PUBLIC_SNAPSHOT = os.environ.get("ACCESS_SNAPSHOT_DATE", "")
PUBLIC_LIMITS = {"rank": 5, "plan": 5, "ask": 10}  # model calls per visitor session
PUBLIC_HOURLY_CAP = 60                              # model calls per hour across all visitors (shared free quota)
PUBLIC_RANK_BUDGET_S = 30                           # online, we stop waiting for the ranking after this many seconds
for _d in (DATA, RAW_DIR, RUNS_DIR, CACHE_DIR):
    _d.mkdir(parents=True, exist_ok=True)


@dataclass(frozen=True)
class ModelSpec:
    provider: str  # "gemini" | "groq" | "ollama"
    model: str
    family: str    # who trained it; used to enforce panel diversity
    label: str     # human-readable name shown in the UI
    fallbacks: tuple = ()  # same-family backups we try when the main model is overloaded

    @property
    def where(self) -> str:
        return "on this laptop" if self.provider == "ollama" else f"{self.provider.title()} cloud (free tier)"


# Each Google model has its own free daily request quota, so the Annotator rotates through all of them.
GEMINI_FLASH = ModelSpec("gemini", "gemini-flash-latest", "Google", "Gemini Flash",
                         fallbacks=("gemini-3.7-flash", "gemini-3.6-flash", "gemini-3.5-flash",
                                    "gemini-3.5-flash-lite", "gemini-flash-lite-latest", "gemma-4-31b-it"))
GPT_OSS = ModelSpec("groq", "openai/gpt-oss-120b", "OpenAI", "GPT-OSS-120B",
                    fallbacks=("openai/gpt-oss-20b",))
QWEN_LARGE = ModelSpec("groq", "qwen/qwen3.8-27b", "Alibaba", "Qwen 27B")
GEMINI_TEXT = ModelSpec("gemini", GEMINI_FLASH.model, "Google", "Gemini Flash",
                        [m for m in GEMINI_FLASH.fallbacks if not m.startswith("gemma")])
PHI_LOCAL = ModelSpec("ollama", "phi4-mini", "Microsoft", "Phi-4-mini")
EMBEDDER = ModelSpec("ollama", "nomic-embed-text", "Nomic", "Nomic Embed")
# Extra judges from NVIDIA's free API (build.nvidia.com, no card needed). They add three more model companies.
NEMOTRON = ModelSpec("nvidia", "nvidia/nemotron-3-super-120b-a12b", "NVIDIA", "Nemotron 3 Super")
GLM = ModelSpec("nvidia", "z-ai/glm-5.3-flash", "Zhipu AI", "GLM-5.3 Flash")
MUSE = ModelSpec("nvidia", "meta/muse-glimmer-30b", "Meta", "Muse Glimmer 30B")
# The same OpenAI open-weight model, served by NVIDIA with its own quota. We keep it so an OpenAI judge is still
# available once Groq's daily quota is spent; with Groq out and two NVIDIA judges timing out, we were left with
# only two of three companies for a whole day. The "nvidia:" prefix gives it a cooldown and quota record separate
# from Groq's model of the same name, and is stripped before the call.
GPT_OSS_NV = ModelSpec("nvidia", "nvidia:openai/gpt-oss-20b", "OpenAI", "GPT-OSS-20B (NVIDIA)")


# Which model(s) run each stage. Panels are lists.
ROLES: dict[str, list[ModelSpec]] = {
    "normalizer": [GEMINI_FLASH],
    "critic_sources": [GPT_OSS, QWEN_LARGE, PHI_LOCAL],  # default panel, also used when the pool is small
    # Rotating judge pool, in order of preference. Each row goes to the first three different companies that
    # still have quota. Google is left out because it is the Annotator. The last entry is only a stand-in.
    "judge_pool": [GPT_OSS, QWEN_LARGE, NEMOTRON, GLM, PHI_LOCAL, MUSE, GPT_OSS_NV],
    "profile_builder": [GEMINI_FLASH],
    "embedder": [EMBEDDER],
    # The public demo gets one fast cloud reviewer. There is no local model there, and Muse on NVIDIA timed out
    # often enough to keep the spinner going.
    "critic_shortlist": [GPT_OSS] if PUBLIC else [GPT_OSS, PHI_LOCAL],
    # Fallbacks never come from the shortlist reviewers' company. The hosted demo falls back to Gemini, because the
    # NVIDIA models answered with server errors from Streamlit Cloud.
    "fit_ranker": [QWEN_LARGE, GEMINI_TEXT] if PUBLIC else [QWEN_LARGE, NEMOTRON, GLM],
    # The advisor writes rather than judges, so the first provider with quota wins. We leave Gemma out because it
    # was slow and often errored, and put Qwen last because it shares Groq's per-minute limit with ranking.
    "advisor": [GEMINI_TEXT, NEMOTRON, GLM, QWEN_LARGE],
    # The Auditor is Qwen reading pages blind: it sees only the page, never the annotation, the votes or earlier
    # calls. Its own judge votes are left out when it calibrates the bands (leave-one-out trust).
    "auditor": [QWEN_LARGE],
}

# We only ever call free providers. Any paid keys in .env are ignored on purpose.
FREE_PROVIDERS = {"gemini", "groq", "ollama", "nvidia"}


def check_free_only() -> list[str]:
    """Return one message per role that uses a provider outside FREE_PROVIDERS."""
    return [f"{role}: {m.label} uses non-free provider {m.provider}"
            for role, ms in ROLES.items() for m in ms if m.provider not in FREE_PROVIDERS]


def check_role_diversity() -> list[str]:
    """Return every breach of the no-self-checking rule; an empty list means the role table is fine."""
    problems = check_free_only()
    producer_checker = [
        ("normalizer", "critic_sources"),
        ("normalizer", "judge_pool"),
        ("fit_ranker", "critic_shortlist"),
        ("profile_builder", "critic_shortlist"),
    ]
    for producer, checker in producer_checker:
        prod_families = {m.family for m in ROLES[producer]}
        for m in ROLES[checker]:
            if m.family in prod_families:
                problems.append(f"{checker} judge {m.label} shares a family with {producer}")
    annotators = {m.family for m in ROLES["normalizer"]}
    for m in ROLES["auditor"]:
        if m.family in annotators:
            problems.append(f"auditor {m.label} shares a family with the Annotator it audits")
    for panel in ("critic_sources", "critic_shortlist"):
        fams = [m.family for m in ROLES[panel]]
        if len(fams) != len(set(fams)):
            problems.append(f"{panel} panel repeats a model family")
    return problems


def api_key(name: str) -> str:
    return os.environ.get(name, "").strip()


# Places left out of search, the demo and new crawling, at the product owner's request. This is reversible: the
# records stay in the database and come back on the next library build once a place is removed from this set.
EXCLUDED_PLACES = {p.strip() for p in os.environ.get("ACCESS_EXCLUDED_PLACES", "").split(",") if p.strip()}
EXCLUDED_TLDS = tuple(t.strip() for t in os.environ.get("ACCESS_EXCLUDED_TLDS", "").split(",") if t.strip())


def is_excluded_place(listing: dict | None = None, domain: str | None = None, country: str | None = None) -> bool:
    """True for a programme hosted in, published from or named for an excluded place, or a site on its domain."""
    if domain and domain.lower().split(":")[0].endswith(EXCLUDED_TLDS):
        return True
    if country in EXCLUDED_PLACES:
        return True
    if listing:
        hosts = set(listing.get("host_countries") or []) | {listing.get("host_country"), listing.get("country_of_publisher")}
        if hosts & EXCLUDED_PLACES:
            return True
        if any(p.lower() in (listing.get("name") or "").lower() for p in EXCLUDED_PLACES):
            return True
    return False
