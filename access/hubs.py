"""Seed sources for the crawler (Layer 0, library building).

HUBS are official index pages and directories that list funding schemes, as (region, country, publisher, url).
The crawler follows their links, plus one level deeper, to the individual programme pages. We also keep the
country tiers and university rankings here, because they decide what gets crawled and verified first.
"""

HUBS = [
    # ---------------- North America ----------------
    ("North America", "United States", "NIH Research Training", "https://researchtraining.nih.gov/programs/fellowships"),
    ("North America", "United States", "NIH Research Training", "https://researchtraining.nih.gov/programs/career-development"),
    ("North America", "United States", "Fulbright US Student", "https://us.fulbrightonline.org/about/types-of-awards"),
    ("North America", "United States", "IIE", "https://www.iie.org/programs/"),
    ("North America", "United States", "Ford Foundation Fellowships", "https://sites.nationalacademies.org/PGA/FordFellowships/index.htm"),
    ("North America", "United States", "Hertz Foundation", "https://www.hertzfoundation.org/the-fellowship/"),
    ("North America", "United States", "DOE CSGF", "https://www.krellinst.org/csgf/"),
    ("North America", "United States", "NDSEG", "https://ndseg.sysplus.com/"),
    ("North America", "United States", "Simons Foundation", "https://www.simonsfoundation.org/funding-opportunities/"),
    ("North America", "United States", "Sloan Foundation", "https://sloan.org/fellowships/"),
    ("North America", "Canada", "EduCanada", "https://www.educanada.ca/scholarships-bourses/non_can/index.aspx?lang=eng"),
    ("North America", "Canada", "NSERC", "https://www.nserc-crsng.gc.ca/students-etudiants/index_eng.asp"),
    ("North America", "Canada", "Vanier CGS", "https://vanier.gc.ca/en/home-accueil.html"),
    ("North America", "Canada", "Mitacs", "https://www.mitacs.ca/our-programs/"),
    ("North America", "Canada", "Trudeau Foundation", "https://www.trudeaufoundation.ca/programs"),
    ("North America", "Mexico", "CONAHCYT", "https://conahcyt.mx/becas_posgrados/"),
    # ---------------- Europe ----------------
    ("Europe", "European Union", "MSCA", "https://marie-sklodowska-curie-actions.ec.europa.eu/actions"),
    ("Europe", "European Union", "ERC", "https://erc.europa.eu/apply-grant"),
    ("Europe", "European Union", "EURAXESS funding", "https://euraxess.ec.europa.eu/funding/search"),
    ("Europe", "European Union", "Erasmus Mundus", "https://www.eacea.ec.europa.eu/scholarships/erasmus-mundus-catalogue_en"),
    ("Europe", "United Kingdom", "UKRI", "https://www.ukri.org/opportunity/"),
    ("Europe", "United Kingdom", "Leverhulme Trust", "https://www.leverhulme.ac.uk/listings"),
    ("Europe", "United Kingdom", "Study UK", "https://study-uk.britishcouncil.org/scholarships-funding"),
    ("Europe", "Germany", "DAAD database", "https://www2.daad.de/deutschland/stipendium/datenbank/en/21148-scholarship-database/"),
    ("Europe", "Germany", "Humboldt Foundation", "https://www.humboldt-foundation.de/en/apply/sponsorship-programmes"),
    ("Europe", "Germany", "DFG", "https://www.dfg.de/en/research-funding/funding-opportunities/programmes"),
    ("Europe", "Germany", "Max Planck", "https://www.mpg.de/en/career"),
    ("Europe", "France", "Campus France", "https://www.campusfrance.org/en/scholarships-funding"),
    ("Europe", "Switzerland", "SNSF", "https://www.snf.ch/en/9YzbqoAJ3Wbgt7TD/page/funding"),
    ("Europe", "Switzerland", "Swiss Excellence", "https://www.sbfi.admin.ch/en/swiss-government-excellence-scholarships"),
    ("Europe", "Netherlands", "Study in NL", "https://www.studyinnl.org/finances/scholarships"),
    ("Europe", "Netherlands", "NWO", "https://www.nwo.nl/en/funding"),
    ("Europe", "Sweden", "Study in Sweden", "https://studyinsweden.se/scholarships/"),
    ("Europe", "Sweden", "Swedish Institute", "https://si.se/en/apply/scholarships/"),
    ("Europe", "Denmark", "Study in Denmark", "https://studyindenmark.dk/tuition-fees-scholarships"),
    ("Europe", "Ireland", "Research Ireland", "https://www.researchireland.ie/funding/"),
    ("Europe", "Austria", "FWF", "https://www.fwf.ac.at/en/funding/portfolio"),
    ("Europe", "Italy", "Study in Italy", "https://studyinitaly.esteri.it/en/scholarship"),
    ("Europe", "Europe", "EMBO", "https://www.embo.org/funding/fellowships-grants-and-career-support/"),
    ("Europe", "Europe", "HFSP", "https://www.hfsp.org/funding"),
    # ---------------- Asia & Pacific ----------------
    ("Asia", "Singapore", "A*STAR", "https://www.a-star.edu.sg/scholarships"),
    ("Asia", "Singapore", "A*STAR", "https://www.a-star.edu.sg/scholarships/home/international-awards"),
    ("Asia", "Singapore", "NRF", "https://www.nrf.gov.sg/grants/"),
    ("Asia", "Singapore", "NTU", "https://www.ntu.edu.sg/admissions/graduate/financialmatters/scholarships"),
    ("Asia", "Singapore", "NTU", "https://www.ntu.edu.sg/research/research-careers"),
    ("Asia", "Singapore", "NUS", "https://nusgs.nus.edu.sg/scholarships/"),
    ("Asia", "Singapore", "SMU", "https://graduatestudies.smu.edu.sg/scholarships"),
    ("Asia", "Singapore", "SUTD", "https://www.sutd.edu.sg/admissions/graduate/scholarships-and-financial-aid"),
    ("Asia", "Singapore", "AI Singapore", "https://aisingapore.org/research/"),
    ("Asia", "Japan", "JSPS", "https://www.jsps.go.jp/english/e-fellow/"),
    ("Asia", "Japan", "Study in Japan", "https://www.studyinjapan.go.jp/en/planning/scholarship/"),
    ("Asia", "Japan", "OIST", "https://www.oist.jp/admissions"),
    ("Asia", "South Korea", "Study in Korea", "https://www.studyinkorea.go.kr/en/sub/gks/allnew_invite.do"),
    ("Asia", "China", "Campus China", "https://www.campuschina.org/content/details3_74776.html"),
    ("Asia", "China", "Schwarzman", "https://www.schwarzmanscholars.org/"),
    ("Asia", "Hong Kong", "HKPFS", "https://cerg1.ugc.edu.hk/hkpfs/index.html"),
    ("Asia", "India", "Inspire / DST", "https://online-inspire.gov.in/"),
    ("Asia", "Malaysia", "Malaysia International Scholarship", "https://biasiswa.mohe.gov.my/INTER/"),
    ("Asia", "Thailand", "TICA", "https://tica-thaigov.mfa.go.th/en/"),
    ("Asia", "Israel", "Council for Higher Education", "https://che.org.il/en/"),
    ("Asia", "Saudi Arabia", "KAUST", "https://www.kaust.edu.sa/en/study/financial-support"),
    ("Asia-Pacific", "Australia", "Study Australia", "https://www.studyaustralia.gov.au/en/plan-your-studies/scholarships"),
    ("Asia-Pacific", "Australia", "Australia Awards", "https://www.dfat.gov.au/people-to-people/australia-awards"),
    ("Asia-Pacific", "Australia", "ARC", "https://www.arc.gov.au/funding-research/funding-schemes"),
    ("Asia-Pacific", "New Zealand", "Manaaki NZ Scholarships", "https://www.nzscholarships.govt.nz/"),
    # ---------------- South America ----------------
    ("South America", "Americas", "OAS Scholarships", "https://www.oas.org/en/scholarships/"),
    ("South America", "Brazil", "CAPES", "https://www.gov.br/capes/pt-br/acesso-a-informacao/acoes-e-programas/bolsas"),
    ("South America", "Brazil", "CNPq", "https://www.gov.br/cnpq/pt-br/acesso-a-informacao/acoes-e-programas"),
    ("South America", "Chile", "ANID", "https://anid.cl/capital-humano/"),
    ("South America", "Argentina", "CONICET", "https://www.conicet.gov.ar/convocatorias/"),
    ("South America", "Colombia", "MinCiencias", "https://minciencias.gov.co/convocatorias"),
    # ---------------- Global / corporate ----------------
    ("Global", "Global", "Google Research", "https://research.google/programs-and-events/"),
    ("Global", "Global", "Microsoft Research", "https://www.microsoft.com/en-us/research/academic-programs/"),
    ("Global", "Global", "NVIDIA Research", "https://research.nvidia.com/graduate-fellowships"),
    ("Global", "Global", "Schmidt Science", "https://schmidtsciencefellows.org/"),
    ("Global", "Global", "Rhodes Trust", "https://www.rhodeshouse.ox.ac.uk/scholarships/"),
    ("Global", "Global", "L'Oreal-UNESCO For Women in Science", "https://www.forwomeninscience.com/"),
    ("Global", "Global", "Aga Khan Foundation", "https://the.akdn/en/how-we-work/our-agencies/aga-khan-foundation/international-scholarship-programme"),
    ("Global", "Global", "World Bank JJ/WBGSP", "https://www.worldbank.org/en/programs/scholarships"),
    ("Global", "Global", "Chevening", "https://www.chevening.org/scholarships/"),
    ("Global", "Global", "Knight-Hennessy", "https://knight-hennessy.stanford.edu/"),
]

