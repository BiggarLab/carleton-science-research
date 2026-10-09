#!/usr/bin/env python3
"""Weekly update for the Carleton Faculty of Science research dashboard and digest.

Runs every Monday from GitHub Actions. It:
  1. matches any new names in config/roster.csv to OpenAlex author profiles,
  2. pulls every Faculty member's outputs since Jan 1 five years ago and rebuilds docs/data.json,
  3. finds outputs not covered by an earlier digest,
  4. asks Claude for plain-language summaries and an innovation/partnering screen,
  5. writes docs/digest/index.html plus an archived copy, and emails the issue.

Environment variables (set as GitHub repository secrets):
  OPENALEX_API_KEY   free key from openalex.org/settings/api
  ANTHROPIC_API_KEY  Claude API key from platform.claude.com
  RESEND_API_KEY     optional, for email via resend.com
  DIGEST_TO          address that receives the weekly email
  SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASS  optional alternative to Resend
Flags: --no-email, --no-ai, --force (rebuild this week's issue even if already sent), --week-end YYYY-MM-DD
"""
import argparse
import csv
import datetime as dt
import json
import os
import re
import smtplib
import ssl
import sys
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from render_digest import render_brief_email, render_brief_web, render_email, render_text, render_web, week_label  # noqa: E402
import signals as SIG  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
CFG = json.loads((ROOT / "config/settings.json").read_text())
CARLETON = "https://openalex.org/I67031392"
OA = "https://api.openalex.org"
DROP_TYPES = {"dataset", "erratum", "supplementary-materials", "paratext", "peer-review", "retraction", "other", "reference-entry", "software"}
TYPES = ["article", "review", "preprint", "conference-paper", "book-chapter", "book", "editorial", "letter", "report", "conference-abstract", "data-paper", "book-review"]
SELECT = "id,doi,title,publication_year,publication_date,created_date,type,primary_location,cited_by_count,fwci,primary_topic,keywords,authorships,open_access,funders,awards"


def log(*a):
    print(*a, flush=True)


# ---------------------------------------------------------------- OpenAlex
def oa_get(path, params=None, key=os.environ.get("OPENALEX_API_KEY", "")):
    params = dict(params or {})
    if key:
        params["api_key"] = key
    url = f"{OA}/{path}?{urllib.parse.urlencode(params)}"
    for attempt in range(6):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "carleton-science-digest"}), timeout=60) as r:
                return json.loads(r.read())
        except urllib.error.HTTPError as e:
            if e.code == 429 or e.code >= 500:
                time.sleep(2 + attempt * 3)
                continue
            raise
        except urllib.error.URLError:
            time.sleep(2 + attempt * 3)
    raise RuntimeError(f"OpenAlex request kept failing: {path}")


def oa_pages(path, params):
    cursor = "*"
    while cursor:
        d = oa_get(path, {**params, "per_page": 100, "cursor": cursor})
        yield from d.get("results", [])
        cursor = d.get("meta", {}).get("next_cursor")


# ---------------------------------------------------------------- roster
def norm(s):
    return re.sub(r"\s+", " ", re.sub(r"[^a-z ]", " ", unicodedata.normalize("NFD", s).encode("ascii", "ignore").decode().lower())).strip()


NICK = {"sue": ["susan", "suzanne"], "tom": ["thomas"], "dave": ["david"], "joe": ["joseph"], "tim": ["timothy"], "alex": ["alexander", "alexandre", "alexandra"],
        "kim": ["kimberly", "kimberley"], "jeff": ["jeffrey", "jeffery"], "jenny": ["jennifer"], "steven": ["stephen", "steve"], "wilf": ["wilfred"],
        "fred": ["frederick"], "chris": ["christopher"], "dan": ["daniel"], "pat": ["patrick"], "mike": ["michael"], "rob": ["robert"], "bob": ["robert"]}


def first_ok(f, F):
    if len(f) == 1:
        return f == F[0]
    if f.startswith(F) or F.startswith(f) or any(f.startswith(a) for a in NICK.get(F, [])):
        return True
    return any(F in v and f == k for k, v in NICK.items())


def name_matches(display, last, first):
    dn = norm(display)
    if norm(last).replace(" ", "") not in dn.replace(" ", ""):
        return False
    toks, F = dn.split(), (norm(first).split() or [""])[0]
    return bool(toks) and bool(F) and first_ok(toks[0], F)


