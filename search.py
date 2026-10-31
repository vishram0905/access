"""Command-line search over the ACCESS lookup document (tooling).

We use this to try a profile quickly without opening the web app.

  python search.py --persona Priya                 # fast lookup only (no model agents), under a second
  python search.py --persona Priya --agents        # full multi-agent pipeline
  python search.py --json my_profile.json --agents
  python search.py --stats                         # what is in the lookup document
"""
import argparse
import json
import sys
import time

from access.evaluation import PERSONAS
from access.lookup import load


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--persona", help="name of an example researcher (Priya, Wei Ling, Daniel, Amara)")
    ap.add_argument("--json", help="path to a profile JSON file (same keys as the app form)")
    ap.add_argument("--agents", action="store_true", help="run the full multi-agent pipeline")
    ap.add_argument("--stats", action="store_true")
    ap.add_argument("-k", type=int, default=10)
    a = ap.parse_args()

    programs, facets, vecs, meta = load()
    if a.stats or not (a.persona or a.json):
        print(json.dumps(meta, indent=1))
        return
    form = json.load(open(a.json)) if a.json else next(
        f for label, f in PERSONAS.items() if f["name"].lower() == a.persona.lower())

    t = time.time()
    if a.agents:
        from access.pipeline import run
        res = run(form)
        print(f"\nFull pipeline in {time.time() - t:.1f}s")
        for i, x in enumerate(res["shortlist"][:a.k], 1):
            adv = x.get("advice") or {}
            print(f"{i:>2}. {x['name']}  ({x['score']}/100) - {x.get('why', '')}")
            for s in adv.get("steps", [])[:4]:
                print(f"      • {s}")
        for x in res["near_misses"][:5]:
            adv = x.get("advice") or {}
            print(f" ~  {x['name']}: {adv.get('close_the_gap') or '; '.join(c['why'] for c in x['gate']['checks'] if c['status'] == 'near')}")
        return

    from access.profile import search_query
    from access.search import search
    profile = {**form, "fields": form.get("fields") or ["any"], "keywords": [], "goals": "",
               "research_summary": form.get("about", "")}
    res = search(profile, search_query(profile), k=a.k,
                 filters={"host_country": form.get("target_countries"), "opportunity_type": form.get("wanted_types")})
    st = res["stats"]
    print(f"Lookup search: {st['programmes']} programmes, {st['ms']} ms, filters {st['filters_applied'] or 'none'}")
    print(f"{st['eligible_total']} eligible · {st['near_total']} near-misses · {st['excluded_total']} excluded\n")
    for i, x in enumerate(res["eligible"][:a.k], 1):
        print(f"{i:>2}. {x['name'][:70]:<70} {x.get('host_country', '')[:15]:<15} sim {res['similarity'][x['id']]:.2f}")
    for x in res["near_miss"][:5]:
        print(f" ~  {x['name'][:70]:<70} " + "; ".join(c['why'] for c in x['gate']['checks'] if c['status'] == 'near'))


if __name__ == "__main__":
    sys.exit(main())