# Region priority for the verification queue. Lower numbers are served sooner.
REGION_PRIORITY = {"Asia": 1, "North America": 2, "Europe": 2, "Asia-Pacific": 3, "Global": 3, "South America": 4}

# Country tiers (see docs/DECISIONS.md, D23). Tier 1 is the set of destinations with the most student traffic.
# New work (site discovery, crawling, annotation, judging) goes to tier 1 first and is shared evenly across its
# 8 groups: whichever group has the fewest programmes goes next. Tier 2 only gets work when tier 1 has nothing
# waiting. We do not re-order records that are already in the database.
_TIER1_ALIASES = {
    "Singapore": {"singapore"},
    "United States": {"united states", "usa", "us", "u.s.", "u.s.a.", "united states of america", "america"},
    "United Kingdom": {"united kingdom", "uk", "u.k.", "england", "scotland", "wales", "northern ireland",
                       "great britain", "britain"},
    "Japan": {"japan"},
    "China": {"china", "mainland china", "people's republic of china", "prc", "hong kong", "hong kong sar",
              "hong kong, china"},  # we group Hong Kong with China, as agreed with the product owner
    "Australia": {"australia"},
    "Canada": {"canada"},
}
_EUROPE = {"europe", "european union", "europe (various)", "eu", "germany", "alemanha", "france", "netherlands",
           "belgium", "luxembourg", "ireland", "switzerland", "austria", "italy", "spain", "portugal", "sweden",
           "norway", "denmark", "finland", "iceland", "poland", "czech republic", "czechia", "slovakia", "hungary",
           "slovenia", "croatia", "estonia", "latvia", "lithuania", "greece", "cyprus", "malta", "romania",
           "bulgaria", "serbia", "monaco", "liechtenstein"}
