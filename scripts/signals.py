"""Partnership and IP signals for the Carleton Faculty of Science dashboard.

Turns raw publication data into research lines (one researcher working on one topic over
several papers) and scores each line on evidence that industry already cares:

  company co-authors     companies on the author list of our papers           (OpenAlex)
  company citers         companies whose own papers cite our papers           (OpenAlex)
  industry funding       Mitacs, NSERC Alliance/CRD/Engage, OCI, company funders (OpenAlex funders and awards)
  NSERC grants           partner organizations, co-researchers and plain-language summaries of planned work (NSERC awards database)
  patents                Carleton patents naming the researcher (USPTO PatentSearch and/or EPO OPS, free keys)
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
import urllib.parse
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


# ------------------------------------------------------------------ NSERC awards database
# Public search at nserc-crsng.canada.ca/en/awards-database (robots.txt allows it). One search per person,
# detail pages only for partner programs and the latest Discovery grant. Cached in state/nserc_cache.json,
# refreshed per person every 28 days, with a pause between requests.
import html as _html
import time as _time

NSERC_HOST = "https://nserc-crsng.canada.ca"
NSERC_SEARCH = (NSERC_HOST + "/en/awards-database?fiscal_year_from={y0}&fiscal_year_to={y1}&competition_year_from=0&competition_year_to=0"
                "&keywords=&institution_type=0&institution_name_1_6%5B23%5D=23&area_code=&subject_code=&department=&award_amount_min="
                "&award_amount_max=&report_type=0&op=Search&person_name={name}")
PARTNER_PROGRAMS = re.compile(r"alliance|collaborative research and development|engage|idea to innovation|applied research|strategic|"
                              r"industrial research chair|partnership|i2i|create|college and community|mission", re.I)
UA = {"User-Agent": "CarletonScienceResearchDashboard/1.0 (Carleton University Faculty of Science research office)"}


def _get_html(url):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.read().decode("utf-8", "replace")


def _strip(h):
    return re.sub(r"\s+", " ", _html.unescape(re.sub(r"<[^>]+>", " ", h or ""))).strip()


def parse_search(page):
    rows = []
    for tr in re.findall(r"<tr[^>]*>(.*?)</tr>", page, re.S):
        tds = re.findall(r"<td[^>]*>(.*?)</td>", tr, re.S)
        if len(tds) < 5:
            continue
        m = re.search(r'href="/en/awards-database/(\d+)"', tr)
        amt = re.sub(r"[^\d.]", "", _strip(tds[2])) or "0"
        rows.append({"name": _strip(tds[0]), "title": _strip(tds[1]), "amount": float(amt), "year": _strip(tds[3]), "program": _strip(tds[4]), "id": m.group(1) if m else None})
    m = re.search(r"Showing \d+ to \d+ of ([\d,]+)", page)
    total = int(m.group(1).replace(",", "")) if m else len(rows)
    return rows, total


def parse_detail(page):
    d = {}
    for lab, span, ul in re.findall(r'award-db-item-label">([^<]+)</span>\s*(?:<span class="award-db-item-value">(.*?)</span>|<ul class="award-db-item-value">(.*?)</ul>)', page, re.S):
        lab = lab.strip().lower()
        d[lab] = [_strip(x) for x in re.findall(r"<li>(.*?)</li>", ul, re.S)] if ul else _strip(span)
    m = re.search(r"Award summary\s*</gcds-heading>(.*?)</section>", page, re.S)
    summ = _strip(m.group(1)) if m else ""
    if summ.lower().startswith("no summary"):
        summ = ""
    partners = d.get("partners") if isinstance(d.get("partners"), list) else []
    cores = d.get("co-researchers") if isinstance(d.get("co-researchers"), list) else []
    return {"app_id": d.get("application id", ""), "program": d.get("program", ""), "area": d.get("area of application", ""), "subject": d.get("research subject", ""),
            "partners": partners, "coresearchers": cores, "summary": summ[:900], "department": d.get("department", "")}


def nserc_awards(people, years=6, refresh_days=28, pause=1.0):
    """Return {person index: {"partners": [...], "grants": [...]}} from the NSERC awards database."""
    cache_p = ROOT / "state/nserc_cache.json"
    cache = json.loads(cache_p.read_text()) if cache_p.exists() else {"people": {}, "details": {}}
    today = dt.date.today()
    y1 = today.year
    y0 = y1 - years
    fetched = 0
    failures = 0
    for i, p in enumerate(people):
        key = p["sort"]
        ent = cache["people"].get(key)
        if ent and (today - dt.date.fromisoformat(ent["fetched"])).days < refresh_days:
            continue
        last, _, first = key.partition(", ")
        try:
            rows, total = [], None
            for pg in range(1, 9):  # NSERC pages are numbered from 1
                url = NSERC_SEARCH.format(y0=y0, y1=y1, name=urllib.parse.quote(last)) + f"&page={pg}"
                r, total = parse_search(_get_html(url))
                ids = {x["id"] for x in rows}
                r = [x for x in r if x["id"] not in ids]
                rows += r
                fetched += 1
                _time.sleep(pause)
                if len(rows) >= total or not r:
                    break
        except Exception as e:
            failures += 1
            log(f"NSERC search failed for {p['n']}: {e}")
            if failures >= 5:
                log("NSERC awards database not reachable; stopping NSERC lookups this run")
                break
            continue
        f3 = norm(first)[:3]
        mine = [r for r in rows if norm(r["name"].split(",")[0]).replace(" ", "") == norm(last).replace(" ", "")
                and (not f3 or norm(r["name"].partition(",")[2]).startswith(f3))]
        cache["people"][key] = {"fetched": today.isoformat(), "awards": mine}
    for key, ent in cache["people"].items():
        aw = sorted(ent["awards"], key=lambda r: r["year"], reverse=True)
        want = [r for r in aw if PARTNER_PROGRAMS.search(r["program"])]
        disc = next((r for r in aw if "discovery grants program - individual" in r["program"].lower()), None)
        if disc:
            want.append(disc)
        seen_titles = set()
        for r in want:
            t = (r["title"], r["program"])
            if t in seen_titles or not r.get("id") or r["id"] in cache["details"]:
                seen_titles.add(t)
                continue
            seen_titles.add(t)
            try:
                cache["details"][r["id"]] = parse_detail(_get_html(f"{NSERC_HOST}/en/awards-database/{r['id']}"))
                fetched += 1
                _time.sleep(pause)
            except Exception as e:
                log(f"NSERC detail failed {r['id']}: {e}")
    cache_p.write_text(json.dumps(cache, ensure_ascii=False, indent=0))
    out = {}
    idx = {p["sort"]: i for i, p in enumerate(people)}
    for key, ent in cache["people"].items():
        i = idx.get(key)
        if i is None:
            continue
        grants, partners, seen = [], [], set()
        for r in sorted(ent["awards"], key=lambda r: r["year"], reverse=True):
            t = (r["title"], r["program"])
            if t in seen:
                continue
            seen.add(t)
            det = cache["details"].get(r.get("id") or "", {})
            total = sum(x["amount"] for x in ent["awards"] if (x["title"], x["program"]) == t)
            g = {"title": r["title"], "program": r["program"], "year": r["year"], "total": round(total), "area": det.get("area", ""),
                 "partners": det.get("partners", []), "summary": det.get("summary", "")[:600]}
            grants.append(g)
            for prt in det.get("partners", []):
                partners.append({"partner": prt, "program": r["program"], "title": r["title"], "year": r["year"]})
        if grants:
            out[i] = {"partners": partners, "grants": grants[:6]}
    log(f"NSERC: {fetched} page requests this run; {sum(1 for v in out.values() if v['partners'])} researchers with partner organizations, "
        f"{sum(len(v['partners']) for v in out.values())} partner links")
    return out


# ------------------------------------------------------------------ patents (optional, free sources)
# USPTO PatentSearch (PatentsView): free key from account.uspto.gov/api-manager, secret PATENTSVIEW_API_KEY. US patents.
# EPO Open Patent Services: free registration at developers.epo.org (4 GB/week), secrets EPO_OPS_KEY and EPO_OPS_SECRET. Worldwide incl. CA and PCT.
NON_COMPANY = re.compile(r"univ|college|institut|hospital|research council|government|ministry|foundation|school|academy|\bcnrs\b|\binserm\b", re.I)


def _post_json(url, body, headers, timeout=60):
    req = urllib.request.Request(url, data=json.dumps(body).encode(), headers={"Content-Type": "application/json", **headers})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


def _pv(q, f, size=100):
    return _post_json("https://search.patentsview.org/api/v1/patent/", {"q": q, "f": f, "o": {"size": size}, "s": [{"patent_date": "desc"}]},
                      {"X-Api-Key": os.environ["PATENTSVIEW_API_KEY"]})


_ops_token = {}


def _ops(path, params):
    import base64
    import urllib.parse
    if "t" not in _ops_token:
        cred = base64.b64encode(f"{os.environ['EPO_OPS_KEY']}:{os.environ['EPO_OPS_SECRET']}".encode()).decode()
        req = urllib.request.Request("https://ops.epo.org/3.2/auth/accesstoken", data=b"grant_type=client_credentials",
                                     headers={"Authorization": f"Basic {cred}", "Content-Type": "application/x-www-form-urlencoded"})
        with urllib.request.urlopen(req, timeout=60) as r:
            _ops_token["t"] = json.loads(r.read())["access_token"]
    url = f"https://ops.epo.org/3.2/rest-services/{path}?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {_ops_token['t']}", "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read())


def _walk(obj, key):
    """Yield every value stored under `key` anywhere in a nested JSON structure."""
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k == key:
                yield v
            yield from _walk(v, key)
    elif isinstance(obj, list):
        for v in obj:
            yield from _walk(v, key)


def _texts(v):
    if isinstance(v, dict):
        if "$" in v:
            return [v["$"]]
        return [t for x in v.values() for t in _texts(x)]
    if isinstance(v, list):
        return [t for x in v for t in _texts(x)]
    return [v] if isinstance(v, str) else []


def _match_inventors(names, people):
    """names: list of (first, last) or 'LAST FIRST' strings -> roster indices."""
    by_last = defaultdict(list)
    for i, p in enumerate(people):
        last, _, first = p["sort"].partition(", ")
        by_last[norm(last).replace(" ", "")].append((i, norm(first)[:3]))
    hits = set()
    for n in names:
        if isinstance(n, tuple):
            first, last = norm(n[0]), norm(n[1])
        else:
            t = norm(str(n).replace(",", " ")).split()
            if len(t) < 2:
                continue
            last, first = t[0], " ".join(t[1:])
        for i, f3 in by_last.get(last.replace(" ", ""), []):
            if not f3 or first.startswith(f3) or (len(first.split()[0] if first else '') == 1 and first[:1] == f3[:1]):
                hits.add(i)
    return hits


def carleton_patents(people, since_year):
    """Return {person index: [patent titles]} for patents assigned to Carleton that name the person as inventor."""
    out = defaultdict(list)
    used = []
    if os.environ.get("PATENTSVIEW_API_KEY"):
        try:
            d = _pv({"_and": [{"_text_phrase": {"assignees.assignee_organization": "Carleton University"}}, {"_gte": {"patent_date": f"{since_year}-01-01"}}]},
                    ["patent_id", "patent_title", "patent_date", "inventors.inventor_name_first", "inventors.inventor_name_last"], size=500)
            for pt in d.get("patents", []):
                inv = [(x.get("inventor_name_first", ""), x.get("inventor_name_last", "")) for x in pt.get("inventors") or []]
                for i in _match_inventors(inv, people):
                    out[i].append(f"{pt.get('patent_title', '')} (US {pt.get('patent_id', '')}, {pt.get('patent_date', '')[:4]})")
            used.append(f"USPTO: {len(d.get('patents', []))} Carleton patents")
        except Exception as e:
            log("USPTO PatentSearch failed:", e)
    if os.environ.get("EPO_OPS_KEY") and os.environ.get("EPO_OPS_SECRET"):
        try:
            n = 0
            for start in range(1, 401, 100):
                d = _ops("published-data/search/biblio", {"q": f'pa="Carleton University" and pd>={since_year}', "Range": f"{start}-{start + 99}"})
                docs = list(_walk(d, "exchange-document"))
                docs = [x for v in docs for x in (v if isinstance(v, list) else [v])]
                for doc in docs:
                    title = next(iter(_texts(next(iter(_walk(doc, "invention-title")), ""))), "")
                    inv = [t for v in _walk(doc, "inventor-name") for t in _texts(v)]
                    num = next(iter(_texts(next(iter(_walk(doc, "doc-number")), ""))), "")
                    cc = doc.get("@country", "") if isinstance(doc, dict) else ""
                    for i in _match_inventors(inv, people):
                        label = f"{title} ({cc}{num})"
                        if label not in out[i]:
                            out[i].append(label)
                n += len(docs)
                if len(docs) < 100:
                    break
            used.append(f"EPO: {n} Carleton documents")
        except Exception as e:
            log("EPO OPS failed:", e)
    if not used:
        log("No patent keys set (PATENTSVIEW_API_KEY or EPO_OPS_KEY/SECRET); skipping patents")
    else:
        log("patents:", "; ".join(used), f"-> {sum(len(v) for v in out.values())} matched to {len(out)} researchers")
    return dict(out)


def patent_landscape(keywords, years=3):
    """Companies filing patents on a topic recently: a ready-made partner list."""
    since = dt.date.today().year - years
    words = [w for w in re.findall(r"[A-Za-z][A-Za-z-]{3,}", " ".join(keywords)) if w.lower() not in {"studies", "analysis", "research", "applications", "advanced", "techniques", "management", "systems"}][:4]
    if not words:
        return []
    c = Counter()
    if os.environ.get("PATENTSVIEW_API_KEY"):
        try:
            d = _pv({"_and": [{"_text_all": {"patent_abstract": " ".join(words[:3])}}, {"_gte": {"patent_date": f"{since}-01-01"}}]},
                    ["assignees.assignee_organization"], size=200)
            for pt in d.get("patents", []):
                for a in pt.get("assignees") or []:
                    o = a.get("assignee_organization")
                    if o and not NON_COMPANY.search(o):
                        c[o] += 1
        except Exception as e:
            log("USPTO landscape failed:", e)
    if os.environ.get("EPO_OPS_KEY") and os.environ.get("EPO_OPS_SECRET"):
        try:
            q = " and ".join(f'ta="{w}"' for w in words[:3]) + f" and pd>={since}"
            d = _ops("published-data/search/biblio", {"q": q, "Range": "1-100"})
            for v in _walk(d, "applicant-name"):
                for o in _texts(v):
                    if o and not NON_COMPANY.search(o):
                        c[o.strip().title()] += 1
        except Exception as e:
            log("EPO landscape failed:", e)
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
        np_ = (nserc.get(i) or {}).get("partners", [])
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
                    "current_grant": next(({"title": g["title"], "program": g["program"], "year": g["year"], "area": g["area"]} for g in (nserc.get(i) or {}).get("grants", [])), None),
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
        nserc = nserc_awards(people)
    except Exception as e:
        log("NSERC skipped:", e)
        nserc = {}
    patents = carleton_patents(people, dt.date.today().year - 10)
    cvs = cv_signals(people)
    lines = build_lines(data, works, citers, nserc, patents, cvs)
    sources = {"openalex": True, "company_citers": bool(citers), "nserc": bool(nserc), "patents": bool(os.environ.get("PATENTSVIEW_API_KEY") or os.environ.get("EPO_OPS_KEY")), "cv": bool(cvs)}
    nserc_out = {str(i): {"partners": sorted({x["partner"] for x in v["partners"]})[:10],
                          "grants": [{k: g[k] for k in ("title", "program", "year", "total", "area", "partners", "summary")} for g in v["grants"][:4]]}
                 for i, v in nserc.items()}
    (ROOT / "docs/signals.json").write_text(json.dumps({"gen": dt.date.today().isoformat(), "sources": sources, "lines": lines[:120], "nserc": nserc_out},
                                                       ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    log(f"signals.json: {len(lines)} research lines, top score {lines[0]['score'] if lines else 0}")
    return lines, citers
