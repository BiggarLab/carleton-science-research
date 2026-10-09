"""University-wide build: every Carleton output in OpenAlex, the people behind it, and research strengths.

Who counts as a researcher (each person carries the evidence in `ev`):
  roster   Faculty of Science roster (config/roster.csv), exact
  web      listed as faculty (professor, instructor, lecturer, research chair) on a carleton.ca department site
  nserc    holds an NSERC grant at Carleton in the last six years
  sshrc    holds a SSHRC grant at Carleton in the last six years
Grant holders not found on a department site are only kept when OpenAlex shows them publishing from Carleton
recently, and their unit is inferred from the affiliation text on their papers.

Writes docs/university/data.json and docs/university/signals.json. Caches in state/uni_*.json.
"""
import csv
import datetime as dt
import io
import json
import re
import sys
import time
import urllib.parse
import urllib.request
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import signals as SIG  # noqa: E402
from update import (CARLETON, DROP_TYPES, ROOT, SELECT, TYPES, load_roster, log, name_matches, norm, oa_get, oa_pages)  # noqa: E402

OUT = ROOT / "docs/university"
CFG = json.loads((ROOT / "config/university_units.json").read_text())
UA = {"User-Agent": "CarletonResearchDashboard/1.0 (Faculty of Science research office; contact via carleton.ca)"}
CORE = re.compile(r"profess|instructor|lecturer|research chair", re.I)
NOT_CORE = re.compile(r"performance instructor|adjunct|emerit|contract instructor|sessional|visiting|post-?doc|candidate|student|retired|honou?rary|teaching assistant|"
                      r"research associate|alumn|former|limited.term|limited term", re.I)
OTHER_UNI = re.compile(r"universit|college|polytechnique|institute of technology", re.I)
NO_GRANT = re.compile(r"scholarship|fellowship|doctoral|master|cgs|postdoc|post-doctoral|undergraduate|usra|bourse|award program for students", re.I)


def get(url, timeout=60):
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=timeout) as r:
        return r.read()


def cached(name, days, build):
    p = ROOT / f"state/uni_{name}.json"
    if p.exists():
        c = json.loads(p.read_text())
        if (dt.date.today() - dt.date.fromisoformat(c["fetched"])).days < days and c.get("items"):
            return c["items"]
    try:
        items = build()
    except Exception as e:
        log(f"{name}: failed ({e}); using the last saved copy if there is one")
        return json.loads(p.read_text())["items"] if p.exists() else []
    if items:
        p.write_text(json.dumps({"fetched": dt.date.today().isoformat(), "items": items}, ensure_ascii=False, indent=0))
    return items


def rank_of(title):
    t = title.lower()
    for k, v in (("assistant prof", "Assistant Professor"), ("associate prof", "Associate Professor"), ("assocaite prof", "Associate Professor"),
                 ("full prof", "Full Professor"), ("distinguished", "Full Professor"), ("research chair", "Research Chair"),
                 ("instructor", "Instructor"), ("lecturer", "Lecturer"), ("professor", "Professor")):
        if k in t:
            return v
    return "Faculty"


# ---------------------------------------------------------------- 1. department web listings
def directory():
    site_unit = {s: u for u in CFG["units"] for s in u.get("sites", [])}
    people = {}
    for site, u in site_unit.items():
        n_site = 0
        for page in range(1, 10):
            url = (f"https://carleton.ca/{site}/wp-json/wp/v2/cu_people?per_page=100&page={page}"
                   "&_fields=title,link,meta,acf.cu_people_job_title,acf.cu_people_orcid")
            try:
                rows = json.loads(get(url))
            except Exception as e:
                if page == 1:
                    log(f"directory: {site} not readable ({e})")
                break
            if not rows:
                break
            for r in rows:
                title = re.sub(r"<[^>]+>|&amp;", " ", (r.get("acf") or {}).get("cu_people_job_title") or "").strip()
                if not CORE.search(title) or NOT_CORE.search(title):
                    continue
                if OTHER_UNI.search(title) and "carleton" not in title.lower():
                    continue
                meta = r.get("meta") or {}
                first, last = (meta.get("cu_people_first_name") or "").strip(), (meta.get("cu_people_last_name") or "").strip()
                if not last:
                    nm = re.sub(r"<[^>]+>", "", (r.get("title") or {}).get("rendered", "")).strip().split()
                    if len(nm) < 2:
                        continue
                    first, last = nm[0], nm[-1]
                link_site = (r.get("link") or "").split("/")[3] if (r.get("link") or "").count("/") > 3 else site
                unit = site_unit.get(link_site, u)
                key = norm(f"{first} {last}")
                p = people.setdefault(key, {"first": first, "last": last, "name": f"{first} {last}", "title": title, "units": [],
                                            "orcid": ((r.get("acf") or {}).get("cu_people_orcid") or "").strip()})
                if unit["unit"] not in p["units"]:
                    p["units"].append(unit["unit"])
                n_site += 1
            if len(rows) < 100:
                break
            time.sleep(0.3)
        log(f"directory: {site}: {n_site} faculty listings")
    sec = {u["unit"] for u in CFG["units"] if u.get("secondary")}
    for p in people.values():
        home = [u for u in p["units"] if u not in sec]
        if home:
            p["units"] = home
    out = list(people.values())
    log(f"directory: {len(out)} faculty across {len(site_unit)} department sites")
    return out