TIER1_GROUPS = list(_TIER1_ALIASES) + ["Europe"]


def tier1_group(country: str | None, region: str | None = None) -> str | None:
    """Return the tier-1 group a country belongs to, or None if it is tier 2."""
    c = (country or "").strip().lower()
    for group, names in _TIER1_ALIASES.items():
        if c in names:
            return group
    if c in _EUROPE or (not c and (region or "") == "Europe"):
        return "Europe"
    return None


# Within each tier-1 country we crawl national and government programmes first, then universities in ranking
# order, starting from each university's central scholarships or graduate-funding page. The order roughly follows
# the QS World University Rankings 2026. We compiled it by hand, so check it against the official table before
# quoting exact ranks. Universities that are not listed come after the listed ones.
UNIVERSITY_RANKING = {
    "United States": ["mit.edu", "stanford.edu", "harvard.edu", "caltech.edu", "berkeley.edu", "uchicago.edu",
                      "cornell.edu", "yale.edu", "princeton.edu", "columbia.edu", "ucla.edu", "umich.edu",
                      "northwestern.edu", "duke.edu", "cmu.edu", "washington.edu", "illinois.edu"],
    "United Kingdom": ["imperial.ac.uk", "ox.ac.uk", "cam.ac.uk", "ucl.ac.uk", "kcl.ac.uk", "ed.ac.uk",
                       "manchester.ac.uk", "lse.ac.uk", "bristol.ac.uk", "warwick.ac.uk"],
    "Singapore": ["nus.edu.sg", "ntu.edu.sg", "smu.edu.sg", "sutd.edu.sg", "singaporetech.edu.sg", "suss.edu.sg"],
    "Japan": ["u-tokyo.ac.jp", "kyoto-u.ac.jp", "isct.ac.jp", "osaka-u.ac.jp", "tohoku.ac.jp", "nagoya-u.ac.jp",
              "kyushu-u.ac.jp", "hokudai.ac.jp", "keio.ac.jp", "waseda.jp"],
    "China": ["pku.edu.cn", "tsinghua.edu.cn", "fudan.edu.cn", "sjtu.edu.cn", "zju.edu.cn", "ustc.edu.cn",
              "nju.edu.cn", "whu.edu.cn", "tongji.edu.cn", "hit.edu.cn", "ucas.ac.cn"],
    "Australia": ["unimelb.edu.au", "sydney.edu.au", "unsw.edu.au", "anu.edu.au", "monash.edu", "uq.edu.au",
                  "uwa.edu.au", "adelaide.edu.au", "uts.edu.au", "rmit.edu.au", "mq.edu.au"],
    "Canada": ["utoronto.ca", "mcgill.ca", "ubc.ca", "ualberta.ca", "uwaterloo.ca", "umontreal.ca", "mcmaster.ca",
               "uwo.ca", "queensu.ca", "ucalgary.ca", "uottawa.ca"],
    "Europe": ["ethz.ch", "epfl.ch", "tum.de", "psl.eu", "lmu.de", "universite-paris-saclay.fr", "tudelft.nl",
               "kuleuven.be", "uva.nl", "ku.dk", "uni-heidelberg.de", "polytechnique.edu", "sorbonne-universite.fr",
               "kth.se", "lunduniversity.lu.se", "uzh.ch", "tcd.ie", "uu.nl", "universiteitleiden.nl", "helsinki.fi",
               "polimi.it", "uu.se", "unibocconi.it", "wur.nl"],
}


GROUP_REGION = {"United States": "North America", "Canada": "North America", "United Kingdom": "Europe",
                "Europe": "Europe", "Japan": "Asia", "China": "Asia", "Singapore": "Asia", "Australia": "Asia-Pacific"}
LEVELS = ("central", "bachelors", "masters", "phd", "postdoc")


def university_seeds() -> list[dict]:
    """Load the ranked universities and their central scholarship pages per study level.

    The data comes from data/seeds/universities_*.json, one file per tier-1 group in QS 2026 order. Each file
    also replaces that group's entry in UNIVERSITY_RANKING above.
    """
    import json
    from urllib.parse import urlparse
    from .config import DATA
    out = []
    for f in sorted((DATA / "seeds").glob("universities_*.json")):
        try:
            d = json.loads(f.read_text())
        except (OSError, ValueError):
            continue
        unis = sorted(d.get("universities", []), key=lambda u: u.get("rank") or 999)
        # A university's pages can sit on several domains (washington.edu and uw.edu, say), so we give the rank
        # to every domain we see in its page list, not only the main one.
        if unis:
            UNIVERSITY_RANKING[d.get("group", f.stem)] = [
                tuple({(u.get("domain") or "").lower().removeprefix("www.")} |
                      {urlparse(x).netloc.lower().removeprefix("www.") for x in (u.get("pages") or {}).values() if x})
                for u in unis]
        for u in unis:
            out.append({**u, "group": d.get("group"), "region": GROUP_REGION.get(d.get("group"), "Global")})
    return out


def university_rank(url_or_domain: str | None) -> int | None:
    """Return the 1-based rank of a university within its country list, matched by domain or subdomain."""
    from urllib.parse import urlparse
    d = (urlparse(url_or_domain).netloc if "//" in (url_or_domain or "") else (url_or_domain or "")).lower()
    for doms in UNIVERSITY_RANKING.values():
        for i, xs in enumerate(doms):
            if any(x and (d == x or d.endswith("." + x)) for x in ((xs,) if isinstance(xs, str) else xs)):
                return i + 1
    return None


