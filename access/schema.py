"""ACCESS annotation schema v2, the labelled matrix of funding programmes (shared by all layers).

There is one row per programme. Every categorical column uses a controlled vocabulary so that we can filter on
it exactly, and every eligibility rule and key fact carries a verbatim evidence quote from the official page.
We keep all of it in this one module so that the Annotator, the Critic panel, the Eligibility Gate, the lookup
document and the data dictionary cannot drift apart.
"""
import re


SCHEMA_VERSION = "2.0"

# ---------------- controlled vocabularies ----------------
PROVIDER_TYPES = ["government", "university", "foundation_charity", "industry",
                  "intergovernmental", "research_institute"]

OPPORTUNITY_TYPES = [
    "undergraduate_scholarship", "masters_scholarship", "phd_scholarship", "postdoc_fellowship",
    "research_fellowship", "research_grant", "travel_mobility_grant", "research_internship",
    "industry_fellowship", "award_prize",  # award_prize covers recognition awards and prizes paid to individuals
]

CAREER_STAGES = ["undergraduate", "masters", "phd_candidate", "postdoc", "early_career",
                 "mid_career", "senior", "industry"]
DEGREES = ["bachelors", "masters", "phd"]

FIELDS = [
    "computer_science", "data_science_ai", "electrical_engineering", "mechanical_aerospace_engineering",
    "civil_environmental_engineering", "chemical_materials_engineering", "mathematics_statistics",
    "physics_astronomy", "chemistry", "earth_climate_sciences", "biology_life_sciences",
    "biomedical_sciences", "medicine_clinical", "public_health", "agriculture_food",
    "energy_sustainability", "economics", "business_management", "law",
    "politics_international_relations", "education", "psychology", "social_sciences",
    "humanities_arts", "any",
]
# We group fields into broad families so that a coarse profile can still match a fine-grained programme field,
# and the other way round.
FIELD_FAMILY = {
    "computer_science": "computing", "data_science_ai": "computing",
    "electrical_engineering": "engineering", "mechanical_aerospace_engineering": "engineering",
    "civil_environmental_engineering": "engineering", "chemical_materials_engineering": "engineering",
    "energy_sustainability": "engineering", "mathematics_statistics": "physical_sciences",
    "physics_astronomy": "physical_sciences", "chemistry": "physical_sciences",
    "earth_climate_sciences": "physical_sciences", "biology_life_sciences": "life_sciences",
    "biomedical_sciences": "life_sciences", "medicine_clinical": "health", "public_health": "health",
    "agriculture_food": "life_sciences", "economics": "social_sciences",
    "business_management": "social_sciences", "law": "social_sciences",
    "politics_international_relations": "social_sciences", "education": "social_sciences",
    "psychology": "social_sciences", "social_sciences": "social_sciences", "humanities_arts": "humanities",
}

APPLICATION_CYCLES = ["annual", "rolling", "one_off", "unclear"]
STATUSES = ["open", "upcoming", "closed", "unclear"]
TARGETED_GROUPS = ["women", "developing_countries", "underrepresented_minorities", "refugees",
                   "disability", "first_generation", "none"]
REGIONS = ["North America", "Europe", "Asia", "Asia-Pacific", "South America", "Africa",
           "Middle East", "Global"]