# ---------------------------------------------------------------- 2. grant holders
def nserc_holders(years=6):
    """The awards database shows at most 10 pages of 25, so ask one fiscal year at a time."""
    y1 = dt.date.today().year
    rows = []
    for fy in range(y1 - years, y1 + 1):
        got, total = [], 0
        for pg in range(1, 11):
            url = SIG.NSERC_SEARCH.format(y0=fy, y1=fy, name="") + f"&page={pg}"
            try:
                r, total = SIG.parse_search(get(url).decode("utf-8", "replace"))
            except Exception as e:
                if got:
                    break
                raise
            seen = {(y["id"], y["name"]) for y in got}
            new = [x for x in r if (x["id"], x["name"]) not in seen]
            got += new
            time.sleep(1.0)
            if len(got) >= total or not new:
                break
        if total > 250:
            log(f"NSERC FY{fy}: {total} awards but only the first 250 can be listed")
        rows += got
    keep = [x for x in rows if not NO_GRANT.search(x["program"])]
    log(f"NSERC: {len(rows)} Carleton awards listed, {len(keep)} research grants")
    return keep


def sshrc_holders(years=6):
    csv.field_size_limit(10_000_000)
    out = []
    y1 = dt.date.today().year
    for fy in range(y1 - years, y1 + 1):
        data = None
        for url in (f"https://www.sshrc-crsh.gc.ca/opendata/SSHRC_FY{fy}_Expenditures.csv", f"https://www.sshrc-crsh.gc.ca/opendata/SSHRC_FY{fy}_Expenditures.csv.xls.csv"):
            try:
                data = get(url, timeout=120)
                break
            except Exception:
                continue
        if not data:
            continue
        text = None
        for enc in ("utf-8-sig", "cp1252", "latin-1"):
            try:
                text = data.decode(enc)
                break
            except UnicodeDecodeError:
                continue
        rd = csv.reader(io.StringIO(text))
        head = next(rd, [])
        H = [h.lower() for h in head]
        def col(*pats):
            for p in pats:
                for i, h in enumerate(H):
                    if re.search(p, h):
                        return i
            return None
        ci, cn, cp, ct, cf = col(r"institution|organi[sz]ation|établissement"), col(r"^name|applicant|nom", r"name"), col(r"program"), col(r"title|titre"), col(r"first|prénom")
        if ci is None or cn is None:
            log(f"SSHRC FY{fy}: columns not recognised: {head[:12]}")
            continue
        n = 0
        for row in rd:
            if len(row) <= max(ci, cn) or "carleton" not in row[ci].lower():
                continue
            prog = row[cp] if cp is not None and cp < len(row) else ""
            if NO_GRANT.search(prog):
                continue
            name = row[cn].strip()
            if cf is not None and cf < len(row) and row[cf].strip() and "," not in name:
                name = f"{name}, {row[cf].strip()}"
            out.append({"name": name, "program": prog, "title": row[ct] if ct is not None and ct < len(row) else "", "year": str(fy)})
            n += 1
        log(f"SSHRC FY{fy}: {n} Carleton research grants (columns: {', '.join(head[:8])})")
    return out


# ---------------------------------------------------------------- 3. all Carleton outputs
def unit_matchers():
    return [(re.compile(u["match"], re.I), u["unit"]) for u in CFG["units"] if u.get("match")]


def infer_unit(raws, M):
    for s in raws:
        if "carleton" not in s.lower():
            continue
        for rx, unit in M:
            if rx.search(s):
                return unit
    return None


