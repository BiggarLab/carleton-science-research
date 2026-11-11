"""Weekly digest for a Faculty that is defined by a roster in the university-wide build (Public and Global Affairs).

Same format as the Science digest, as its own page and its own email, without partnership signals or the innovation screen.
People and their OpenAlex profiles come from docs/university/data.json, so this runs after scripts/university.py.

Saved issues: state/fpga/issues/*.json. Pages: docs/digest/fpga/. State: state/fpga/digest_state.json.
Email goes to FPGA_DIGEST_TO if that is set, otherwise to DIGEST_TO.
"""
import argparse
import datetime as dt
import json
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import update as U  # noqa: E402
from render_digest import render_email, render_text, week_label  # noqa: E402

FACULTY = "Public and Global Affairs"
SHORT = "FPGA"
STATE = U.ROOT / "state/fpga"
BRAND = {"title": f"New from Carleton {SHORT}", "page_title": f"{SHORT} Weekly Digest",
         "empty": f"No new Faculty of {FACULTY} outputs were indexed this week.", "dash_label": "Open the university dashboard",
         "foot": ("Summaries were written by Claude from each paper's abstract, so check the paper before quoting. Outputs are matched to the Faculty list "
                  "using OpenAlex, which can miss outputs (books, chapters, law reviews and reports especially) or lag a few weeks behind publication.")}


def load_people():
    d = json.loads((U.ROOT / "docs/university/data.json").read_text(encoding="utf-8"))
    return [p for p in d["people"] if "roster" in p.get("ev", []) and FACULTY in p.get("fac", [])]


def fetch_works(people, since):
    """Recent outputs by these people where the paper lists them at Carleton. Returns {work id: {"raw": work, "f": [people indexes]}}."""
    who = {}
    for i, p in enumerate(people):
        for a in p["oa"]:
            who.setdefault(a, []).append(i)
    ids, works = sorted(who), {}
    for k in range(0, len(ids), 40):
        chunk = ids[k:k + 40]
        for w in U.oa_pages("works", {"filter": f"author.id:{'|'.join(chunk)},from_publication_date:{since}", "select": U.SELECT}):
            au = w.get("authorships") or []
            f = set()
            for a in au:
                aid = ((a.get("author") or {}).get("id") or "").split("/")[-1]
                if aid not in who:
                    continue
                insts = [x.get("id") for x in a.get("institutions") or []]
                raw = " ".join(a.get("raw_affiliation_strings") or [])
                if U.CARLETON in insts or re.search("carleton", raw, re.I) or len(au) >= 100:
                    f.update(who[aid])
            if f:
                rec = works.setdefault(w["id"].split("/")[-1], {"raw": w, "f": []})
                rec["f"] = sorted(set(rec["f"]) | f)
    return works


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-email", action="store_true")
    ap.add_argument("--no-ai", action="store_true")
    ap.add_argument("--force", action="store_true", help="rebuild this week's issue even if it was already made")
    ap.add_argument("--week-end")
    a = ap.parse_args()
    today = dt.date.today()
    week_end = dt.date.fromisoformat(a.week_end) if a.week_end else today - dt.timedelta(days=today.weekday() + 1)
    week_start = week_end - dt.timedelta(days=6)
    (STATE / "issues").mkdir(parents=True, exist_ok=True)
    state_p = STATE / "digest_state.json"
    state = json.loads(state_p.read_text()) if state_p.exists() else {"last_issue": 0, "seen": []}
    prev = STATE / f"issues/{week_end.isoformat()}.json"
    if state.get("last_week_end") == week_end.isoformat():
        if not a.force:
            U.log(f"This week's {SHORT} digest was already made. Use --force to rebuild it.")
            return
        state["last_issue"] = max(state.get("last_issue", 1) - 1, 0)
        if prev.exists():  # let this week's papers be summarized again
            done = {it.get("id") for u in json.loads(prev.read_text(encoding="utf-8"))["units"] for it in u["items"]}
            state["seen"] = [x for x in state.get("seen", []) if x not in done]

    people = load_people()
    U.log(f"{SHORT} digest: {len(people)} people on the roster, {sum(bool(p['oa']) for p in people)} with an OpenAlex profile")
    works = fetch_works(people, (week_end - dt.timedelta(days=60)).isoformat())
    issue, new_ids = U.make_issue({"people": people}, works, state, week_start, week_end, use_ai=not a.no_ai, innovate=False, faculty=f"Faculty of {FACULTY}")
    issue["brand"] = BRAND
    if issue.get("also"):
        issue["also_title"] = "Working papers and preprints"
    prev.write_text(json.dumps(issue, ensure_ascii=False, indent=1), encoding="utf-8")
    U.render_all()
    state.update({"last_week_end": week_end.isoformat(), "last_issue": issue["issue"], "seen": sorted(set(state.get("seen", [])) | set(new_ids))})
    state_p.write_text(json.dumps(state, indent=1))
    if not a.no_email:
        site = U.CFG.get("site_url", "").rstrip("/")
        web, dash = (f"{site}/digest/fpga/", f"{site}/university/") if site else ("", "")
        U.send_mail(f"Carleton {SHORT} research digest: {week_label(issue)}", render_email(issue, web, dash), render_text(issue, dash),
                    to=os.environ.get("FPGA_DIGEST_TO") or None, from_name=f"Carleton {SHORT} Digest")


if __name__ == "__main__":
    main()
