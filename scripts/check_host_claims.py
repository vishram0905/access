"""Panel-check the "where held" claim of records resolved by resolve_host_countries.py (tooling, Layer 0).

We hold it to the same standard as every claim we display (see docs/DECISIONS.md, D22): the quote must be found
on the page, and then a majority of a panel of models from three different companies must confirm the list. An
unconfirmed claim becomes "Not stated", which still shows up in every country search. We only ask about the host
claim, so the record's other verified claims stay as they are.

Run: PYTHONPATH=. python scripts/check_host_claims.py
"""
import json
import time

from access import factcheck, resources
from access.config import ROLES
from access.db import connect
from access.llm import set_role


def main():
    """Check every resolved host claim that has no verdict yet, and write the result back to its listing."""
    set_role("critic")
    with connect() as con:
        rows = con.execute("SELECT l.id, l.data, s.text FROM listings l JOIN sources s ON s.url = l.source_url "
                           "WHERE json_extract(l.data, '$.host_resolved') = 1 "
                           "AND json_extract(l.data, '$.verification.claims.host') IS NULL").fetchall()
    print(len(rows), "host claims to check", flush=True)
    kept = dropped = 0
    rows = list(rows)
    for row in rows:
        listing = json.loads(row["data"])
        claim = [c for c in factcheck.claims(listing, row["text"] or "") if c["id"] == "host"]
        if not claim:
            continue
        c = claim[0]
        if c["located"]:
            while True:
                panel, wait = resources.pick_panel(ROLES["judge_pool"], "critic", 3)
                if len({j.family for j in panel}) == 3:
                    break
                print(time.strftime("%H:%M"), "waiting for a full panel", round(wait), "s", flush=True)
                time.sleep(min(max(wait, 60), 900))
            verdicts = [factcheck._ask(j, listing, [c], "critic") for j in panel]
            valid = [v for v in verdicts if "error" not in v]
            # We never decide on a short panel. Failed judges are benched and the record goes back in the queue.
            if len({v["family"] for v in valid}) < 3:
                for v in verdicts:
                    if "error" in v:
                        spec = next(j for j in panel if j.label == v["judge"])
                        resources.bench(spec.model, "timeout" if "imeout" in v["error"] else "error")
                print("  short panel, will retry:", "; ".join(v["error"][:50] for v in verdicts if "error" in v),
                      flush=True)
                rows.append(row)  # back of the queue
                continue
            votes = [v["votes"]["host"] for v in valid if "host" in v["votes"]]
            res = {"kind": "host", "located": True, "yes": sum(votes), "of": len(votes),
                   "confirmed": len(votes) >= 2 and sum(votes) >= len(votes) // 2 + 1,
                   "judges": [f"{j.label} ({j.family})" for j in panel]}
        else:
            res = {"kind": "host", "located": False, "yes": 0, "of": 0, "confirmed": False}
        was = listing["host_country"]
        if not res["confirmed"]:
            listing.update(host_countries=[], host_regions=[], host_anywhere=False, host_resolved=False,
                           host_evidence=None, host_country="Not stated", region="Global")
            listing.setdefault("facts_unconfirmed", []).append(f"host: {was}")
            dropped += 1
        else:
            kept += 1
        listing.setdefault("verification", {}).setdefault("claims", {})["host"] = res
        with connect() as con:
            con.execute("UPDATE listings SET data = ? WHERE id = ?", (json.dumps(listing), row["id"]))
        print(f'{"KEPT" if res["confirmed"] else "DROP"} {res["yes"]}/{res["of"]}  {was[:40]:<40} '
              f'{listing["name"][:45]}', flush=True)
    print(f"DONE kept {kept}, dropped to 'Not stated' {dropped}", flush=True)


if __name__ == "__main__":
    main()