def fetch_works(y0):
    M = unit_matchers()
    works, authors = {}, {}
    n = 0
    for w in oa_pages("works", {"filter": f"institutions.id:{CARLETON.split('/')[-1]},from_publication_date:{y0}-01-01", "select": SELECT}):
        n += 1
        if w.get("type") in DROP_TYPES or not w.get("title"):
            continue
        au = w.get("authorships") or []
        na = len(au)
        wid = w["id"].split("/")[-1]
        car, lead_aids = [], set()
        for k, a in enumerate(au):
            insts = [x.get("id") for x in a.get("institutions") or []]
            raw = a.get("raw_affiliation_strings") or []
            if CARLETON not in insts and not any("carleton" in s.lower() for s in raw):
                continue
            au_ = a.get("author") or {}
            aid = (au_.get("id") or "").split("/")[-1]
            if not aid:
                continue
            unit = infer_unit(raw, M)
            car.append((aid, unit))
            if k == 0 or k == na - 1 or a.get("is_corresponding"):
                lead_aids.add(aid)
            A = authors.setdefault(aid, {"name": au_.get("display_name") or "", "orcid": (au_.get("orcid") or "").split("/")[-1], "n": 0, "last": 0, "units": Counter()})
            A["n"] += 1
            A["last"] = max(A["last"], w.get("publication_year") or 0)
            if unit:
                A["units"][unit] += 1
        if na >= 100:  # keep memory down: big collaborations only need the Carleton authorships
            keep = {c[0] for c in car}
            w["authorships"] = [a for a in au if ((a.get("author") or {}).get("id") or "").split("/")[-1] in keep]
        w["_na"] = na
        works[wid] = {"raw": w, "car": car, "lead": lead_aids}
        if n % 2000 == 0:
            log(f"works: {n} read")
    log(f"works: {len(works)} Carleton outputs since {y0}, {len(authors)} Carleton-affiliated author profiles")
    return works, authors


# ---------------------------------------------------------------- 4. people
def build_people(authors, dirx, grants, today):
    unit_fac = {u["unit"]: u["faculty"] for u in CFG["units"]}
    by_last = defaultdict(list)
    by_orcid = {}
    for aid, A in authors.items():
        t = norm(A["name"]).split()
        if t:
            by_last[t[-1]].append(aid)
        if A["orcid"]:
            by_orcid[A["orcid"]] = aid
    taken = set()

    def find(first, last, orcid=""):
        if orcid and orcid.split("/")[-1] in by_orcid:
            return [by_orcid[orcid.split("/")[-1]]]
        lt = norm(last).split()
        if not lt:
            return []
        return [a for a in by_last.get(lt[-1], []) if name_matches(authors[a]["name"], last, first)]

    people = []
    # Science roster, exact
    for r in load_roster():
        ids = r["openalex_ids"].split()
        taken |= set(ids)
        people.append({"n": r["name"], "sort": r["sort_name"], "u": [u.strip() for u in r["units"].split(";") if u.strip()], "rk": r["rank"],
                       "st": r["stream"], "ro": [x.strip() for x in r["roles"].split(";") if x.strip()], "oa": ids, "ev": ["roster"],
                       "orc": f"https://orcid.org/{r['orcid']}" if r.get("orcid") else None})
    sci_names = {norm(p["n"]) for p in people}
    # department web listings
    unmatched = 0
    for d in dirx:
        if norm(d["name"]) in sci_names or all(unit_fac.get(u) == "Science" for u in d["units"]):
            continue
        ids = [a for a in find(d["first"], d["last"], d.get("orcid")) if a not in taken]
        if not ids:
            unmatched += 1
            continue
        taken |= set(ids)
        people.append({"n": d["name"], "sort": f"{d['last']}, {d['first']}", "u": d["units"], "rk": rank_of(d["title"]), "st": "", "ro": [],
                       "oa": ids, "ev": ["web"], "title": d["title"][:120], "orc": f"https://orcid.org/{d['orcid']}" if d.get("orcid") else None})
    log(f"people: {len(people)} so far; {unmatched} web-listed faculty had no Carleton outputs in OpenAlex for these years")
    # grant holders
    a2i = {a: i for i, p in enumerate(people) for a in p["oa"]}
    added = 0
    for src, rows in grants.items():
        for g in rows:
            last, _, first = g["name"].partition(",")
            first = first.strip().split(" ")[0] if first.strip() else ""
            if not last or not first:
                continue
            ids = find(first, last.strip())
            hit = next((a2i[a] for a in ids if a in a2i), None)
            if hit is not None:
                if src not in people[hit]["ev"]:
                    people[hit]["ev"].append(src)
                people[hit].setdefault("_g", []).append(dict(g, src=src.upper()))
                continue
            ids = [a for a in ids if a not in taken and authors[a]["n"] >= 3 and authors[a]["last"] >= today.year - 2]
            if not ids:
                continue
            units = Counter()
            for a in ids:
                units.update(authors[a]["units"])
            if not units:
                continue
            unit = units.most_common(1)[0][0]
            taken |= set(ids)
            nm = authors[ids[0]]["name"]
            people.append({"n": nm, "sort": f"{last.strip()}, {first}", "u": [unit], "rk": "Faculty (grant holder)", "st": "", "ro": [], "oa": ids,
                           "ev": [src], "orc": None, "_g": [dict(g, src=src.upper())]})
            for a in ids:
                a2i[a] = len(people) - 1
            added += 1
    log(f"people: {added} more found through NSERC/SSHRC grants; {len(people)} in total")
    for p in people:
        p["fac"] = sorted({unit_fac.get(u, "Other") for u in p["u"]})
    return people


