"""Report which USPTO service accepts the PATENTSVIEW_API_KEY secret. Prints status codes only, never the key."""
import json, os, urllib.request, urllib.error
from pathlib import Path

key = os.environ.get("PATENTSVIEW_API_KEY", "").strip()
out = [f"key present: {bool(key)} (length {len(key)})"]


def call(name, url, headers, body=None):
    req = urllib.request.Request(url, data=json.dumps(body).encode() if body is not None else None, headers={**headers, "Content-Type": "application/json", "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            txt = r.read().decode("utf-8", "replace")
            out.append(f"{name}: HTTP {r.status}; {txt[:300]}")
    except urllib.error.HTTPError as e:
        out.append(f"{name}: HTTP {e.code}; {e.read().decode('utf-8', 'replace')[:300]}")
    except Exception as e:
        out.append(f"{name}: failed ({e})")


if key:
    call("PatentsView PatentSearch", "https://search.patentsview.org/api/v1/patent/", {"X-Api-Key": key},
         {"q": {"_text_phrase": {"assignees.assignee_organization": "Carleton University"}}, "f": ["patent_id", "patent_title", "patent_date"], "o": {"size": 3}})
    call("USPTO Open Data Portal", "https://api.uspto.gov/api/v1/patent/applications/search", {"X-API-KEY": key},
         {"q": "applicationMetaData.firstApplicantName:\"Carleton University\"", "pagination": {"offset": 0, "limit": 3}})
Path(__file__).resolve().parent.parent.joinpath("state/key_check.log").write_text("\n".join(out) + "\n")
print("\n".join(out))
