"""Partnership and IP signals for the Carleton Faculty of Science dashboard.

Turns raw publication data into research lines (one researcher working on one topic over
several papers) and scores each line on evidence that industry already cares:

  company co-authors     companies on the author list of our papers           (OpenAlex)
  company citers         companies whose own papers cite our papers           (OpenAlex)
  industry funding       Mitacs, NSERC Alliance/CRD/Engage, OCI, company funders (OpenAlex funders and awards)
  NSERC partners         partner organizations on the researcher's NSERC grants (NSERC open data, if reachable)
  patents                patents with the researcher as inventor and Carleton as applicant (Lens.org, if LENS_API_TOKEN is set)
  preprint clock         preprints in the last 12 months (patent grace period still open in Canada and the US)
  CV signals             grants, theses and other items from config/cv_signals.csv, when that file exists

Every source is optional except OpenAlex. Anything unreachable is skipped and logged.
"""
import csv
import datetime as dt
import io
import json
import os
import re
import unicodedata
import urllib.error
import urllib.request
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CARLETON = "https://openalex.org/I67031392"

INDUSTRY_AWARD_PREFIX = re.compile(r"^(ALLRP|ALLIANCE|CRDPJ|CRD|EGP|EGP2|IT\d|ARPPJ|IRAP|CREATE)", re.I)
INDUSTRY_FUNDER = re.compile(r"mitacs|ontario cent(re|er)s? (of|for) (excellence|innovation)|\bOCI\b|industrial research assistance|"
                             r"\b(inc|ltd|llc|corp|corporation|gmbh|s\.a\.|ag|plc|limited|pharmaceuticals?|technologies)\b\.?$", re.I)


def log(*a):
    print(*a, flush=True)


def norm(s):
    return re.sub(r"\s+", " ", re.sub(r"[^a-z ]", " ", unicodedata.normalize("NFD", str(s)).encode("ascii", "ignore").decode().lower())).strip()


# ------------------------------------------------------------------ per-work signals
def work_signals(raw):
    """Company co-authors, funders, industry funding and per-author roles for one OpenAlex work."""
    au = raw.get("authorships") or []
    companies = set()
    if len(au) < 100:
        for a in au:
            for x in a.get("institutions") or []:
                if (x.get("type") or "") == "company" and x.get("display_name"):
                    companies.add(x["display_name"])
    funders = sorted({f.get("display_name") for f in raw.get("funders") or [] if f.get("display_name")})
    industry = set()
    for aw in raw.get("awards") or []:
        aid = (aw.get("funder_award_id") or "").strip()
        if INDUSTRY_AWARD_PREFIX.match(aid):
            industry.add(f"{aw.get('funder_display_name') or 'Grant'} {aid}")
    for f in funders:
        if INDUSTRY_FUNDER.search(f):
            industry.add(f)
    roles = {}
    n = len(au)
    for k, a in enumerate(au):
        aid = ((a.get("author") or {}).get("id") or "").split("/")[-1]
        lead = k == 0 or k == n - 1 or bool(a.get("is_corresponding"))
        roles[aid] = lead
    return {"companies": sorted(companies), "funders": funders, "industry": sorted(industry), "roles": roles}


# ------------------------------------------------------------------ companies citing our work
def company_citers(works, y0, oa_pages, batch=50, max_pages=3):
    """Map Carleton work id -> set of company names on papers that cite it."""
    ids = [wid for wid, rec in works.items() if len(rec["raw"].get("authorships") or []) < 100]
    out = defaultdict(set)
    calls = 0
    for i in range(0, len(ids), batch):
        chunk = ids[i:i + batch]
        want = set(chunk)
        try:
            pages = 0
            for w in oa_pages("works", {"filter": f"cites:{'|'.join(chunk)},authorships.institutions.type:company,from_publication_date:{y0}-01-01",
                                        "select": "id,referenced_works,authorships"}):
                comps = {x.get("display_name") for a in (w.get("authorships") or []) for x in (a.get("institutions") or [])
                         if (x.get("type") or "") == "company" and x.get("display_name")}
                if not comps:
                    continue
                for ref in w.get("referenced_works") or []:
                    rid = ref.split("/")[-1]
                    if rid in want:
                        out[rid] |= comps
                pages += 1
                if pages >= max_pages * 100:
                    break
            calls += 1
        except Exception as e:
            log("company citer lookup failed for a batch:", e)
    log(f"company citers: {sum(len(v) for v in out.values())} company links across {len(out)} papers ({calls} batches)")
    return out