def site_priority(region: str | None, country: str | None, depth: int = 0, provider_type: str | None = None,
                  url: str | None = None) -> int:
    """Return the crawl priority for a site, lower first.

    In tier 1, national and government sources get 1, ranked universities get 2, 3, ... in bands of five, and
    unranked universities get 8. All of tier 2 comes after tier 1. Within a band, shallower pages go first.
    """
    if not tier1_group(country, region):
        return 20 + REGION_PRIORITY.get(region, 5) + depth
    rank = university_rank(url)
    if rank:
        base = 2 + (rank - 1) // 5
    elif provider_type == "university":
        base = 8
    else:
        base = 1
    return base + depth

# ---------------------------------------------------------------------------------
# The larger seed list, grouped by provider type, as (region, country, publisher, url, provider_type).
# Most entries start at the organisation's home page because home pages rarely move; the crawler then follows
# the funding, scholarship and fellowship links from there.
SEEDS_BY_PROVIDER = [
    # ---- tier 1 (D23): national programmes not covered by the hubs ----
    ("North America", "United States", "NSF Graduate Research Fellowship", "https://www.nsfgrfp.org/", "government"),
    ("North America", "United States", "Fulbright Foreign Student Program", "https://foreign.fulbrightonline.org/", "government"),
    # ---- tier 1 (D23): ranked universities, central funding pages (home page where we were unsure) ----
    ("North America", "United States", "Caltech Graduate Studies", "https://www.gradoffice.caltech.edu/", "university"),
    ("North America", "United States", "UChicagoGRAD", "https://grad.uchicago.edu/", "university"),
    ("North America", "United States", "Cornell Graduate School", "https://gradschool.cornell.edu/financial-support/", "university"),
    ("North America", "United States", "Yale GSAS", "https://gsas.yale.edu/", "university"),
    ("North America", "United States", "UCLA Graduate Division", "https://grad.ucla.edu/funding/", "university"),
    ("North America", "United States", "Northwestern TGS", "https://www.tgs.northwestern.edu/", "university"),
    ("North America", "United States", "Duke Graduate School", "https://gradschool.duke.edu/", "university"),
    ("North America", "United States", "UW Graduate School", "https://grad.uw.edu/", "university"),
    ("North America", "United States", "Illinois Graduate College", "https://grad.illinois.edu/", "university"),
    ("Europe", "United Kingdom", "King's College London", "https://www.kcl.ac.uk/", "university"),
    ("Europe", "United Kingdom", "University of Manchester", "https://www.manchester.ac.uk/", "university"),
    ("Europe", "United Kingdom", "LSE fees and funding", "https://www.lse.ac.uk/study-at-lse/Graduate/fees-and-funding", "university"),
    ("Europe", "United Kingdom", "University of Bristol", "https://www.bristol.ac.uk/", "university"),
    ("Europe", "United Kingdom", "University of Warwick", "https://warwick.ac.uk/", "university"),
    ("Asia", "Japan", "Institute of Science Tokyo", "https://www.isct.ac.jp/en", "university"),
    ("Asia", "Japan", "Nagoya University", "https://en.nagoya-u.ac.jp/", "university"),
    ("Asia", "Japan", "Kyushu University", "https://www.kyushu-u.ac.jp/en/", "university"),
    ("Asia", "Japan", "Hokkaido University", "https://www.global.hokudai.ac.jp/", "university"),
    ("Asia", "Japan", "Keio University", "https://www.keio.ac.jp/en/", "university"),
    ("Asia", "Japan", "Waseda University", "https://www.waseda.jp/top/en/", "university"),
    ("Asia", "China", "USTC", "https://en.ustc.edu.cn/", "university"),
    ("Asia", "China", "Nanjing University", "https://www.nju.edu.cn/en/", "university"),
    ("Asia", "China", "Wuhan University", "https://en.whu.edu.cn/", "university"),
    ("Asia", "China", "Tongji University", "https://en.tongji.edu.cn/", "university"),
    ("Asia", "China", "Harbin Institute of Technology", "https://en.hit.edu.cn/", "university"),
    ("Asia-Pacific", "Australia", "UTS", "https://www.uts.edu.au/", "university"),
    ("Asia-Pacific", "Australia", "RMIT University", "https://www.rmit.edu.au/", "university"),
    ("Asia-Pacific", "Australia", "Macquarie University", "https://www.mq.edu.au/", "university"),
    ("North America", "Canada", "Université de Montréal", "https://www.umontreal.ca/en/", "university"),
    ("North America", "Canada", "McMaster School of Graduate Studies", "https://gs.mcmaster.ca/", "university"),
    ("North America", "Canada", "Western University Graduate Studies", "https://grad.uwo.ca/", "university"),
    ("North America", "Canada", "Queen's SGSPA", "https://www.queensu.ca/sgsph/", "university"),
    ("North America", "Canada", "University of Calgary Graduate Studies", "https://grad.ucalgary.ca/", "university"),
    ("North America", "Canada", "University of Ottawa", "https://www.uottawa.ca/", "university"),
    ("Europe", "France", "PSL University", "https://psl.eu/en", "university"),
    ("Europe", "Germany", "Heidelberg University", "https://www.uni-heidelberg.de/en", "university"),
    ("Europe", "France", "Institut Polytechnique de Paris / École polytechnique", "https://www.polytechnique.edu/en", "university"),
    ("Europe", "France", "Sorbonne Université", "https://www.sorbonne-universite.fr/en", "university"),
    ("Europe", "Sweden", "Lund University", "https://www.lunduniversity.lu.se/", "university"),
    ("Europe", "Switzerland", "University of Zurich", "https://www.uzh.ch/en.html", "university"),
    ("Europe", "Netherlands", "Utrecht University", "https://www.uu.nl/en", "university"),
    ("Europe", "Netherlands", "Leiden University", "https://www.universiteitleiden.nl/en", "university"),
    ("Europe", "Sweden", "Uppsala University", "https://www.uu.se/en", "university"),
    ("Europe", "Italy", "Bocconi University", "https://www.unibocconi.it/en", "university"),
    ("Europe", "Netherlands", "Wageningen University", "https://www.wur.nl/en.htm", "university"),
    # ---- tier 1 (D23): countries that had few sources ----
    ("Asia", "China", "Fudan University International Students Office", "https://iso.fudan.edu.cn/", "university"),
    ("Asia", "China", "Shanghai Jiao Tong University International Students", "https://isc.sjtu.edu.cn/", "university"),
    ("Asia", "China", "Zhejiang University International College", "https://iczu.zju.edu.cn/", "university"),
    ("Asia", "China", "University of Chinese Academy of Sciences", "https://admission.ucas.ac.cn/", "university"),
    ("Asia", "China", "Yenching Academy of Peking University", "https://yenchingacademy.pku.edu.cn/", "university"),
    ("Asia", "China", "NSFC (English)", "https://www.nsfc.gov.cn/english/site_1/index.html", "government"),
    ("Asia-Pacific", "Australia", "UNSW Scholarships", "https://www.scholarships.unsw.edu.au/", "university"),
    ("Asia-Pacific", "Australia", "University of Queensland Scholarships", "https://scholarships.uq.edu.au/", "university"),
    ("Asia-Pacific", "Australia", "Monash University Scholarships",
     "https://www.monash.edu/study/fees-scholarships/scholarships", "university"),
    ("Asia-Pacific", "Australia", "UWA Scholarships", "https://www.uwa.edu.au/study/scholarships", "university"),
    ("Asia-Pacific", "Australia", "University of Adelaide Scholarships", "https://scholarships.adelaide.edu.au/", "university"),
    ("Asia-Pacific", "Australia", "Destination Australia", "https://www.education.gov.au/destination-australia", "government"),
    ("Asia-Pacific", "Australia", "Research Training Program",
     "https://www.education.gov.au/research-block-grants/research-training-program", "government"),
    ("Asia", "Japan", "JASSO Scholarships", "https://www.jasso.go.jp/en/study_j/scholarships/index.html", "government"),
    ("Asia", "Japan", "Osaka University", "https://www.osaka-u.ac.jp/en/admissions", "university"),
    ("Asia", "Japan", "Tohoku University", "https://www.tohoku.ac.jp/en/admissions/", "university"),
    ("Asia", "Japan", "RIKEN training programs", "https://www.riken.jp/en/careers/programs/", "government"),
    ("Asia", "Japan", "Rotary Yoneyama Memorial Foundation", "https://www.rotary-yoneyama.or.jp/english/", "foundation_charity"),
    ("North America", "Canada", "Banting Postdoctoral Fellowships",
     "https://banting.fellowships-bourses.gc.ca/en/home-accueil.html", "government"),
    ("North America", "Canada", "University of Waterloo GSPA", "https://uwaterloo.ca/graduate-studies-postdoctoral-affairs/", "university"),
    ("North America", "Canada", "University of Alberta Graduate Studies", "https://www.ualberta.ca/en/graduate-studies/", "university"),
    ("Europe", "United Kingdom", "Commonwealth Scholarship Commission", "https://cscuk.fcdo.gov.uk/scholarships/", "government"),
    ("Europe", "United Kingdom", "Marshall Scholarships", "https://www.marshallscholarship.org/", "government"),
    ("Europe", "United Kingdom", "Gates Cambridge", "https://www.gatescambridge.org/", "foundation_charity"),
    ("Europe", "United Kingdom", "Wellcome research funding", "https://wellcome.org/research-funding/schemes", "foundation_charity"),
    ("Europe", "United Kingdom", "Royal Society grants", "https://royalsociety.org/grants/", "learned_society"),
    ("Europe", "United Kingdom", "British Academy funding", "https://www.thebritishacademy.ac.uk/funding/", "learned_society"),
    # ---- universities: North America ----
    ("North America", "United States", "MIT", "https://oge.mit.edu/", "university"),
    ("North America", "United States", "Stanford", "https://gradadmissions.stanford.edu/", "university"),
    ("North America", "United States", "Harvard GSAS", "https://gsas.harvard.edu/", "university"),
    ("North America", "United States", "UC Berkeley Graduate Division", "https://grad.berkeley.edu/", "university"),
    ("North America", "United States", "Carnegie Mellon", "https://www.cmu.edu/graduate/", "university"),
    ("North America", "United States", "Princeton Graduate School", "https://gradschool.princeton.edu/", "university"),
    ("North America", "United States", "Columbia GSAS", "https://gsas.columbia.edu/", "university"),
    ("North America", "United States", "University of Michigan Rackham", "https://rackham.umich.edu/", "university"),
    ("North America", "Canada", "University of Toronto SGS", "https://www.sgs.utoronto.ca/", "university"),
    ("North America", "Canada", "UBC Graduate Studies", "https://www.grad.ubc.ca/", "university"),
    ("North America", "Canada", "McGill Graduate Studies", "https://www.mcgill.ca/gps/", "university"),
    # ---- universities: Europe ----
    ("Europe", "United Kingdom", "University of Oxford", "https://www.ox.ac.uk/admissions/graduate/fees-and-funding", "university"),
    ("Europe", "United Kingdom", "University of Cambridge", "https://www.postgraduate.study.cam.ac.uk/finance", "university"),
    ("Europe", "United Kingdom", "Imperial College London", "https://www.imperial.ac.uk/study/fees-and-funding/", "university"),
    ("Europe", "United Kingdom", "UCL", "https://www.ucl.ac.uk/scholarships/", "university"),
    ("Europe", "United Kingdom", "University of Edinburgh", "https://www.ed.ac.uk/student-funding", "university"),
    ("Europe", "Switzerland", "ETH Zurich", "https://ethz.ch/en/studies/financial/scholarships.html", "university"),
    ("Europe", "Switzerland", "EPFL", "https://www.epfl.ch/education/phd/", "university"),
    ("Europe", "Netherlands", "TU Delft", "https://www.tudelft.nl/en/education/admission-and-application/scholarships", "university"),
    ("Europe", "Netherlands", "University of Amsterdam", "https://www.uva.nl/en/education/fees-and-funding/scholarships-and-loans/scholarships-and-loans.html", "university"),
    ("Europe", "Germany", "TU Munich", "https://www.tum.de/en/studies/fees-and-financial-aid", "university"),
    ("Europe", "Germany", "LMU Munich", "https://www.lmu.de/en/study/all-degrees-and-programs/", "university"),
    ("Europe", "Sweden", "KTH", "https://www.kth.se/en/studies/master/admission/scholarships", "university"),
    ("Europe", "Denmark", "University of Copenhagen", "https://studies.ku.dk/masters/tuition-fees-and-scholarships/", "university"),
    ("Europe", "France", "Université Paris-Saclay", "https://www.universite-paris-saclay.fr/en/admission/bourses-et-aides-financieres", "university"),
    ("Europe", "Belgium", "KU Leuven", "https://www.kuleuven.be/english/admissions/scholarships", "university"),
    ("Europe", "Finland", "University of Helsinki", "https://www.helsinki.fi/en/admissions-and-education/tuition-fees-and-scholarships", "university"),
    ("Europe", "Ireland", "Trinity College Dublin", "https://www.tcd.ie/study/fees-funding/", "university"),
    ("Europe", "Italy", "Politecnico di Milano", "https://www.polimi.it/en/international-prospective-students/laurea-magistrale-programmes-equivalent-to-master-of-science/scholarships", "university"),
    # ---- universities: Asia ----
    ("Asia", "Singapore", "NUS", "https://nus.edu.sg/", "university"),
    ("Asia", "Singapore", "NTU", "https://www.ntu.edu.sg/", "university"),
    ("Asia", "Singapore", "SMU", "https://www.smu.edu.sg/", "university"),
    ("Asia", "Singapore", "SUTD", "https://www.sutd.edu.sg/", "university"),
    ("Asia", "Hong Kong", "HKU Graduate School", "https://gradsch.hku.hk/", "university"),
    ("Asia", "Hong Kong", "HKUST", "https://fytgs.hkust.edu.hk/", "university"),
    ("Asia", "Hong Kong", "CUHK Graduate School", "https://www.gs.cuhk.edu.hk/", "university"),
    ("Asia", "Japan", "University of Tokyo", "https://www.u-tokyo.ac.jp/en/prospective-students/", "university"),
    ("Asia", "Japan", "Kyoto University", "https://www.kyoto-u.ac.jp/en/education-campus/", "university"),
    ("Asia", "South Korea", "KAIST", "https://admission.kaist.ac.kr/intl-graduate/", "university"),
    ("Asia", "South Korea", "Seoul National University", "https://en.snu.ac.kr/admission/", "university"),
    ("Asia", "China", "Tsinghua University", "https://yz.tsinghua.edu.cn/en/", "university"),
    ("Asia", "China", "Peking University", "https://www.isd.pku.edu.cn/", "university"),
    ("Asia", "India", "IISc Bangalore", "https://iisc.ac.in/admissions/", "university"),
    ("Asia", "Malaysia", "Universiti Malaya", "https://www.um.edu.my/", "university"),
    ("Asia", "Saudi Arabia", "KAUST", "https://www.kaust.edu.sa/en/", "university"),
    ("Asia", "Israel", "Weizmann Institute", "https://www.weizmann.ac.il/feinberg/", "research_institute"),
    ("Asia-Pacific", "Australia", "University of Melbourne", "https://scholarships.unimelb.edu.au/", "university"),
    ("Asia-Pacific", "Australia", "ANU", "https://study.anu.edu.au/scholarships", "university"),
    ("Asia-Pacific", "Australia", "University of Sydney", "https://www.sydney.edu.au/scholarships/", "university"),
    ("Asia-Pacific", "New Zealand", "University of Auckland", "https://www.auckland.ac.nz/en/study/scholarships-and-awards.html", "university"),
    # ---- universities: South America ----
    ("South America", "Brazil", "University of São Paulo", "https://www5.usp.br/", "university"),
    ("South America", "Chile", "Pontificia Universidad Católica de Chile", "https://www.uc.cl/", "university"),
    ("South America", "Argentina", "Universidad de Buenos Aires", "https://www.uba.ar/", "university"),
    ("South America", "Colombia", "Universidad de los Andes", "https://uniandes.edu.co/", "university"),
    ("North America", "Mexico", "UNAM", "https://www.unam.mx/", "university"),
    # ---- foundations / charities ----
    ("North America", "United States", "Gates Foundation", "https://www.gatesfoundation.org/about/how-we-work/general-information/grant-opportunities", "foundation_charity"),
    ("North America", "United States", "Howard Hughes Medical Institute", "https://www.hhmi.org/programs", "foundation_charity"),
    ("North America", "United States", "Paul & Daisy Soros Fellowships", "https://www.pdsoros.org/", "foundation_charity"),
    ("North America", "United States", "Rockefeller Foundation", "https://www.rockefellerfoundation.org/", "foundation_charity"),
    ("North America", "United States", "Mastercard Foundation Scholars", "https://mastercardfdn.org/en/what-we-do/our-programs/mastercard-foundation-scholars-program/", "foundation_charity"),
    ("North America", "United States", "Open Philanthropy", "https://www.openphilanthropy.org/", "foundation_charity"),
    ("North America", "United States", "Burroughs Wellcome Fund", "https://www.bwfund.org/funding-opportunities/", "foundation_charity"),
    ("North America", "United States", "Alfred P. Sloan Foundation", "https://sloan.org/", "foundation_charity"),
    ("North America", "United States", "Kavli Foundation", "https://www.kavlifoundation.org/", "foundation_charity"),
    ("Europe", "Germany", "Volkswagen Foundation", "https://www.volkswagenstiftung.de/en/funding", "foundation_charity"),
    ("Europe", "Germany", "Konrad-Adenauer-Stiftung", "https://www.kas.de/en/web/begabtenfoerderung-und-kultur", "foundation_charity"),
    ("Europe", "Germany", "Heinrich Böll Foundation", "https://www.boell.de/en/scholarships", "foundation_charity"),
    ("Europe", "Germany", "Friedrich Ebert Foundation", "https://www.fes.de/en/", "foundation_charity"),
    ("Europe", "Germany", "Boehringer Ingelheim Fonds", "https://www.bifonds.de/", "foundation_charity"),
    ("Europe", "Switzerland", "Branco Weiss Fellowship", "https://brancoweissfellowship.org/", "foundation_charity"),
    ("Europe", "United Kingdom", "Leverhulme Trust", "https://www.leverhulme.ac.uk/", "foundation_charity"),
    ("Europe", "United Kingdom", "Royal Commission for the Exhibition of 1851", "https://www.royalcommission1851.org/", "foundation_charity"),
    ("Europe", "United Kingdom", "Cancer Research UK", "https://www.cancerresearchuk.org/funding-for-researchers", "foundation_charity"),
    ("Europe", "Denmark", "Novo Nordisk Foundation", "https://novonordiskfonden.dk/en/", "foundation_charity"),
    ("Europe", "Denmark", "Carlsberg Foundation", "https://www.carlsbergfondet.dk/en/", "foundation_charity"),
    ("Europe", "Sweden", "Knut and Alice Wallenberg Foundation", "https://kaw.wallenberg.org/en", "foundation_charity"),
    ("Europe", "Europe", "Fondation Bettencourt Schueller", "https://www.fondationbs.org/en", "foundation_charity"),
    ("Asia", "Japan", "Japan Foundation", "https://www.jpf.go.jp/e/", "foundation_charity"),
    ("Asia", "Japan", "Nakajima Foundation", "https://www.nakajimafound.or.jp/english/", "foundation_charity"),
    ("Asia", "Singapore", "Lee Kuan Yew School / LKY scholarships", "https://lkyspp.nus.edu.sg/", "university"),
    ("Global", "Global", "Wellcome Trust", "https://wellcome.org/", "foundation_charity"),
    ("Global", "Global", "Aga Khan Foundation", "https://the.akdn/en/", "foundation_charity"),
    ("Global", "Global", "OWSD (women in science)", "https://owsd.net/", "foundation_charity"),
    ("Global", "Global", "TWAS", "https://twas.org/", "intergovernmental"),
    # ---- industry research ----
    ("Global", "Global", "Meta Research", "https://research.facebook.com/fellows/", "industry"),
    ("Global", "Global", "Apple Machine Learning Research", "https://machinelearning.apple.com/work-with-us", "industry"),
    ("Global", "Global", "Amazon Science", "https://www.amazon.science/academic-engagements", "industry"),
    ("Global", "Global", "IBM Research", "https://research.ibm.com/", "industry"),
    ("Global", "Global", "Qualcomm Research", "https://www.qualcomm.com/research/university-relations", "industry"),
    ("Global", "Global", "Adobe Research", "https://research.adobe.com/", "industry"),
    ("Global", "Global", "Intel Labs", "https://www.intel.com/content/www/us/en/research/overview.html", "industry"),
    ("Global", "Global", "Samsung Research", "https://research.samsung.com/", "industry"),
    ("Global", "Global", "Jane Street", "https://www.janestreet.com/join-jane-street/programs-and-events/", "industry"),
    ("Global", "Global", "Two Sigma", "https://www.twosigma.com/", "industry"),
    ("Global", "Global", "Bosch Research", "https://www.bosch.com/research/", "industry"),
    ("Global", "Global", "Siemens Research", "https://www.siemens.com/", "industry"),
    ("Asia", "Singapore", "AI Singapore (industry-linked)", "https://aisingapore.org/", "industry"),
    # ---- intergovernmental ----
    ("Global", "Global", "UNESCO", "https://www.unesco.org/en/fellowships", "intergovernmental"),
    ("Global", "Global", "United Nations University", "https://unu.edu/", "intergovernmental"),
    ("Global", "Global", "WHO", "https://www.who.int/careers", "intergovernmental"),
    ("Global", "Global", "IAEA", "https://www.iaea.org/about/employment/fellowships", "intergovernmental"),
    ("Global", "Global", "CERN", "https://careers.cern/", "intergovernmental"),
    ("Europe", "Europe", "EMBL", "https://www.embl.org/about/info/embl-international-phd-programme/", "intergovernmental"),
    ("Europe", "Europe", "ESA", "https://www.esa.int/About_Us/Careers_at_ESA", "intergovernmental"),
    ("Global", "Global", "OECD", "https://www.oecd.org/careers/", "intergovernmental"),
    ("Asia", "Asia", "Asian Development Bank", "https://www.adb.org/work-with-us/careers/japan-scholarship-program", "intergovernmental"),
    ("Global", "Global", "Commonwealth Secretariat", "https://thecommonwealth.org/", "intergovernmental"),
    ("Global", "Global", "ICTP (Trieste)", "https://www.ictp.it/", "intergovernmental"),
    ("Global", "Global", "IIASA", "https://iiasa.ac.at/", "intergovernmental"),
    # ---- government (more) ----
    ("North America", "United States", "NIH Grants (individual fellowships)", "https://grants.nih.gov/funding/", "government"),
    ("North America", "United States", "NASA Fellowships", "https://science.nasa.gov/researchers/", "government"),
    ("North America", "Canada", "SSHRC", "https://www.sshrc-crsh.gc.ca/funding-financement/", "government"),
    ("North America", "Canada", "CIHR", "https://cihr-irsc.gc.ca/e/193.html", "government"),
    ("Europe", "Norway", "Research Council of Norway", "https://www.forskningsradet.no/en/", "government"),
    ("Europe", "Finland", "Research Council of Finland", "https://www.aka.fi/en/", "government"),
    ("Europe", "Spain", "La Caixa Foundation fellowships", "https://lacaixafellowships.org/", "foundation_charity"),
    ("Europe", "Portugal", "FCT", "https://www.fct.pt/en/", "government"),
    ("Europe", "Belgium", "FWO", "https://www.fwo.be/en/", "government"),
    ("Europe", "Poland", "NAWA", "https://nawa.gov.pl/en/", "government"),
    ("Europe", "Czech Republic", "Czech Government Scholarships", "https://www.msmt.cz/", "government"),
    ("Europe", "Hungary", "Stipendium Hungaricum", "https://stipendiumhungaricum.hu/", "government"),
    ("Europe", "Ireland", "Irish Research Council", "https://research.ie/", "government"),
    ("Asia", "South Korea", "National Research Foundation of Korea", "https://www.nrf.re.kr/eng/", "government"),
    ("Asia", "China", "China Scholarship Council", "https://www.csc.edu.cn/", "government"),
    ("Asia", "India", "SERB / ANRF", "https://www.anrfonline.in/", "government"),
    ("Asia", "Japan", "JST", "https://www.jst.go.jp/EN/", "government"),
    ("Asia", "Singapore", "Public Service Commission Scholarships", "https://www.psc.gov.sg/scholarships/", "government"),
    ("Asia", "Singapore", "Singapore International Foundation", "https://www.sif.org.sg/", "foundation_charity"),
    # Singapore universities and agencies. We seed the scholarship sections directly because the home pages
    # only link to them several levels down.
    ("Asia", "Singapore", "NUS", "https://www.nus.edu.sg/oam/scholarships", "university"),
    ("Asia", "Singapore", "NUS", "https://nusgs.nus.edu.sg/scholarships/", "university"),
    ("Asia", "Singapore", "NUS", "https://cde.nus.edu.sg/graduate/graduate-programmes-by-research/scholarships/",
     "university"),
    ("Asia", "Singapore", "SMU", "https://admissions.smu.edu.sg/financial-matters/scholarships", "university"),
    ("Asia", "Singapore", "SMU", "https://graduatestudies.smu.edu.sg/scholarships", "university"),
    ("Asia", "Singapore", "SUTD", "https://www.sutd.edu.sg/admissions/undergraduate/scholarship/", "university"),
    ("Asia", "Singapore", "SIT", "https://www.singaporetech.edu.sg/admissions/undergraduate/scholarships", "university"),
    ("Asia", "Singapore", "SUSS", "https://www.suss.edu.sg/full-time-undergraduate/scholarships-and-financial-aid",
     "university"),
    ("Asia", "Singapore", "NIE", "https://www.ntu.edu.sg/nie/admissions/scholarships-awards", "university"),
    ("Asia", "Singapore", "Ministry of Education", "https://www.moe.gov.sg/financial-matters/awards-scholarships",
     "government"),
    ("Asia", "Singapore", "EDB", "https://www.edb.gov.sg/en/about-edb/careers/scholarships.html", "government"),
    ("Asia", "Singapore", "IMDA", "https://www.imda.gov.sg/how-we-can-help/scholarships", "government"),
    # PhD funding open to international applicants, since this is the Singapore search students ask for most
    ("Asia", "Singapore", "A*STAR", "https://www.a-star.edu.sg/Scholarships/for-graduate-studies/"
     "singapore-international-graduate-award-singa", "government"),
    ("Asia", "Singapore", "A*STAR", "https://www.a-star.edu.sg/Scholarships/for-graduate-studies", "government"),
    ("Asia", "Singapore", "NUS", "https://nusgs.nus.edu.sg/scholarships/nus-research-scholarship/", "university"),
    ("Asia", "Singapore", "NUS", "https://nusgs.nus.edu.sg/scholarships/president-graduate-fellowship/", "university"),
    ("Asia", "Singapore", "SMU", "https://graduatestudies.smu.edu.sg/phd-scholarships", "university"),
    ("Asia", "Singapore", "SUTD", "https://www.sutd.edu.sg/admissions/graduate/phd/scholarships", "university"),
    ("Asia", "Singapore", "NTU", "https://www.ntu.edu.sg/admissions/graduate/financialmatters/scholarships/"
     "research-scholarships", "university"),
    ("Asia-Pacific", "Australia", "NHMRC", "https://www.nhmrc.gov.au/funding", "government"),
    ("South America", "Brazil", "FAPESP", "https://fapesp.br/en/", "government"),
    ("South America", "Peru", "PRONABEC", "https://www.pronabec.gob.pe/", "government"),
    ("South America", "Ecuador", "SENESCYT", "https://www.educacionsuperior.gob.ec/", "government"),
]