# We derive the region from where the programme is held (host_country), never from the directory the crawler
# happened to find it in. When the country is not one we know, region_for falls back to the country domain of
# the official site, and to "Global" if that does not help either.
COUNTRY_ALIASES = {"UK": "United Kingdom", "Korea": "South Korea", "USA": "United States", "US": "United States"}
_REGION_COUNTRIES = {
    "North America": "United States, Canada, Mexico",
    "South America": "Brazil, Argentina, Chile, Colombia, Peru, Ecuador, Uruguay, Venezuela, Bolivia, Paraguay",
    "Europe": "United Kingdom, Germany, France, Netherlands, Switzerland, Sweden, Norway, Denmark, Finland, "
              "Belgium, Austria, Ireland, Italy, Spain, Portugal, Poland, Czech Republic, Hungary, Greece, "
              "Iceland, Luxembourg, Estonia, Latvia, Lithuania, Slovenia, Slovakia, Croatia, Romania, Bulgaria, "
              "Cyprus, Malta, Serbia, Ukraine, Turkey",
    "Asia": "Singapore, Japan, China, Hong Kong, India, South Korea, Malaysia, Thailand, Indonesia, "
            "Vietnam, Philippines, Pakistan, Bangladesh, Sri Lanka, Nepal, Macau, Kazakhstan, Mongolia",
    "Asia-Pacific": "Australia, New Zealand, Fiji, Papua New Guinea",
    "Middle East": "Israel, Saudi Arabia, United Arab Emirates, Qatar, Kuwait, Oman, Bahrain, Jordan, Lebanon, "
                   "Iran, Iraq",
    "Africa": "South Africa, Nigeria, Kenya, Egypt, Ghana, Ethiopia, Morocco, Rwanda, Uganda, Tanzania, Tunisia",
}
COUNTRY_REGION = {c.strip(): r for r, cs in _REGION_COUNTRIES.items() for c in cs.split(",")}
TLD_COUNTRY = {"sg": "Singapore", "jp": "Japan", "cn": "China", "hk": "Hong Kong", "in": "India",
               "kr": "South Korea", "my": "Malaysia", "th": "Thailand", "id": "Indonesia", "il": "Israel",
               "sa": "Saudi Arabia", "ae": "United Arab Emirates", "uk": "United Kingdom", "de": "Germany",
               "fr": "France", "nl": "Netherlands", "ch": "Switzerland", "se": "Sweden", "no": "Norway",
               "dk": "Denmark", "fi": "Finland", "be": "Belgium", "at": "Austria", "ie": "Ireland", "it": "Italy",
               "es": "Spain", "pt": "Portugal", "pl": "Poland", "ca": "Canada", "us": "United States",
               "mx": "Mexico", "br": "Brazil", "ar": "Argentina", "cl": "Chile", "co": "Colombia",
               "au": "Australia", "nz": "New Zealand", "za": "South Africa", "ke": "Kenya", "ng": "Nigeria"}


def region_for(host_country, url=""):
    """Return (country, region) for a host country, using the URL's top-level domain when the country is unknown.

    A bare .edu, .gov or .mil domain is treated as North America, since those are almost always US sites.
    """
    host_country = host_country if isinstance(host_country, str) else ""
    country = COUNTRY_ALIASES.get(host_country.strip(), host_country.strip())
    if country in COUNTRY_REGION:
        return country, COUNTRY_REGION[country]
    from urllib.parse import urlparse
    tld = urlparse(url or "").netloc.rsplit(".", 1)[-1].lower()
    if tld in ("edu", "gov", "mil"):
        return country, "North America"
    return country, COUNTRY_REGION.get(TLD_COUNTRY.get(tld), "Global")


def region_of(listing: dict) -> str:
    """Return the listing's region: the one region all its host countries and regions fall in, otherwise Global."""
    if listing.get("host_anywhere") or listing.get("host_resolved") is False:
        return "Global"
    url = listing.get("url", "")
    regs = {region_for(c, url)[1] for c in listing.get("host_countries") or []} | set(listing.get("host_regions") or [])
    return regs.pop() if len(regs) == 1 else "Global"


# ---------------- eligibility rules ----------------
# attribute -> (operators, hard, label). A hard attribute is one the applicant cannot change, such as nationality.
# A soft one can be reached with effort (a better IELTS score, another paper), and that is what makes a
# near-miss possible.
ATTRIBUTES = {
    "nationality": (["in", "not_in"], True, "Nationality"),
    "residency": (["in", "not_in"], True, "Residency / PR status"),
    "field": (["in"], True, "Field of study"),
    "career_stage": (["in"], False, "Career stage"),
    "highest_degree": (["in", "gte"], False, "Highest degree held"),
    "years_since_phd": (["lte", "gte"], True, "Years since PhD"),
    "age": (["lte"], True, "Age"),
    "ielts": (["gte"], False, "IELTS score"),
    "toefl": (["gte"], False, "TOEFL iBT score"),
    "publications": (["gte"], False, "Publications"),
    "gpa": (["gte"], False, "GPA (out of 4.0)"),
    "work_experience_years": (["gte"], False, "Years of work experience"),
    "gender": (["in"], True, "Gender"),
}
NEAR_MISS_MARGIN = {"ielts": 1.0, "toefl": 15, "publications": 2, "gpa": 0.3, "work_experience_years": 1}

RULE_SCHEMA_TEXT = f"""Each rule: {{"attribute": one of {list(ATTRIBUTES)},
  "operator": "in" | "not_in" | "gte" | "lte",
  "value": list of strings for in/not_in, a number for gte/lte (highest_degree gte takes a degree string),
  "evidence": SHORT exact quote (<= 25 words) copied verbatim from the page}}
Allowed values: field in {FIELDS}; career_stage in {CAREER_STAGES}; highest_degree in {DEGREES};
gender in ["female","male","non_binary"]; nationality/residency are country names (e.g. "Singapore") or "Singapore PR".
Encode only criteria that apply to ALL applicants; put group-specific criteria in conditional_criteria."""

