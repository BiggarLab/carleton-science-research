"""Probe the USPTO Open Data Portal with the PATENTSVIEW_API_KEY secret. Prints structure and counts only, never the key."""
import json, os, urllib.request, urllib.error
from pathlib import Path

key = os.environ.get("PATENTSVIEW_API_KEY", "").strip()
out = []


def call(body):
    req = urllib.request.Request("https://api.uspto.gov/api/v1/patent/applications/search", data=json.dumps(body).encode(),
                                 headers={"X-API-KEY": key, "Content-Type": "application/json", "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        return {"error": e.code, "body": e.read().decode("utf-8", "replace")[:300]}


def shape(o, depth=0):
    if isinstance(o, dict):
        return {k: shape(v, depth + 1) for k, v in list(o.items())[:40]} if depth < 4 else "{...}"
    if isinstance(o, list):
        return [shape(o[0], depth + 1)] if o else []
    return type(o).__name__ if not isinstance(o, str) else (o[:40])


for label, q in [("first applicant exact", 'applicationMetaData.firstApplicantName:"Carleton University"'),
                 ("applicant bag", 'applicationMetaData.applicantBag.applicantNameText:"Carleton University"'),
                 ("free text carleton university", '"Carleton University"'),
                 ("assignment", 'assignmentBag.assigneeBag.assigneeNameText:"Carleton University"'),
                 ("title words since 2023", 'applicationMetaData.inventionTitle:(peptide AND inhibitor) AND applicationMetaData.filingDate:[2023-01-01 TO 2026-12-31]')]:
    d = call({"q": q, "pagination": {"offset": 0, "limit": 2}})
    out.append(f"{label}: count={d.get('count')} error={d.get('error')} {d.get('body', '')}")
d = call({"q": 'applicationMetaData.firstApplicantName:"Carleton University"', "pagination": {"offset": 0, "limit": 1}})
out.append(json.dumps(shape((d.get("patentFileWrapperDataBag") or [{}])[0]), indent=1)[:6000])
Path(__file__).resolve().parent.parent.joinpath("state/key_check.log").write_text("\n".join(out) + "\n")
print("\n".join(out))