def lifetime(people):
    ids = [(i, a) for i, p in enumerate(people) for a in p["oa"]]
    for p in people:
        p.update({"h": 0, "i10": 0, "lw": 0, "lc": 0})
    for k in range(0, len(ids), 50):
        chunk = ids[k:k + 50]
        who = {a: i for i, a in chunk}
        try:
            d = oa_get("authors", {"filter": "ids.openalex:" + "|".join(a for _, a in chunk), "per_page": 50, "select": "id,works_count,cited_by_count,summary_stats"})
        except Exception as e:
            log("author batch failed:", e)
            continue
        for a in d.get("results", []):
            i = who.get(a["id"].split("/")[-1])
            if i is None:
                continue
            ss = a.get("summary_stats") or {}
            p = people[i]
            p["lw"] += a.get("works_count") or 0
            p["lc"] += a.get("cited_by_count") or 0
            p["h"] = max(p["h"], ss.get("h_index") or 0)
            p["i10"] = max(p["i10"], ss.get("i10_index") or 0)


# ---------------------------------------------------------------- 5. world baseline for specialisation
def world_counts(topic_ids, y0, y1):
    total = oa_get("works", {"filter": f"publication_year:{y0}-{y1}", "per_page": 1})["meta"]["count"]
    out = {}
    tids = sorted(topic_ids)
    for k in range(0, len(tids), 50):
        chunk = tids[k:k + 50]
        try:
            d = oa_get("works", {"filter": f"publication_year:{y0}-{y1},primary_topic.id:{'|'.join(chunk)}", "group_by": "primary_topic.id"})
        except Exception as e:
            log("world baseline batch failed:", e)
            continue
        for g in d.get("group_by", []):
            out[g["key"].split("/")[-1]] = g["count"]
    log(f"world baseline: {len(out)} topics, {total:,} works worldwide {y0}-{y1}")
    return total, out