# ------------------------------------------------------------------ NSERC open data (optional)
NSERC_BASES = ["https://www.nserc-crsng.gc.ca/opendata/", "https://nserc-crsng.canada.ca/opendata/"]


def _get_csv(url):
    req = urllib.request.Request(url, headers={"User-Agent": "carleton-science-digest"})
    with urllib.request.urlopen(req, timeout=120) as r:
        b = r.read()
    for enc in ("utf-8-sig", "cp1252", "latin-1"):
        try:
            txt = b.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    if "<html" in txt[:500].lower():
        raise ValueError("got a web page, not a CSV")
    return list(csv.DictReader(io.StringIO(txt)))


def _col(headers, *needles, avoid=()):
    for h in headers:
        hl = norm(h)
        if any(n in hl for n in needles) and not any(a in hl for a in avoid):
            return h
    return None


def nserc_partners(people, years=4):
    """Return {person index: [{"partner", "program", "title", "year"}]} from NSERC partner and award files."""
    files = sorted((ROOT / "config/nserc").glob("*.csv")) if (ROOT / "config/nserc").exists() else []
    this_fy = dt.date.today().year - (0 if dt.date.today().month >= 4 else 1)
    pairs = []
    for fy in range(this_fy, this_fy - years - 1, -1):
        aw = pa = None
        for base in NSERC_BASES:
            try:
                aw = _get_csv(f"{base}NSERC_FY{fy}_Expenditures.csv")
                pa = _get_csv(f"{base}NSERC_FY{fy}_PARTNER.csv")
                break
            except Exception:
                aw = pa = None
        if aw and pa:
            pairs.append((fy, aw, pa))
    for f in files:  # manual downloads: config/nserc/<anything>_Expenditures.csv + <anything>_PARTNER.csv
        if "expenditure" in f.name.lower():
            p = f.with_name(f.name.lower().replace("expenditures", "partner"))
            cand = [x for x in files if x.name.lower() == p.name]
            if cand:
                pairs.append((f.stem, _read_local(f), _read_local(cand[0])))
    if not pairs:
        log("NSERC open data not reachable and no files in config/nserc; skipping NSERC partners")
        return {}
    by_last = defaultdict(list)
    for i, p in enumerate(people):
        last, _, first = p["sort"].partition(", ")
        by_last[norm(last)].append((i, norm(first)[:3]))
    out = defaultdict(list)
    for fy, aw, pa in pairs:
        ah, ph = list(aw[0].keys()), list(pa[0].keys())
        key = next((h for h in ah if h in ph and re.search(r"cle|key|id", norm(h))), None) or next((h for h in ah if h in ph), None)
        name_c = _col(ah, "name", "nom", avoid=("partner", "partenaire", "organization", "program", "institution"))
        inst_c = _col(ah, "institution", "etablissement")
        prog_c = _col(ah, "program")
        title_c = _col(ah, "title", "titre")
        part_c = _col(ph, "partner", "partenaire", "organization", "organisme", avoid=("type", "id", "province", "country", "pays"))
        if not (key and name_c and inst_c and part_c):
            log(f"NSERC FY{fy}: unexpected columns, skipped. Award columns: {ah[:12]} Partner columns: {ph[:8]}")
            continue
        partners = defaultdict(set)
        for r in pa:
            if r.get(part_c):
                partners[r[key]].add(r[part_c].strip())
        hits = 0
        for r in aw:
            if "carleton" not in norm(r.get(inst_c, "")) or r.get(key) not in partners:
                continue
            nm = r.get(name_c, "")
            last, _, first = nm.partition(",")
            for i, f3 in by_last.get(norm(last), []):
                if not f3 or norm(first).startswith(f3):
                    for prt in partners[r[key]]:
                        out[i].append({"partner": prt, "program": r.get(prog_c, ""), "title": r.get(title_c, ""), "year": str(fy)})
                    hits += 1
        log(f"NSERC FY{fy}: {hits} Carleton Science grants with partners")
    return dict(out)


def _read_local(p):
    b = p.read_bytes()
    for enc in ("utf-8-sig", "cp1252", "latin-1"):
        try:
            return list(csv.DictReader(io.StringIO(b.decode(enc))))
        except UnicodeDecodeError:
            continue
    return []