# ---------------- the full annotation (what the Annotator returns) ----------------
ANNOTATION_SPEC = f"""Return ONE JSON object with exactly these keys:
"page_kind": "single_opportunity" | "list_of_opportunities" | "other",
"about_programme": true/false (does the page describe the named programme?),
"name": official programme name,
"provider": organisation offering it,
"provider_type": one of {PROVIDER_TYPES},
"host_countries": list of countries where the award is held (a named host institution implies its country),
"host_regions": list from {{Europe, Asia, Asia-Pacific, North America, South America, Middle East, Africa}} ONLY if
                 the page names a region instead of countries (e.g. "EU member states" -> Europe), else [],
"host_anywhere": true ONLY if the page says recipients may go to any country / worldwide,
"host_institutions": list of named host institutions, or [] if any,
"language_of_page": e.g. "English",
"opportunity_type": one of {OPPORTUNITY_TYPES},
"career_levels": list from {CAREER_STAGES} - who it is for,
"fields": 1-4 from {FIELDS} ("any" if open to all fields),
"summary": 2-3 plain-English sentences: what it funds and for whom,
"duration_months": number or null,
"number_of_awards": number or null,
"funding": {{"fully_funded": true/false/null, "stipend_amount": number or null, "currency": "ISO code" or null,
             "stipend_period": "month"|"year"|"total"|null, "covers_tuition": bool|null, "covers_travel": bool|null,
             "covers_research_costs": bool|null, "covers_insurance": bool|null, "other_benefits": short text or null,
             "evidence": short verbatim quote or null}},
"rules": list of eligibility rules (see below),
"conditional_criteria": list of short strings,
"targeted_groups": list from {TARGETED_GROUPS},
"process": {{"application_cycle": one of {APPLICATION_CYCLES}, "next_deadline": "YYYY-MM-DD" or null,
             "deadline_text": deadline as written or null, "opens": "YYYY-MM-DD" or null,
             "status": one of {STATUSES}, "needs_supervisor_or_host": bool|null, "proposal_required": bool|null,
             "references_required": number or null, "documents_required": list of short strings,
             "application_url": url or null, "evidence": short verbatim quote or null}},
"obligations": {{"service_bond": true/false/null, "return_requirement": true/false/null, "text": short or null}},
"sections": {{"eligibility": heading text on the page where eligibility is described, or null,
              "funding": heading for funding/benefits or null, "deadline": heading for dates or null,
              "how_to_apply": heading for the application process or null}}
{RULE_SCHEMA_TEXT}"""

# ---------------- flat matrix columns (CSV / lookup) ----------------
MATRIX_COLUMNS = [
    # identity
    "program_id", "name", "provider", "provider_type", "host_country", "host_countries", "host_regions",
    "host_scope", "region", "official_url",
    "official_source", "language_of_page",
    # opportunity
    "opportunity_type", "career_levels", "fields", "duration_months", "number_of_awards", "summary",
    # funding
    "fully_funded", "stipend_amount", "currency", "stipend_period", "covers_tuition", "covers_travel",
    "covers_research_costs", "covers_insurance",
    # eligibility (flattened from rules)
    "nationality_allowed", "nationality_excluded", "residency_required", "degree_required",
    "career_stage_required", "max_years_since_phd", "max_age", "min_ielts", "min_toefl", "min_gpa",
    "min_publications", "min_work_experience_years", "gender", "targeted_groups", "conditional_criteria",
    # process
    "application_cycle", "next_deadline", "deadline_text", "status", "needs_supervisor_or_host",
    "proposal_required", "references_required", "documents_required", "application_url",
    # obligations
    "service_bond", "return_requirement",
    # provenance
    "trust", "band", "completeness",
    "rules_count", "rules_dropped", "judges", "decision", "confidence", "annotated_by",
    "last_verified", "content_hash", "schema_version",
]