# ---------------------------------------------------------------- assemble
def main():
    today = dt.date.today()
    y0 = today.year - 5
    OUT.mkdir(parents=True, exist_ok=True)
    dirx = cached("directory", 7, directory)
    grants = {"nserc": cached("nserc", 28, nserc_holders), "sshrc": cached("sshrc", 28, sshrc_holders)}
    works, authors = fetch_works(y0)
    people = build_people(authors, dirx, grants, today)
    lifetime(people)
    aid2p = defaultdict(list)
    for i, p in enumerate(people):
        for a in p["oa"]:
            aid2p[a].append(i)

    units = [u["unit"] for u in CFG["units"]]
    uix = {u: k for k, u in enumerate(units)}
    topics, venues, insts = {}, {}, {}

    def idx(d, k, v=None):
        if k not in d:
            d[k] = (len(d), v)
        return d[k][0]

    rows = []
    sig_works = {}
    for wid, rec in works.items():
        w = rec["raw"]
        f = sorted({i for aid, _ in rec["car"] for i in aid2p.get(aid, [])})
        extra = sorted({uix[u] for aid, u in rec["car"] if u and not aid2p.get(aid) and u in uix})
        lead = sorted({i for aid in rec["lead"] for i in aid2p.get(aid, [])})
        na = w["_na"]
        countries, inst_ix = set(), []
        if na <= 60:
            for a in w.get("authorships") or []:
                for x in a.get("institutions") or []:
                    if x.get("country_code"):
                        countries.add(x["country_code"])
                    if x.get("id") and x["id"] != CARLETON:
                        inst_ix.append(idx(insts, x["id"].split("/")[-1], [x.get("display_name"), x.get("country_code") or "", x.get("type") or ""]))
        pt = w.get("primary_topic")
        tp = idx(topics, pt["id"].split("/")[-1], [pt["display_name"], (pt.get("subfield") or {}).get("display_name"), (pt.get("field") or {}).get("display_name")]) if pt else -1
        src = ((w.get("primary_location") or {}).get("source") or {}).get("display_name") or ""
        v = idx(venues, src) if src else -1
        fw = w.get("fwci")
        rows.append([wid[1:], w["title"].replace("�", ""), w.get("publication_date") or f"{w.get('publication_year')}-01-01",
                     TYPES.index(w["type"]) if w.get("type") in TYPES else 0, v, (w.get("doi") or "").replace("https://doi.org/", ""),
                     w.get("cited_by_count") or 0, None if fw is None else round(fw, 2), tp, [k["display_name"] for k in (w.get("keywords") or [])[:3]],
                     na, f, sorted(countries), sorted(set(inst_ix)), 1 if (w.get("open_access") or {}).get("is_oa") else 0, extra, lead])
        if f and na < 100:
            sig_works[wid] = {"raw": w, "f": f}
    rows.sort(key=lambda r: r[2], reverse=True)
    inv = lambda d: [v for _, v in sorted(d.values(), key=lambda x: x[0])]
    tlist = sorted(topics.items(), key=lambda kv: kv[1][0])
    wtot, wc = world_counts([k for k, _ in tlist], y0, today.year)
    data = {"gen": today.isoformat(), "scope": "university", "people": [{k: v for k, v in p.items() if k != "_g"} for p in people], "works": rows, "topics": inv(topics),
            "venues": [k for k, _ in sorted(venues.items(), key=lambda kv: kv[1][0])], "insts": inv(insts), "types": TYPES,
            "units": [[u["unit"], u["faculty"]] for u in CFG["units"]], "faculties": [f["name"] for f in CFG["faculties"]],
            "world": {"total": wtot, "topics": [wc.get(k, 0) for k, _ in tlist]},
            "evidence": {"web": sum("web" in p["ev"] for p in people), "roster": sum("roster" in p["ev"] for p in people),
                         "nserc": sum("nserc" in p["ev"] for p in people), "sshrc": sum("sshrc" in p["ev"] for p in people),
                         "sources": {"web": bool(dirx), "nserc": bool(grants["nserc"]), "sshrc": bool(grants["sshrc"])}}}
    (OUT / "data.json").write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    log(f"university data.json: {len(people)} people, {len(rows)} outputs, {(OUT / 'data.json').stat().st_size / 1e6:.1f} MB")

    # partnership signals, university-wide (grants come from the institution-wide lists, without detail pages)
    try:
        citers = SIG.company_citers(sig_works, today.year - 3, oa_pages)
    except Exception as e:
        log("company citers skipped:", e)
        citers = {}
    nserc = {}
    for i, p in enumerate(people):
        gs = p.get("_g") or []
        if gs:
            nserc[i] = {"partners": [], "grants": [{"title": g["title"], "program": f"{g['src']} {g['program']}", "year": g["year"], "area": "", "partners": [], "summary": ""}
                                                   for g in sorted(gs, key=lambda g: g["year"], reverse=True)[:4]],
                        "timing": SIG.dg_timing([g for g in gs if g["src"] == "NSERC"])}
    patents = SIG.carleton_patents(people, today.year - 10)
    lines = SIG.build_lines(data, sig_works, citers, nserc, patents, {})
    (OUT / "signals.json").write_text(json.dumps({"gen": today.isoformat(), "sources": {"openalex": True, "company_citers": bool(citers), "nserc": bool(grants["nserc"]),
                                                  "patents": bool(patents), "cv": False}, "lines": lines[:300],
                                                  "nserc": {str(i): v for i, v in nserc.items()}}, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    log(f"university signals.json: {len(lines)} research lines")


if __name__ == "__main__":
    main()