# ------------------------------------------------------------------ patents via Lens.org (optional)
def _lens(query, size=50, include=None):
    tok = os.environ.get("LENS_API_TOKEN")
    body = {"query": query, "size": size}
    if include:
        body["include"] = include
    req = urllib.request.Request("https://api.lens.org/patent/search", data=json.dumps(body).encode(),
                                 headers={"Authorization": f"Bearer {tok}", "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read())


def _names(obj, keys=("applicants", "applicant")):
    """Pull applicant names out of a Lens record without depending on one exact schema."""
    out = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k in keys and isinstance(v, list):
                for a in v:
                    n = (a.get("extracted_name") or {}).get("value") if isinstance(a, dict) else None
                    n = n or (a.get("name") if isinstance(a, dict) else None)
                    if n:
                        out.append(n)
            else:
                out += _names(v, keys)
    elif isinstance(obj, list):
        for v in obj:
            out += _names(v, keys)
    return out


def lens_patents(people):
    """Return {person index: [patent titles]} for patents naming the person as inventor with Carleton as applicant."""
    if not os.environ.get("LENS_API_TOKEN"):
        log("LENS_API_TOKEN not set; skipping patents")
        return {}
    out = {}
    for i, p in enumerate(people):
        if not p.get("oa"):
            continue
        try:
            d = _lens({"bool": {"must": [{"match_phrase": {"inventor.name": p["n"]}}, {"match": {"applicant.name": "Carleton"}}]}}, size=20)
        except Exception as e:
            log("Lens lookup failed:", p["n"], e)
            continue
        titles = []
        for rec in d.get("data", []):
            t = rec.get("biblio", {}).get("invention_title") or rec.get("title")
            if isinstance(t, list):
                t = (t[0] or {}).get("text") if t else ""
            titles.append(t or rec.get("lens_id", "patent"))
        if titles:
            out[i] = titles
    log(f"patents: {sum(len(v) for v in out.values())} Carleton patents across {len(out)} researchers")
    return out


def lens_landscape(keywords, years=3):
    """Companies filing patents on a topic in recent years: a ready-made partner list."""
    if not os.environ.get("LENS_API_TOKEN"):
        return []
    since = (dt.date.today() - dt.timedelta(days=365 * years)).isoformat()
    q = " OR ".join(f'"{k}"' for k in keywords[:4])
    try:
        d = _lens({"bool": {"must": [{"query_string": {"query": q, "fields": ["title", "abstract", "claim"]}}],
                            "filter": [{"range": {"date_published": {"gte": since}}}]}}, size=100)
    except Exception as e:
        log("Lens landscape failed:", e)
        return []
    c = Counter(n for n in _names(d.get("data", [])) if not re.search(r"univ|college|institut|hospital|research council|government", n, re.I))
    return c.most_common(8)


# ------------------------------------------------------------------ CV signals (optional, for later)
def cv_signals(people):
    """config/cv_signals.csv with columns: name, type, title, year, funder, partner, notes.
    type is one of grant, thesis, patent, disclosure_public, award, other. Matched to the roster by name."""
    p = ROOT / "config/cv_signals.csv"
    if not p.exists():
        return {}
    idx = {norm(x["n"]): i for i, x in enumerate(people)}
    idx.update({norm(x["sort"].replace(",", " ")): i for i, x in enumerate(people)})
    out = defaultdict(list)
    with open(p, encoding="utf-8") as f:
        for r in csv.DictReader(f):
            i = idx.get(norm(r.get("name", "")))
            if i is not None:
                out[i].append({k: r.get(k, "") for k in ("type", "title", "year", "funder", "partner", "notes")})
    log(f"CV signals: {sum(len(v) for v in out.values())} items for {len(out)} people")
    return dict(out)


# ------------------------------------------------------------------ research lines
def build_lines(data, works, citers, nserc, patents, cvs, today=None):
    """Group each person's recent outputs by OpenAlex topic and score each line on momentum and industry pull."""
    today = today or dt.date.today()
    people = data["people"]
    since = dt.date(today.year - 3, 1, 1).isoformat()
    recent_cut = (today - dt.timedelta(days=730)).isoformat()
    grace_cut = (today - dt.timedelta(days=365)).isoformat()
    aid2p = {a: i for i, p in enumerate(people) for a in p["oa"]}
    lines = defaultdict(lambda: {"works": [], "companies": set(), "citers": set(), "industry": set(), "funders": Counter(), "lead": 0, "preprints": []})
    for wid, rec in works.items():
        w = rec["raw"]
        pub = w.get("publication_date") or ""
        if pub < since or not w.get("primary_topic") or len(w.get("authorships") or []) >= 100:
            continue
        sig = work_signals(w)
        tid = w["primary_topic"]["id"].split("/")[-1]
        for i in rec["f"]:
            L = lines[(i, tid)]
            L["topic"] = w["primary_topic"]["display_name"]
            L["subfield"] = (w["primary_topic"].get("subfield") or {}).get("display_name", "")
            L["works"].append({"id": wid, "t": re.sub(r"<[^>]+>", "", w.get("title") or ""), "d": pub, "v": ((w.get("primary_location") or {}).get("source") or {}).get("display_name") or ""})
            L["companies"] |= set(sig["companies"])
            L["citers"] |= citers.get(wid, set())
            L["industry"] |= set(sig["industry"])
            L["funders"].update(sig["funders"])
            if any(sig["roles"].get(a) for a in people[i]["oa"]):
                L["lead"] += 1
            if w.get("type") == "preprint" and pub >= grace_cut:
                gd = dt.date.fromisoformat(pub) + dt.timedelta(days=365)
                L["preprints"].append({"t": L["works"][-1]["t"], "d": pub, "grace_until": gd.isoformat()})
    out = []
    for (i, tid), L in lines.items():
        n = len(L["works"])
        if n < 2:
            continue
        rec = sum(1 for x in L["works"] if x["d"] >= recent_cut)
        prior = n - rec
        lead_share = L["lead"] / n
        p = people[i]
        np_ = nserc.get(i, [])
        pat = patents.get(i, [])
        cv = cvs.get(i, [])
        pull = (4 * len(L["companies"]) + 3 * min(len(L["citers"]), 6) + 3 * len(L["industry"]) + min(len({x["partner"] for x in np_}), 3)
                + (2 if pat else 0) + 2 * len(L["preprints"]) + min(sum(1 for c in cv if c["type"] in ("grant", "patent")), 3))
        base = min(rec, 3) + (1 if rec > prior else 0) + (2 if lead_share >= 0.5 else 0)
        score = pull + base if pull else base / 10  # lines with no sign of industry interest sink to the bottom
        out.append({"person": i, "name": p["n"], "units": p["u"], "rank": p["rk"], "roles": p["ro"], "topic": L["topic"], "subfield": L["subfield"],
                    "n": n, "recent": rec, "prior": prior, "lead_share": round(lead_share, 2),
                    "companies": sorted(L["companies"])[:8], "citers": sorted(L["citers"])[:8], "industry": sorted(L["industry"])[:6],
                    "funders": [f for f, _ in L["funders"].most_common(5)], "preprints": L["preprints"][:3],
                    "nserc_partners": sorted({x["partner"] for x in np_})[:6], "patents": pat[:4],
                    "cv": [c for c in cv if c["type"] in ("grant", "thesis", "patent", "award")][:5],
                    "titles": [x["t"] for x in sorted(L["works"], key=lambda x: x["d"], reverse=True)[:4]],
                    "pull": pull, "score": round(score, 1)})
    out.sort(key=lambda x: x["score"], reverse=True)
    return out


def compute(data, works, y0, oa_pages):
    """Run every source and write docs/signals.json. Returns the ranked lines."""
    people = data["people"]
    try:
        citers = company_citers(works, max(y0, dt.date.today().year - 3), oa_pages)
    except Exception as e:
        log("company citers skipped:", e)
        citers = {}
    try:
        nserc = nserc_partners(people)
    except Exception as e:
        log("NSERC skipped:", e)
        nserc = {}
    patents = lens_patents(people)
    cvs = cv_signals(people)
    lines = build_lines(data, works, citers, nserc, patents, cvs)
    sources = {"openalex": True, "company_citers": bool(citers), "nserc": bool(nserc), "patents": bool(os.environ.get("LENS_API_TOKEN")), "cv": bool(cvs)}
    (ROOT / "docs/signals.json").write_text(json.dumps({"gen": dt.date.today().isoformat(), "sources": sources, "lines": lines[:120]},
                                                       ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    log(f"signals.json: {len(lines)} research lines, top score {lines[0]['score'] if lines else 0}")
    return lines, citers