DATA_DICTIONARY = {
    "program_id": "Stable identifier (slug of the name + hash of the source URL).",
    "provider_type": f"Who funds it: {', '.join(PROVIDER_TYPES)}.",
    "host_country": "Display label of where it is held: country list, 'Any country' or 'Not stated'.",
    "host_countries": "Countries where the funded activity takes place (from the page; panel-checked claim).",
    "host_regions": "A region named on the page instead of countries (e.g. 'EU member states' -> Europe).",
    "host_scope": "named | anywhere (page says any country) | not_stated (page does not say, or the panel did not "
                  "confirm the place) | unresolved (legacy 'Multiple', not yet re-read). A country search matches "
                  "named countries, their region, anywhere, not_stated and unresolved.",
    "region": f"Region where the programme is held (one region if every host country/region is in it, else "
              f"Global): {', '.join(REGIONS)}.",
    "opportunity_type": f"One of: {', '.join(OPPORTUNITY_TYPES)}.",
    "career_levels": f"Who it is for, from: {', '.join(CAREER_STAGES)}.",
    "fields": "Subject areas from the 25-field taxonomy; 'any' = open to all fields.",
    "fully_funded": "True if tuition and living costs are both covered.",
    "nationality_allowed": "Only these nationalities may apply (empty = no restriction stated).",
    "nationality_excluded": "These nationalities may NOT apply.",
    "degree_required": "Minimum degree held at application time.",
    "max_years_since_phd": "Maximum years since PhD award at the deadline.",
    "next_deadline": "Next application deadline (ISO date) if stated.",
    "status": "open / upcoming / closed / unclear as of last verification.",
    "decision": "Critic panel outcome: accepted / accepted_with_warning / rejected.",
    "confidence": "Share of judge votes supporting the extracted rules and facts (0-1).",
    "trust": "Weighted KPI score: source authenticity, funding-opportunity vote, rule support, verbatim "
             "evidence grounding, judge agreement, validation (0-1).",
    "band": "high / medium by calibrated trust cut-offs (low-trust rows are withheld from search).",
    "completeness": "Share of key fields present: rules, deadline, funding, documents, application link.",
    "content_hash": "Fingerprint of the page text when verified; a change triggers re-annotation.",
}


# ---------------- human-friendly labels (every code shown to a user goes through these) ----------------
LABELS = {
    # fields
    "computer_science": "computer science", "data_science_ai": "data science & AI",
    "electrical_engineering": "electrical engineering", "mechanical_aerospace_engineering": "mechanical & aerospace engineering",
    "civil_environmental_engineering": "civil & environmental engineering",
    "chemical_materials_engineering": "chemical & materials engineering", "mathematics_statistics": "mathematics & statistics",
    "physics_astronomy": "physics & astronomy", "chemistry": "chemistry", "earth_climate_sciences": "earth & climate sciences",
    "biology_life_sciences": "biology & life sciences", "biomedical_sciences": "biomedical sciences",
    "medicine_clinical": "clinical medicine", "public_health": "public health", "agriculture_food": "agriculture & food",
    "energy_sustainability": "energy & sustainability", "economics": "economics",
    "business_management": "business & management", "law": "law",
    "politics_international_relations": "politics & international relations", "education": "education",
    "psychology": "psychology", "social_sciences": "social sciences", "humanities_arts": "humanities & arts",
    "any": "any field",
    # career stages
    "undergraduate": "undergraduate students", "masters": "master's students", "phd_candidate": "PhD candidates",
    "postdoc": "postdocs", "early_career": "early-career researchers", "mid_career": "mid-career researchers",
    "senior": "senior researchers", "industry": "industry professionals",
    # degrees
    "bachelors": "bachelor's degree", "phd": "PhD",
    # funding types
    "phd_scholarship": "PhD scholarship", "masters_scholarship": "master's scholarship",
    "undergraduate_scholarship": "undergraduate scholarship", "postdoc_fellowship": "postdoc fellowship",
    "research_fellowship": "research fellowship", "research_grant": "research grant",
    "travel_mobility_grant": "travel / mobility grant", "research_internship": "research internship",
    # funders
    "government": "government", "university": "university", "foundation_charity": "foundation / charity",
    "intergovernmental": "intergovernmental body", "research_institute": "research institute",
}
DEGREE_LABELS = {"bachelors": "bachelor's degree", "masters": "master's degree", "phd": "PhD"}
CAREER_SINGULAR = {"undergraduate": "undergraduate", "masters": "master's student", "phd_candidate": "PhD candidate",
                   "postdoc": "postdoc", "early_career": "early-career researcher", "mid_career": "mid-career researcher",
                   "senior": "senior researcher", "industry": "industry professional"}


def human(code) -> str:
    """Return the plain-English label for a vocabulary code, in lower case for use inside sentences."""
    c = str(code or "").strip()
    return LABELS.get(c, c.replace("_", " "))


def human_title(code) -> str:
    """Return the label with its first letter capitalised, for chips, headings and table cells."""
    h = human(code)
    return h[:1].upper() + h[1:]


_SNAKE = re.compile(r"\b[a-z]+(?:_[a-z]+)+\b")


def humanize_text(text) -> str:
    """Replace any snake_case code that slipped into free text, such as model-written advice, with its label."""
    return _SNAKE.sub(lambda m: human(m.group(0)), str(text or ""))