def load_roster():
    with open(ROOT / "config/roster.csv", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def save_roster(rows):
    with open(ROOT / "config/roster.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)


def match_new_people(rows):
    """Fill openalex_ids for roster rows that have none. Flags them for a human check."""
    changed = False
    for r in rows:
        if r["openalex_ids"].strip() or "no match" in r.get("notes", ""):
            continue
        last, _, first = r["sort_name"].partition(", ")
        if r.get("orcid"):
            try:
                a = oa_get(f"authors/orcid:{r['orcid']}", {"select": "id,display_name"})
                r["openalex_ids"] = a["id"].split("/")[-1]
                r["notes"] = f"matched by ORCID {dt.date.today()}"
                changed = True
                continue
            except Exception:
                pass
        res = oa_get("authors", {"search": f"{first} {last}", "filter": f"affiliations.institution.id:{CARLETON.split('/')[-1]}",
                                 "per_page": 25, "select": "id,display_name,works_count"}).get("results", [])
        hits = [a for a in res if name_matches(a["display_name"], last, first)]
        if hits:
            r["openalex_ids"] = " ".join(a["id"].split("/")[-1] for a in hits)
            r["notes"] = f"auto-matched {dt.date.today()}, please check: " + "; ".join(f"{a['display_name']} ({a['works_count']})" for a in hits)
        else:
            r["notes"] = f"no match {dt.date.today()}"
        changed = True
        log("roster:", r["name"], "->", r["openalex_ids"] or "no match")
    return changed


# ---------------------------------------------------------------- build dashboard data
def build_data(rows, y0):
    people = []
    for r in rows:
        people.append({"n": r["name"], "sort": r["sort_name"], "u": [u.strip() for u in r["units"].split(";") if u.strip()], "rk": r["rank"], "st": r["stream"],
                       "ro": [x.strip() for x in r["roles"].split(";") if x.strip()], "oa": r["openalex_ids"].split(), "h": 0, "i10": 0, "lw": 0, "lc": 0,
                       "orc": f"https://orcid.org/{r['orcid']}" if r.get("orcid") else None})
    # lifetime metrics (single-entity lookups are free on OpenAlex)
    for p in people:
        for aid in p["oa"]:
            try:
                a = oa_get(f"authors/{aid}", {"select": "works_count,cited_by_count,summary_stats"})
            except Exception as e:
                log("author lookup failed", aid, e)
                continue
            ss = a.get("summary_stats") or {}
            p["lw"] += a.get("works_count") or 0
            p["lc"] += a.get("cited_by_count") or 0
            p["h"] = max(p["h"], ss.get("h_index") or 0)
            p["i10"] = max(p["i10"], ss.get("i10_index") or 0)

    works = {}
    for i, p in enumerate(people):
        if not p["oa"]:
            continue
        ids = set(p["oa"])
        n = 0
        for w in oa_pages("works", {"filter": f"author.id:{'|'.join(p['oa'])},from_publication_date:{y0}-01-01", "select": SELECT}):
            au = w.get("authorships") or []
            mine = False
            lead = False
            for k, a in enumerate(au):
                aid = ((a.get("author") or {}).get("id") or "").split("/")[-1]
                if aid in ids and (k == 0 or k == len(au) - 1 or a.get("is_corresponding")):
                    lead = True
                if aid in ids:
                    insts = [x.get("id") for x in a.get("institutions") or []]
                    raw = " ".join(a.get("raw_affiliation_strings") or [])
                    if CARLETON in insts or re.search("carleton", raw, re.I):
                        mine = True
            if not mine and len(au) >= 100:  # author list truncated by OpenAlex: trust the author filter
                mine = True
            if not mine:
                continue
            n += 1
            wid = w["id"].split("/")[-1]
            if wid in works:
                if i not in works[wid]["f"]:
                    works[wid]["f"].append(i)
                if lead:
                    works[wid]["lead"].add(i)
                continue
            works[wid] = {"raw": w, "f": [i], "lead": {i} if lead else set()}
        log(f"{p['n']}: {n} outputs")

    topics, venues, insts = {}, {}, {}

    def idx(d, k, v=None):
        if k not in d:
            d[k] = (len(d), v)
        return d[k][0]

    rows_out = []
    for wid, rec in works.items():
        w = rec["raw"]
        if w.get("type") in DROP_TYPES or not w.get("title"):
            continue
        au = w.get("authorships") or []
        countries, inst_ix = set(), []
        if len(au) <= 60:
            for a in au:
                for x in a.get("institutions") or []:
                    if x.get("country_code"):
                        countries.add(x["country_code"])
                    if x.get("id") and x["id"] != CARLETON:
                        k = x["id"].split("/")[-1]
                        inst_ix.append(idx(insts, k, [x.get("display_name"), x.get("country_code") or "", x.get("type") or ""]))
        pt = w.get("primary_topic")
        tp = idx(topics, pt["id"], [pt["display_name"], (pt.get("subfield") or {}).get("display_name"), (pt.get("field") or {}).get("display_name")]) if pt else -1
        src = ((w.get("primary_location") or {}).get("source") or {}).get("display_name") or ""
        v = idx(venues, src) if src else -1
        fw = w.get("fwci")
        rows_out.append([wid[1:], w["title"].replace("�", ""), w.get("publication_date") or f"{w.get('publication_year')}-01-01",
                         TYPES.index(w["type"]) if w.get("type") in TYPES else 0, v, (w.get("doi") or "").replace("https://doi.org/", ""),
                         w.get("cited_by_count") or 0, None if fw is None else round(fw, 2), tp,
                         [k["display_name"] for k in (w.get("keywords") or [])[:4]], len(au), sorted(set(rec["f"])), sorted(countries),
                         sorted(set(inst_ix)), 1 if (w.get("open_access") or {}).get("is_oa") else 0, [], sorted(rec["lead"])])
    rows_out.sort(key=lambda r: r[2], reverse=True)
    inv = lambda d: [v for _, v in sorted(d.values(), key=lambda x: x[0])]
    data = {"gen": dt.date.today().isoformat(), "people": people, "works": rows_out,
            "topics": inv(topics), "venues": [k for k, _ in sorted(venues.items(), key=lambda kv: kv[1][0])], "insts": inv(insts), "types": TYPES}
    return data, works


# ---------------------------------------------------------------- Claude
def claude(messages, max_tokens=8000, tools=None, system=None):
    key = os.environ["ANTHROPIC_API_KEY"]
    body = {"model": CFG.get("model", "claude-sonnet-5-5"), "max_tokens": max_tokens, "messages": messages}
    if tools:
        body["tools"] = tools
    if system:
        body["system"] = system
    for turn in range(6):
        req = urllib.request.Request("https://api.anthropic.com/v1/messages", data=json.dumps(body).encode(),
                                     headers={"x-api-key": key, "anthropic-version": "2023-06-01", "content-type": "application/json"})
        for attempt in range(5):
            try:
                with urllib.request.urlopen(req, timeout=600) as r:
                    resp = json.loads(r.read())
                break
            except urllib.error.HTTPError as e:
                if e.code in (429, 500, 502, 503, 529):
                    time.sleep(10 * (attempt + 1))
                    continue
                raise RuntimeError(f"Claude API error {e.code}: {e.read().decode()[:500]}")
        else:
            raise RuntimeError("Claude API kept failing")
        if resp.get("stop_reason") == "pause_turn":  # long server-tool turn: let it continue
            body["messages"] = body["messages"] + [{"role": "assistant", "content": resp["content"]}]
            continue
        return "".join(b.get("text", "") for b in resp["content"] if b.get("type") == "text")
    raise RuntimeError("Claude did not finish")


def parse_json(text):
    m = re.findall(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.S)
    cand = m[-1] if m else text[text.find("{"): text.rfind("}") + 1]
    return json.loads(cand)


STYLE = ("Write in plain, direct Canadian English for a busy Associate Dean of Research. No hype, no marketing language, no em dashes, "
         "no phrases like 'groundbreaking' or 'novel'. Do not invent findings that are not in the abstract.")


def summarize(items):
    payload = [{"id": it["id"], "title": it["title"], "venue": it["venue"], "carleton_authors": [f"{n} ({u})" for n, u in it["who"]],
                "large_collaboration": it.get("big", False), "abstract": it.get("abstract", "")[:2500]} for it in items]
    prompt = (f"{STYLE}\n\nBelow are new publications by Carleton University Faculty of Science researchers this week. For each, write a 2-sentence "
              "summary a non-specialist colleague can follow: what was done and why it matters. If there is no abstract, describe only what the title "
              "says and note that no abstract was available. Then write a 2 to 4 sentence lead paragraph for the digest that highlights the week by unit "
              "and points out cross-unit collaborations.\n\nReturn only JSON in a ```json block: {\"lead\": str, \"summaries\": {id: str}}\n\n"
              + json.dumps(payload, ensure_ascii=False))
    return parse_json(claude([{"role": "user", "content": prompt}]))


CHECKS = ("market", "partner", "carleton_role", "evidence")


def innovation(items):
    """Screen papers with a fixed checklist. Claude answers each check with evidence; this code decides the tier."""
    crit = (ROOT / "config/innovation_criteria.md").read_text()
    payload = [{"id": it["id"], "title": it["title"], "venue": it["venue"], "carleton_authors": [f"{n} ({u})" for n, u in it["who"]],
                "author_order": it.get("author_order", ""), "doi_url": it.get("url"), "abstract": it.get("abstract", "")[:2500],
                "signals": it.get("signals", {})}
               for it in items if not it.get("big")]
    prompt = (f"{STYLE}\n\nYou screen this week's Carleton Faculty of Science publications for innovation, partnering or licensing opportunities "
              f"for the Associate Dean of Research, International and Innovation. The rules:\n\n{crit}\n\n"
              "Each paper carries 'signals' from our data: companies on the author list, industry funding, whether it is a preprint (patent grace "
              "period open), and the researcher's wider research line on this topic (paper count, momentum, companies citing that line). Use them as "
              "evidence for the market and partner checks; a company that already co-authors or cites the work is the strongest partner evidence. "
              "Where a paper or research line names people at a company (people_at_companies_on_this_paper, warm_contacts), use them in next_step as the introduction route. "
              "Step 1. Skip papers with no plausible commercial or partnering angle at all (pure theory, reviews, large collaborations). "
              "Step 2. For every remaining paper, answer each check with pass true/false and evidence of at most 20 words (a plain fact, no hedging). "
              "Also give 'would_change': at most 15 words on the one concrete thing that would flip the failed checks (for example 'a Carleton-led prototype "
              "with field data'), or an empty string if nothing realistic would. Use web search to verify partner "
              "companies are real and currently active (prefer Ottawa or Canadian), and to check whether code or methods are already public. "
              "Judge each check on its own; do not let one check decide another. Be consistent: the same facts must always give the same answers. "
              "Keep every field short so it scans: heading at most 12 words, what at most 40, market_fit at most 35, each partner why at most 20, "
              "next_step at most 40, route_reason at most 30. One fact per sentence. "
              "\n\n"
              "Return only JSON in a ```json block:\n"
              "{\"assessments\": [{\"id\": str, \"title\": str,\n"
              "  \"checks\": {\"market\": {\"pass\": bool, \"evidence\": str}, \"partner\": {\"pass\": bool, \"evidence\": str},\n"
              "              \"carleton_role\": {\"pass\": bool, \"evidence\": str}, \"evidence\": {\"pass\": bool, \"evidence\": str}},\n"
              "  \"route\": \"licence\" | \"partnership\" | \"unclear\", \"route_reason\": str,\n"
              "  \"heading\": str, \"what\": str, \"market_fit\": str, \"partners\": [{\"name\": str, \"location\": str, \"why\": str}],\n"
              "  \"next_step\": str, \"would_change\": str}],\n"
              " \"skipped\": [{\"id\": str, \"reason\": str (at most 8 words, e.g. 'review article' or 'basic evolutionary biology')}]}\n\n"
              + json.dumps(payload, ensure_ascii=False))
    tools = [{"type": "web_search_20250305", "name": "web_search", "max_uses": 10, "user_location": {"type": "approximate", "city": "Ottawa", "region": "Ontario", "country": "CA"}}]
    raw = parse_json(claude([{"role": "user", "content": prompt}], max_tokens=16000, tools=tools))
    out = tier_assessments(raw)
    out["counts"] = {"papers": len(items), "large_collaborations": sum(1 for it in items if it.get("big")),
                     "screened": len(out["opportunities"]) + len(out["near_misses"]), "skipped": len(out.get("skipped", []))}
    return out


def tier_assessments(raw):
    """Fixed rule: a paper is recommended only when all four checks pass. Anything else is a near-miss with its reason."""
    labels = {"carleton_role": "Carleton's role", "evidence": "evidence", "market": "market", "partner": "partner"}
    ops, near = [], []
    for a in raw.get("assessments", []):
        ch = a.get("checks", {})
        failed = [k for k in CHECKS if not (ch.get(k) or {}).get("pass")]
        if not failed:
            route = a.get("route", "unclear")
            ops.append({"tier": "act", "id": a.get("id"), "heading": a.get("heading") or a.get("title", ""), "what": a.get("what", ""),
                        "market_fit": a.get("market_fit", ""), "partners": a.get("partners", []), "next_step": a.get("next_step", ""),
                        "licensing_note": f"{'Licence' if route == 'licence' else 'Partnership' if route == 'partnership' else 'Route unclear'}. {a.get('route_reason', '')}".strip(),
                        "checks": {k: True for k in CHECKS}})
            ops[-1]["evidence"] = {k: (ch.get(k) or {}).get("evidence", "") for k in CHECKS}
        else:
            why = "; ".join(f"{labels[k]}: {(ch.get(k) or {}).get('evidence', '').rstrip('.')}" for k in failed)
            near.append({"id": a.get("id"), "title": a.get("title", a.get("id")), "why": why,
                         "checks": {k: {"pass": bool((ch.get(k) or {}).get("pass")), "note": (ch.get(k) or {}).get("evidence", "")} for k in CHECKS},
                         "would_change": a.get("would_change", "")})
    near.sort(key=lambda n: -sum(c["pass"] for c in n["checks"].values()))
    skipped = [{"id": x.get("id"), "reason": x.get("reason", "")} for x in raw.get("skipped", []) if isinstance(x, dict)]
    return {"opportunities": ops, "near_misses": near, "skipped": skipped, "screened": raw.get("skipped_note", "")}


def log_innovation(issue):
    p = ROOT / "state/innovation_log.json"
    log_ = json.loads(p.read_text()) if p.exists() else {}
    inn = issue.get("innovation") or {}
    for o in inn.get("opportunities", []):
        if o.get("id"):
            log_[o["id"]] = {"week_end": issue["week_end"], "outcome": "act", "heading": o.get("heading")}
    for n in inn.get("near_misses", []):
        if n.get("id"):
            log_[n["id"]] = {"week_end": issue["week_end"], "outcome": "near miss", "title": n.get("title"), "why": n.get("why")}
    p.write_text(json.dumps(log_, indent=1, ensure_ascii=False))


# ---------------------------------------------------------------- digest
def abstract_of(wid):
    try:
        d = oa_get(f"works/{wid}", {"select": "abstract_inverted_index"})
    except Exception:
        return ""
    ii = d.get("abstract_inverted_index") or {}
    pos = {}
    for word, ps in ii.items():
        for p in ps:
            pos[p] = word
    return " ".join(pos[k] for k in sorted(pos))


def make_issue(data, works, state, week_start, week_end, use_ai=True, lines=None, citers=None):
    people = data["people"]
    line_ix = {(L["person"], L["topic"]): L for L in (lines or [])}
    seen = set(state.get("seen", []))
    recent_floor = (week_end - dt.timedelta(days=60)).isoformat()
    cands = []
    for wid, rec in works.items():
        w = rec["raw"]
        if wid in seen or w.get("type") in DROP_TYPES or not w.get("title"):
            continue
        pub, created = w.get("publication_date") or "", w.get("created_date") or ""
        in_week = week_start.isoformat() <= pub <= week_end.isoformat()
        newly_indexed = week_start.isoformat() <= created[:10] <= week_end.isoformat() and pub >= recent_floor and pub <= week_end.isoformat()
        if in_week or newly_indexed:
            cands.append((wid, rec))
    items = []
    for wid, rec in cands:
        w = rec["raw"]
        who = [[people[i]["n"], people[i]["u"][0] if people[i]["u"] else ""] for i in rec["f"]]
        units = {u for i in rec["f"] for u in people[i]["u"]}
        first_units = {people[i]["u"][0] for i in rec["f"] if people[i]["u"]}
        big = len(w.get("authorships") or []) >= 100
        au = w.get("authorships") or []
        def _who(x):
            n = ((x.get("author") or {}).get("display_name")) or "?"
            inst = ", ".join(i.get("display_name", "") for i in (x.get("institutions") or [])[:1])
            return f"{n} ({inst})" if inst else n
        car_pos = [k + 1 for k, x in enumerate(au) if CARLETON in [i.get("id") for i in x.get("institutions") or []]]
        author_order = (f"{len(au)} authors; first: {_who(au[0])}; last: {_who(au[-1])}; Carleton authors at positions {car_pos}") if au and not big else ""
        items.append({"id": wid, "who": who, "who_note": "with a large collaboration" if big else "", "title": re.sub(r"<[^>]+>", "", w["title"]),
                      "url": f"https://doi.org/{w['doi'].replace('https://doi.org/', '')}" if w.get("doi") else f"https://openalex.org/{wid}",
                      "venue": ((w.get("primary_location") or {}).get("source") or {}).get("display_name") or "", "date": w.get("publication_date"),
                      "oa": bool((w.get("open_access") or {}).get("is_oa")), "big": big, "cross": len(first_units) > 1,
                      "unit": sorted(first_units)[0] if first_units else "Other", "preprint": w.get("type") == "preprint", "author_order": author_order})
    for it, (wid, rec) in zip(items, cands):
        w = rec["raw"]
        sig = SIG.work_signals(w)
        topic = (w.get("primary_topic") or {}).get("display_name")
        ln = [line_ix.get((i, topic)) for i in rec["f"]]
        ln = [x for x in ln if x]
        it["signals"] = {"company_coauthors": sig["companies"], "industry_funding": sig["industry"], "funders": sig["funders"][:5],
                         "people_at_companies_on_this_paper": [f"{n} ({c})" for n, c in sig["company_people"][:5]],
                         "companies_citing": sorted((citers or {}).get(wid, set()))[:6],
                         "preprint_grace_until": (dt.date.fromisoformat(w["publication_date"]) + dt.timedelta(days=365)).isoformat() if it["preprint"] and w.get("publication_date") else "",
                         "research_line": [{"researcher": x["name"], "topic": x["topic"], "papers_3y": x["n"], "recent_2y": x["recent"], "lead_share": x["lead_share"],
                                            "companies_citing_line": x["citers"][:5], "companies_coauthoring_line": x["companies"][:5],
                                            "partner_ready": x.get("ready_reasons", []), "warm_contacts": x.get("contacts", [])} for x in ln]}
    log(f"{len(items)} new outputs for {week_label({'week_start': week_start.isoformat(), 'week_end': week_end.isoformat()})}")
    for it in items:
        it["abstract"] = abstract_of(it["id"])
    lead, summ, inn = "", {}, {"opportunities": [], "screened": ""}
    if items and use_ai:
        s = summarize(items)
        lead, summ = s.get("lead", ""), s.get("summaries", {})
        try:
            inn = innovation(items)
        except Exception as e:
            log("innovation screen failed:", e)
            inn = {"opportunities": [], "screened": "The innovation screen did not run this week."}
    for it in items:
        it["summary"] = summ.get(it["id"]) or (it["abstract"][:300].rsplit(" ", 1)[0] + "..." if it["abstract"] else "No abstract was available when this digest was assembled.")
    main = [it for it in items if not it["preprint"]]
    pre = [it for it in items if it["preprint"]]
    by_unit = {}
    for it in sorted(main, key=lambda x: x["date"], reverse=True):
        by_unit.setdefault(it["unit"], []).append({k: v for k, v in it.items() if k not in ("abstract", "unit", "preprint", "author_order", "signals")})
    issue = {"issue": state.get("last_issue", 0) + 1, "week_start": week_start.isoformat(), "week_end": week_end.isoformat(),
             "lead": lead or ("A quiet week: no new Faculty of Science outputs were indexed." if not items else f"{len(items)} new outputs this week."),
             "units": [{"unit": u, "items": by_unit[u]} for u in sorted(by_unit)], "innovation": inn}
    if pre:
        issue["also_title"] = "Preprints"
        issue["also"] = [f"{', '.join(n for n, _ in it['who'])} ({it['who'][0][1]}): {it['title']}. {it['venue']}, {it['date']}." for it in pre]
    return issue, [it["id"] for it in items]



# ---------------------------------------------------------------- quarterly partnership brief
def quarter_label(d):
    return f"{d.year}-Q{(d.month - 1) // 3 + 1}"


def quarterly_brief(lines, n_screen=12):
    """Screen the strongest research lines with the four fixed checks; keep only lines that pass all four."""
    crit = (ROOT / "config/innovation_criteria.md").read_text()
    short = [L for L in lines if L.get("pull", 0) > 0][:n_screen]
    if not short:
        return {"picks": [], "near_misses": [], "screened": 0}
    for L in short:
        L["patent_landscape"] = SIG.patent_landscape([L["topic"]] + L["titles"][:1])
    payload = [{"id": f"L{k}", "researcher": f"{L['name']} ({', '.join(L['units'])}, {L['rank']})", "topic": L["topic"],
                "papers_last_3y": L["n"], "recent_2y": L["recent"], "earlier": L["prior"], "share_as_lead_author": L["lead_share"],
                "recent_titles": L["titles"], "companies_coauthoring": L["companies"], "companies_citing": L["citers"],
                "industry_funding": L["industry"], "main_funders": L["funders"], "nserc_partners": L["nserc_partners"],
                "carleton_patents": L["patents"], "open_preprints": L["preprints"], "cv_items": L["cv"],
                "latest_nserc_grant": L.get("current_grant"), "grant_timing": L.get("timing", ""),
                "partner_ready_evidence": L.get("ready_reasons", []), "warm_contacts": L.get("contacts", []),
                "companies_patenting_in_topic": L.get("patent_landscape", [])} for k, L in enumerate(short)]
    prompt = (f"{STYLE}\n\nOnce a quarter you pick the best partnership or IP opportunities in Carleton University's Faculty of Science "
              f"for the Associate Dean of Research, International and Innovation. Below are the {len(short)} research lines with the strongest "
              "industry signals: one researcher's sustained work on one topic, with companies that co-author, cite or fund it. "
              f"Rules:\n\n{crit}\n\nFor 'carleton_role', use share_as_lead_author (0.5 or more passes) plus the titles. For 'evidence', judge the "
              "line as a whole, not one paper. For 'partner', prefer companies already in the signals; verify with web search that they are real and "
              "active, preferring Ottawa and Canadian ones, and add at most one new company you find. Note open preprints as an IP clock. "
              "'warm_contacts' are named people at companies who already co-authored with the researcher: when one is at a partner you list, "
              "say so in next_step (who to ask for the introduction). 'partner_ready_evidence' is the researcher's track record with industry; "
              "'grant_timing' flags a Discovery grant ending, which is a good moment to propose an Alliance grant. "
              "Be strict and consistent: most lines will not pass every check. Each check's evidence is at most 20 words, a plain fact. "
              "Also give 'would_change': at most 15 words on the one concrete thing that would flip the failed checks, or an empty string. "
              "Keep every field short so it scans: heading at most 12 words, what at most 40, market_fit at most 35, each partner why at most 20, "
              "next_step at most 40, route_reason at most 30. One fact per sentence. "
              "\n\n"
              "Return only JSON in a ```json block:\n"
              "{\"assessments\": [{\"id\": str, \"title\": str (researcher and topic),\n"
              "  \"checks\": {\"market\": {\"pass\": bool, \"evidence\": str}, \"partner\": {\"pass\": bool, \"evidence\": str},\n"
              "              \"carleton_role\": {\"pass\": bool, \"evidence\": str}, \"evidence\": {\"pass\": bool, \"evidence\": str}},\n"
              "  \"route\": \"licence\" | \"partnership\" | \"unclear\", \"route_reason\": str,\n"
              "  \"heading\": str, \"what\": str, \"market_fit\": str, \"partners\": [{\"name\": str, \"location\": str, \"why\": str}],\n"
              "  \"next_step\": str, \"would_change\": str}],\n \"skipped_note\": str}\n\n" + json.dumps(payload, ensure_ascii=False))
    tools = [{"type": "web_search_20250305", "name": "web_search", "max_uses": 15, "user_location": {"type": "approximate", "city": "Ottawa", "region": "Ontario", "country": "CA"}}]
    raw = parse_json(claude([{"role": "user", "content": prompt}], max_tokens=20000, tools=tools))
    tiers = tier_assessments(raw)
    byid = {f"L{k}": L for k, L in enumerate(short)}
    picks = []
    for o in tiers["opportunities"]:
        L = byid.get(o.get("id"), {})
        o["signals"] = {k: L.get(k) for k in ("name", "units", "topic", "n", "recent", "lead_share", "companies", "citers", "industry", "preprints", "patents",
                                              "ready", "ready_reasons", "contacts", "timing")}
        o["score"] = L.get("score", 0)
        picks.append(o)
    picks.sort(key=lambda o: o["score"], reverse=True)
    for n in tiers.get("near_misses", []):
        L = byid.get(n.get("id"), {})
        if L:
            n["who"] = f"{L['name']} ({', '.join(L['units'])})"
    return {"picks": picks[:3], "near_misses": tiers.get("near_misses", []), "screened": len(short)}


def run_brief(lines, today, send=True, force=False):
    st_p = ROOT / "state/brief_state.json"
    st = json.loads(st_p.read_text()) if st_p.exists() else {}
    q = quarter_label(today)
    if st.get("last_quarter") == q and not force:
        log(f"Quarterly brief for {q} already made.")
        return
    brief = quarterly_brief(lines)
    brief.update({"quarter": q, "date": today.isoformat()})
    d = ROOT / "state/briefs"
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{q}.json").write_text(json.dumps(brief, ensure_ascii=False, indent=1), encoding="utf-8")
    render_briefs()
    st["last_quarter"] = q
    st_p.write_text(json.dumps(st, indent=1))
    site = CFG.get("site_url", "").rstrip("/")
    if send:
        send_mail(f"Carleton Science quarterly partnership brief: {q}", render_brief_email(brief, f"{site}/brief/" if site else "", f"{site}/logo.png" if site else ""),
                  f"Quarterly partnership brief {q}. Read it at {site}/brief/")


def render_briefs():
    files = sorted((ROOT / "state/briefs").glob("*.json")) if (ROOT / "state/briefs").exists() else []
    out = ROOT / "docs/brief"
    out.mkdir(parents=True, exist_ok=True)
    qs = [f.stem for f in files][::-1]
    for f in files:
        b = json.loads(f.read_text(encoding="utf-8"))
        (out / f"{f.stem}.html").write_text(render_brief_web(b, qs, "../logo.png", ""), encoding="utf-8")
    if files:
        (out / "index.html").write_text(render_brief_web(json.loads(files[-1].read_text(encoding="utf-8")), qs, "../logo.png", ""), encoding="utf-8")


# ---------------------------------------------------------------- email
def send_email(issue, web_url, dash_url):
    subject = f"Carleton Science research digest: {week_label(issue)}"
    send_mail(subject, render_email(issue, web_url, dash_url, f"{dash_url}logo.png" if dash_url else ""), render_text(issue, dash_url))


def send_mail(subject, html_body, text_body):
    to = os.environ.get("DIGEST_TO")
    if not to:
        log("DIGEST_TO not set; skipping email")
        return
    if os.environ.get("RESEND_API_KEY"):
        body = {"from": os.environ.get("DIGEST_FROM") or "Carleton Science Digest <onboarding@resend.dev>", "to": [x.strip() for x in to.split(",") if x.strip()],
                "subject": subject, "html": html_body, "text": text_body}
        req = urllib.request.Request("https://api.resend.com/emails", data=json.dumps(body).encode(),
                                     headers={"Authorization": f"Bearer {os.environ['RESEND_API_KEY']}", "Content-Type": "application/json", "User-Agent": "carleton-science-digest"})
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                log("email sent via Resend:", r.read().decode()[:200])
        except urllib.error.HTTPError as e:
            raise RuntimeError(f"Resend refused the email ({e.code}): {e.read().decode()[:500]}")
        return
    if os.environ.get("SMTP_HOST"):
        msg = MIMEMultipart("alternative")
        msg["Subject"], msg["From"], msg["To"] = subject, os.environ.get("DIGEST_FROM") or os.environ["SMTP_USER"], to
        msg.attach(MIMEText(text_body, "plain", "utf-8"))
        msg.attach(MIMEText(html_body, "html", "utf-8"))
        with smtplib.SMTP(os.environ["SMTP_HOST"], int(os.environ.get("SMTP_PORT", "587"))) as s:
            s.starttls(context=ssl.create_default_context())
            s.login(os.environ["SMTP_USER"], os.environ["SMTP_PASS"])
            s.sendmail(msg["From"], [x.strip() for x in to.split(",")], msg.as_string())
        log("email sent via SMTP")
        return
    log("No RESEND_API_KEY or SMTP_HOST set; skipping email")


# ---------------------------------------------------------------- main
def write_digest(issue):
    issues_dir = ROOT / "state/issues"
    issues_dir.mkdir(parents=True, exist_ok=True)
    (issues_dir / f"{issue['week_end']}.json").write_text(json.dumps(issue, ensure_ascii=False, indent=1), encoding="utf-8")
    render_all()


def render_all():
    """Re-render the latest digest and every archived issue from state/issues/*.json."""
    site = CFG.get("site_url", "").rstrip("/")
    dash = f"{site}/" if site else "../"
    files = sorted((ROOT / "state/issues").glob("*.json"))
    dates = [f.stem for f in files][::-1]
    out = ROOT / "docs/digest/issues"
    out.mkdir(parents=True, exist_ok=True)
    for f in files:
        iss = json.loads(f.read_text(encoding="utf-8"))
        (out / f"{f.stem}.html").write_text(render_web(iss, "../../", [d for d in dates], logo_src="../../logo.png", archive_prefix=""), encoding="utf-8")
    if files:
        latest = json.loads(files[-1].read_text(encoding="utf-8"))
        (ROOT / "docs/digest/index.html").write_text(render_web(latest, "../", dates, logo_src="../logo.png", archive_prefix="issues/"), encoding="utf-8")
    return dash


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-email", action="store_true")
    ap.add_argument("--no-ai", action="store_true")
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--week-end")
    ap.add_argument("--render-only", action="store_true", help="re-render pages from saved issues, no network")
    ap.add_argument("--brief", action="store_true", help="make the quarterly partnership brief now")
    ap.add_argument("--data-only", action="store_true", help="rebuild dashboard data and signals only; no digest, brief or email")
    a = ap.parse_args()
    if a.render_only:
        render_all()
        render_briefs()
        log("rendered")
        return
    today = dt.date.today()
    week_end = dt.date.fromisoformat(a.week_end) if a.week_end else today - dt.timedelta(days=today.weekday() + 1)
    week_start = week_end - dt.timedelta(days=6)
    state_p = ROOT / "state/digest_state.json"
    state = json.loads(state_p.read_text())
    done_already = state.get("last_week_end") == week_end.isoformat()
    if done_already and not a.force and not a.brief and not a.data_only:
        log("This week's digest was already made. Use --force to rebuild it.")
        return
    skip_digest = (done_already and not a.force) or a.data_only  # brief-only or data-only run
    if a.force and state.get("last_week_end") == week_end.isoformat():
        state["last_issue"] = state.get("last_issue", 1) - 1
        prev = ROOT / f"state/issues/{week_end.isoformat()}.json"
        if prev.exists():  # let this week's papers be summarized again
            done = {it.get("id") for u in json.loads(prev.read_text(encoding="utf-8"))["units"] for it in u["items"]}
            state["seen"] = [x for x in state.get("seen", []) if x not in done]

    rows = load_roster()
    if match_new_people(rows):
        save_roster(rows)
    y0 = today.year - 5
    data, works = build_data(rows, y0)
    (ROOT / "docs/data.json").write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    log(f"data.json: {len(data['works'])} outputs")

    try:
        lines, citers = SIG.compute(data, works, y0, oa_pages)
    except Exception as e:
        log("signals failed, continuing without them:", e)
        lines, citers = [], {}
    site = CFG.get("site_url", "").rstrip("/")
    if not skip_digest:
        issue, new_ids = make_issue(data, works, state, week_start, week_end, use_ai=not a.no_ai, lines=lines, citers=citers)
        write_digest(issue)
        log_innovation(issue)
        state.update({"last_week_end": week_end.isoformat(), "last_issue": issue["issue"], "seen": sorted(set(state.get("seen", [])) | set(new_ids))})
        state_p.write_text(json.dumps(state, indent=1))
        if not a.no_email:
            send_email(issue, f"{site}/digest/" if site else "", f"{site}/" if site else "")
    quarter_start = today.month in (1, 4, 7, 10) and today.day <= 7
    if (a.brief or quarter_start) and lines and not a.no_ai and not a.data_only:
        try:
            run_brief(lines, today, send=not a.no_email, force=a.brief)
        except Exception as e:
            log("quarterly brief failed:", e)


if __name__ == "__main__":
    main()
