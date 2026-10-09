"""Render a weekly digest issue (JSON) to a web page, an email body and plain text.

The issue JSON looks like:
{
  "issue": 1, "week_start": "2026-09-28", "week_end": "2026-10-04",
  "lead": "One paragraph overview.",
  "units": [{"unit": "Biology", "items": [
      {"who": [["Bruce McKay", "Biology"], ...], "who_note": "", "title": "...", "url": "https://doi.org/...",
       "venue": "...", "date": "2026-09-30", "oa": true, "big": false, "cross": true, "summary": "..."}]}],
  "innovation": {"opportunities": [{"heading": "...", "what": "...", "market_fit": "...",
       "partners": [{"name": "...", "location": "...", "why": "..."}], "next_step": "...", "licensing_note": "..."}],
       "screened": "..."},
  "also": ["plain text line", ...], "also_title": "Also published"
}
"""
import datetime as dt
import html
import json
import sys
from gate import gate_html

PREPARED = "Independent summary built from public data (OpenAlex, NSERC, SSHRC). Not an official Carleton University publication."
import re
E = lambda s: html.escape(re.sub(r"</?cite[^>]*>", "", str(s or "")), quote=True)


def fmt_day(d):
    x = dt.date.fromisoformat(d)
    return x.strftime("%b ") + str(x.day)


def week_label(issue):
    a, b = dt.date.fromisoformat(issue["week_start"]), dt.date.fromisoformat(issue["week_end"])
    return f"Week of {a.strftime('%B')} {a.day} to {b.strftime('%B')} {b.day}, {b.year}"


def stats(issue):
    items = [it for u in issue["units"] for it in u["items"]]
    people = {n for it in items for n, _ in it["who"]}
    units = {u["unit"] for u in issue["units"] if u["items"]}
    cross = sum(1 for it in items if it.get("cross"))
    return len(items), len(people), len(units), cross


CSS = """
:root{--bg:#f3f4f6;--paper:#ffffff;--ink:#15171c;--ink-2:#4a4f5a;--muted:#6e7380;--line:#d9dce1;--line-2:#ebedf0;--accent:#b0162b;--accent-soft:#f7e3e6;
--f-display:"IBM Plex Sans Condensed","Arial Narrow",system-ui,sans-serif;--f-body:"IBM Plex Sans",system-ui,sans-serif;--f-read:"IBM Plex Serif",Georgia,serif;--f-mono:"IBM Plex Mono",ui-monospace,Menlo,monospace}
@media (prefers-color-scheme: dark){:root:not([data-theme="light"]){--bg:#111316;--paper:#191c20;--ink:#eceef1;--ink-2:#c1c5cd;--muted:#9298a3;--line:#2e3238;--line-2:#262a30;--accent:#ec5a6d;--accent-soft:#3a1d22;color-scheme:dark}}
:root[data-theme="dark"]{--bg:#111316;--paper:#191c20;--ink:#eceef1;--ink-2:#c1c5cd;--muted:#9298a3;--line:#2e3238;--line-2:#262a30;--accent:#ec5a6d;--accent-soft:#3a1d22;color-scheme:dark}
*{box-sizing:border-box}
body{background:var(--bg);color:var(--ink);font-family:var(--f-body);font-size:15px;line-height:1.5;margin:0}
.col{max-width:760px;margin:0 auto;padding-inline:16px;padding-block:28px 56px}
.sheet{background:var(--paper);border:1px solid var(--line);border-radius:6px;padding:clamp(18px,4vw,40px)}
.logo{display:block;width:clamp(160px,30vw,220px);height:auto;background:#fff;border-radius:4px;padding:6px 8px;margin:0 0 18px -8px}
.eyebrow{font-family:var(--f-mono);font-size:11px;letter-spacing:.08em;text-transform:uppercase;color:var(--muted);display:flex;gap:10px;align-items:center}
.eyebrow i{display:inline-block;width:10px;height:10px;background:var(--accent)}
h1{font-family:var(--f-display);font-weight:600;font-size:clamp(28px,5vw,40px);line-height:1.05;margin:8px 0 6px;text-wrap:balance}
.dates{font-family:var(--f-mono);font-size:13px;color:var(--ink-2)}
.prep{font-size:13px;color:var(--ink-2);margin-top:4px}
.stats{display:flex;flex-wrap:wrap;gap:6px 22px;margin:18px 0 0;padding:14px 0;border-top:1px solid var(--line);border-bottom:1px solid var(--line)}
.stats div{display:flex;flex-direction:column}
.stats b{font-family:var(--f-display);font-size:26px;font-weight:600;line-height:1.1;font-variant-numeric:tabular-nums}
.stats span{font-size:12px;color:var(--muted)}
.lead{font-family:var(--f-read);font-size:17px;line-height:1.6;margin:20px 0 0;max-width:62ch}
.tools{display:flex;flex-wrap:wrap;gap:8px;align-items:center;margin-top:18px}
.btn{border:1px solid var(--line);background:var(--paper);border-radius:4px;padding:6px 11px;cursor:pointer;font:inherit;font-size:13px;font-weight:500;color:var(--ink);text-decoration:none}
.btn:hover{border-color:var(--ink-2)}
.note{font-size:12.5px;color:var(--muted)}
h2{font-family:var(--f-display);font-weight:600;font-size:13px;letter-spacing:.07em;text-transform:uppercase;color:var(--ink-2);margin:34px 0 4px;padding-bottom:6px;border-bottom:2px solid var(--ink);display:flex;justify-content:space-between;gap:12px}
h2 span{font-family:var(--f-mono);font-weight:400;letter-spacing:0;text-transform:none;color:var(--muted)}
.item{padding:16px 0;border-bottom:1px solid var(--line-2)}
.item:last-child{border-bottom:0}
.item .who{font-size:13px;font-weight:600;color:var(--accent)}
.item .who small{font-weight:400;color:var(--muted)}
.item h3{font-family:var(--f-body);font-size:16px;font-weight:600;line-height:1.35;margin:4px 0 6px}
.item h3 a{color:inherit;text-decoration:none}
.item h3 a:hover{text-decoration:underline}
.item p{font-family:var(--f-read);font-size:15.5px;line-height:1.6;margin:0;max-width:64ch}
.item .src{font-size:12.5px;color:var(--muted);margin-top:6px}
.tag{display:inline-block;font-size:11px;padding:1px 6px;border-radius:3px;background:var(--accent-soft);color:var(--ink);margin-left:4px;vertical-align:1px}
.opp{margin-top:34px;border:1px solid var(--line);border-left:3px solid var(--accent);border-radius:4px;padding:16px 18px;background:var(--bg)}
.opp h2{margin:0 0 10px;border-bottom:0;padding-bottom:0}
.opp h4{font-size:15px;margin:14px 0 4px;font-weight:600}
.opp h4:first-of-type{margin-top:0}
.opp p,.opp li{font-size:14px;line-height:1.55;margin:0 0 8px;max-width:66ch}
.opp ul{padding-left:1.1em;margin:4px 0 8px}
.opp .k{font-weight:600}\n.tier{display:inline-block;font-size:11px;font-weight:600;padding:1px 7px;border-radius:3px;margin-right:6px;vertical-align:2px;letter-spacing:.02em}\n.tier.act{background:var(--accent);color:#fff}\n.tier.conversation{background:var(--accent-soft);color:var(--ink)}
.opp .tally{font-family:var(--f-mono);font-size:12px;color:var(--ink-2);margin:0 0 6px}
.opp .rule{font-size:12.5px;color:var(--muted);margin:0 0 4px}
.opp h4.sub{font-family:var(--f-display);font-size:12px;letter-spacing:.06em;text-transform:uppercase;color:var(--ink-2);margin:16px 0 6px;font-weight:600}
.opp h4.sub span{font-family:var(--f-body);text-transform:none;letter-spacing:0;font-weight:400;color:var(--muted)}
.opp .none{color:var(--ink-2)}
.opp .rec{border:1px solid var(--line);border-radius:4px;padding:12px 14px;background:var(--paper);margin:0 0 10px}
.opp .rw{font-size:13px;font-weight:600;color:var(--accent)}
.opp .rec .sig{font-size:12px;color:var(--muted);margin:0 0 6px}
.opp .rec h5{font-size:15px;margin:0 0 4px}.opp .rec h5 a{color:inherit}
.opp dl{display:grid;grid-template-columns:max-content 1fr;gap:4px 12px;margin:8px 0 0;font-size:13.5px}
.opp dt{font-weight:600}.opp dd{margin:0}.opp dd ul{margin:0;padding-left:1.1em}.opp dd li{margin:0 0 4px}
.opp .nm{padding:10px 0;border-top:1px solid var(--line-2)}
.opp .nt{font-size:14px;font-weight:600;line-height:1.35}.opp .nt a{color:inherit}
.opp .nw{font-size:12.5px;color:var(--muted);margin:2px 0 6px}
.opp .chips{display:flex;flex-wrap:wrap;gap:4px;margin:0 0 6px}
.opp .chk{font-size:11.5px;padding:1px 7px;border-radius:3px;border:1px solid var(--line)}
.opp .chk.y{color:#1d6b3a;border-color:#b9dcc6;background:#eef7f1}
.opp .chk.n{color:var(--accent);border-color:#f0c2c9;background:#fbeef0}
.opp .nm ul{margin:0;padding-left:1.1em}.opp .nm li{font-size:13.5px;margin:0 0 3px}
.opp .wc{font-size:13px;margin:4px 0 0;color:var(--ink-2)}
.opp .more{font-size:12.5px;color:var(--muted);margin:10px 0 0}
.opp .screened{font-size:12.5px;color:var(--muted);border-top:1px solid var(--line-2);padding-top:10px;margin-top:10px}
.also{font-size:14px}
.also ul{padding-left:1.1em;margin:10px 0 0}
.also li{margin:0 0 10px}
.foot{margin-top:28px;padding-top:14px;border-top:1px solid var(--line);font-size:12.5px;color:var(--muted)}
.foot a,.arch a{color:var(--accent)}
.arch{margin-top:10px;font-size:12.5px;color:var(--muted)}
a:focus-visible,button:focus-visible{outline:2px solid var(--accent);outline-offset:2px}
"""

FONTS = '<link rel="preconnect" href="https://fonts.googleapis.com"><link rel="preconnect" href="https://fonts.gstatic.com" crossorigin><link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;500&family=IBM+Plex+Sans+Condensed:wght@500;600&family=IBM+Plex+Serif:ital,wght@0,400;0,500;1,400&family=IBM+Plex+Sans:wght@400;500;600&display=swap">'

FOOT = ("Summaries and the innovation section were written by Claude from each paper's abstract and public company information, "
        "so check the paper and the company before acting. The innovation section screens every paper on the same four checks and "
        "recommends one only when all four pass, so most weeks nothing is recommended. Papers are matched to the Faculty list using OpenAlex, which can miss outputs "
        "or lag a few weeks behind publication.")


def who_html(it):
    s = ", ".join(f"{E(n)} <small>{E(u)}</small>" for n, u in it["who"])
    if it.get("who_note"):
        s += f" <small>{E(it['who_note'])}</small>"
    if it.get("cross"):
        s += '<span class="tag">cross-unit</span>'
    return s


def src_line(it):
    bits = [E(it.get("venue") or "Venue not recorded"), fmt_day(it["date"])]
    if it.get("oa"):
        bits.append("open access")
    if it.get("big"):
        bits.append("large collaboration")
    return " · ".join(bits)


CHECK_ORDER = ("market", "partner", "carleton_role", "evidence")
CHECK_NAME = {"market": "Market", "partner": "Partner", "carleton_role": "Carleton-led", "evidence": "Evidence"}
CHECK_RULE = ("Four checks: <b>Market</b> (someone buys this today), <b>Partner</b> (a named, active company, Canadian preferred), "
              "<b>Carleton-led</b> (first, last or corresponding author), <b>Evidence</b> (a working result, not just an idea). "
              "A paper is recommended only when all four pass.")
LEGACY_LABELS = {"market": "market", "partner": "partner", "Carleton's role": "carleton_role", "evidence": "evidence"}
MAX_NEAR = 5


def _parse_why(why):
    """Older issues stored only the failed checks as 'label: text; label: text'."""
    checks = {k: {"pass": True, "note": ""} for k in CHECK_ORDER}
    for part in (why or "").split("; "):
        lab, _, txt = part.partition(": ")
        k = LEGACY_LABELS.get(lab.strip())
        if k:
            checks[k] = {"pass": False, "note": txt.strip()}
    return checks


def innov_model(issue):
    """One structure for every renderer, built the same way every week."""
    inn = issue.get("innovation") or {}
    items = {it["id"]: it for u in issue.get("units", []) for it in u["items"] if it.get("id")}
    def person(i):
        it = items.get(i)
        return ", ".join(f"{n} ({u})" for n, u in it["who"]) if it else ""
    rec = [dict(o, who=person(o.get("id")), url=(items.get(o.get("id")) or {}).get("url", "")) for o in inn.get("opportunities") or []]
    near = []
    for n in inn.get("near_misses") or []:
        near.append(norm_near(dict(n, url=(items.get(n.get("id")) or {}).get("url", "")), person(n.get("id"))))
    near.sort(key=lambda x: -x["passed"])
    skipped = [{"title": (items.get(x["id"]) or {}).get("title", ""), "who": person(x["id"]), "reason": x.get("reason", "")}
               for x in inn.get("skipped") or [] if x.get("id")]
    skipped_text = ""
    if not skipped and inn.get("screened"):  # older issues: free text after the near-miss list
        t = inn["screened"]
        k = t.find("Skipped")
        skipped_text = t[k:] if k >= 0 else ("" if t.startswith("Screened, nothing") else t)
    c = inn.get("counts") or {}
    counts = {"papers": c.get("papers", sum(len(u["items"]) for u in issue.get("units", []))), "screened": len(rec) + len(near),
              "recommended": len(rec), "near": len(near), "skipped": len(skipped) if skipped else c.get("skipped"),
              "big": c.get("large_collaborations", 0)}
    return {"rec": rec, "near": near, "skipped": skipped, "skipped_text": skipped_text, "counts": counts}


def tally(m):
    c = m["counts"]
    bits = [f"Screened {c['screened']} of {c['papers']} papers", f"{c['recommended']} recommended", f"{c['near']} near miss{'es' if c['near'] != 1 else ''}"]
    if c.get("skipped"):
        bits.append(f"{c['skipped']} with no commercial angle")
    if c.get("big"):
        bits.append(f"{c['big']} large collaboration{'s' if c['big'] != 1 else ''} not screened")
    return " · ".join(bits)


def gap_of(n):
    fails = [k for k in CHECK_ORDER if not n["checks"][k]["pass"]]
    return [(CHECK_NAME[k], n["checks"][k]["note"]) for k in fails]


def _cell(v, email=False):
    if not isinstance(v, list):
        return E(v)
    st = " style='margin:0;padding-left:16px'" if email else ""
    li = " style='margin:0 0 4px'" if email else ""
    return f"<ul{st}>" + "".join(f"<li{li}>{E(x)}</li>" for x in v) + "</ul>"


def rec_rows(o):
    ev = o.get("evidence") or {}
    rows = [("Route", o.get("licensing_note", "")), ("Market", o.get("market_fit", "")),
            ("Partners", [f"{p['name']} ({p['location']}): {p['why']}" for p in o.get("partners", [])]),
            ("Carleton lead", (o.get("who") or "") + (f". {ev.get('carleton_role')}" if ev.get("carleton_role") else "")),
            ("Evidence", ev.get("evidence", "")), ("Next step", o.get("next_step", ""))]
    return [(k, v) for k, v in rows if v]


def norm_near(n, who=""):
    checks = n.get("checks") if isinstance(n.get("checks"), dict) and all(isinstance(v, dict) for v in n["checks"].values()) else _parse_why(n.get("why"))
    return {"title": n.get("title", ""), "url": n.get("url", ""), "who": n.get("who") or who, "checks": checks,
            "passed": sum(1 for k in CHECK_ORDER if checks[k]["pass"]), "would_change": n.get("would_change", "")}


def near_html(near, unit="paper"):
    out = [f'<h4 class="sub">Near misses <span>closest first</span></h4>']
    for n in near[:MAX_NEAR]:
        t = f'<a href="{E(n["url"])}" target="_blank" rel="noopener">{E(n["title"])}</a>' if n.get("url") else E(n["title"])
        chips = "".join(f'<span class="chk {"y" if n["checks"][k]["pass"] else "n"}">{"✓" if n["checks"][k]["pass"] else "✗"} {CHECK_NAME[k]}</span>' for k in CHECK_ORDER)
        gaps = "".join(f"<li><b>{E(k)}:</b> {E(v)}</li>" for k, v in gap_of(n))
        wc = f'<p class="wc"><b>Would change the call:</b> {E(n["would_change"])}</p>' if n.get("would_change") else ""
        who = f'<div class="nw">{E(n["who"])}</div>' if n.get("who") else '<div class="nw"></div>'
        out.append(f'<div class="nm"><div class="nt">{t}</div>{who}<div class="chips">{chips}</div><ul>{gaps}</ul>{wc}</div>')
    if len(near) > MAX_NEAR:
        out.append(f'<p class="more">Also screened: {E("; ".join(f"{x['title']} ({x['passed']}/4)" for x in near[MAX_NEAR:]))}.</p>')
    return "".join(out)


def near_email(near, muted, accent, line):
    green = "#1d6b3a"
    body = [f"<div style='font-size:12px;letter-spacing:1px;text-transform:uppercase;color:#4a4f5a;font-weight:bold;margin:14px 0 4px'>Near misses <span style='text-transform:none;letter-spacing:0;font-weight:normal;color:{muted}'>closest first</span></div>"]
    for n in near[:MAX_NEAR]:
        chips = " ".join(f"<span style='display:inline-block;font-size:11.5px;padding:1px 6px;border:1px solid {'#b9dcc6' if n['checks'][k]['pass'] else '#f0c2c9'};"
                         f"color:{green if n['checks'][k]['pass'] else accent};background:{'#eef7f1' if n['checks'][k]['pass'] else '#fbeef0'}'>{'&#10003;' if n['checks'][k]['pass'] else '&#10007;'} {CHECK_NAME[k]}</span>" for k in CHECK_ORDER)
        gaps = "".join(f"<li style='margin:0 0 3px'><b>{E(k)}:</b> {E(v)}</li>" for k, v in gap_of(n))
        wc = f"<p style='margin:4px 0 0;font-size:13px'><b>Would change the call:</b> {E(n['would_change'])}</p>" if n.get("would_change") else ""
        body.append(f"<div style='border-top:1px solid {line};padding:9px 0'><div style='font-weight:bold;font-size:14px'>{E(n['title'])}</div>"
                    f"<div style='font-size:12.5px;color:{muted};margin:2px 0 6px'>{E(n['who'])}</div><div>{chips}</div>"
                    f"<ul style='margin:6px 0 0;padding-left:18px;font-size:13.5px'>{gaps}</ul>{wc}</div>")
    if len(near) > MAX_NEAR:
        rest = "; ".join(f"{x['title']} ({x['passed']}/4)" for x in near[MAX_NEAR:])
        body.append(f"<p style='margin:8px 0 0;color:{muted};font-size:12.5px'>Also screened: {E(rest)}.</p>")
    return "".join(body)


def near_text(near):
    L = ["", "NEAR MISSES (closest first)"]
    for n in near[:MAX_NEAR]:
        L += [n["title"]] + ([n["who"]] if n.get("who") else []) + ["   ".join(f"{'✓' if n['checks'][k]['pass'] else '✗'} {CHECK_NAME[k]}" for k in CHECK_ORDER)]
        L += [f"- {k}: {v}" for k, v in gap_of(n)]
        if n.get("would_change"):
            L.append("Would change the call: " + n["would_change"])
        L.append("")
    if len(near) > MAX_NEAR:
        L += ["Also screened: " + "; ".join(f"{x['title']} ({x['passed']}/4)" for x in near[MAX_NEAR:]), ""]
    return L


def rec_email(o, muted, line, extra=""):
    return (f"<div style='background:#fff;border:1px solid {line};padding:10px 12px;margin:0 0 10px'>"
            + (f"<div style='font-size:13px;font-weight:bold;color:#b0162b'>{E(o['who'])}</div>" if o.get("who") else "")
            + f"<p style='margin:2px 0 4px;font-weight:bold;font-size:15px'>{E(o['heading'])}</p>{extra}"
            f"<p style='margin:0 0 8px'>{E(o.get('what', ''))}</p><table role='presentation' cellpadding='0' cellspacing='0' style='font-size:13.5px'>"
            + "".join(f"<tr><td style='font-weight:bold;padding:3px 12px 3px 0;vertical-align:top;white-space:nowrap'>{E(k)}</td><td style='padding:3px 0'>{_cell(v, True)}</td></tr>" for k, v in rec_rows(o))
            + "</table></div>")


def rec_html(o, extra=""):
    t = f'<a href="{E(o["url"])}" target="_blank" rel="noopener">{E(o["heading"])}</a>' if o.get("url") else E(o["heading"])
    who = f'<div class="rw">{E(o["who"])}</div>' if o.get("who") else ""
    return (f'<div class="rec">{who}<h5>{t}</h5>{extra}<p>{E(o.get("what", ""))}</p><dl>'
            + "".join(f"<dt>{E(k)}</dt><dd>{_cell(v)}</dd>" for k, v in rec_rows(o)) + "</dl></div>")


def opp_html(inn_unused=None, issue=None):
    m = innov_model(issue)
    out = [f'<section class="opp" id="opp"><h2>Innovation and partnering <span>{m["counts"]["recommended"] or "nothing"} to act on</span></h2>',
           f'<p class="tally">{E(tally(m))}</p>', f'<p class="rule">{CHECK_RULE}</p>']
    out.append('<h4 class="sub">Recommended</h4>')
    if not m["rec"]:
        out.append('<p class="none">Nothing this week. No paper passed all four checks.</p>')
    for o in m["rec"]:
        out.append(rec_html(o))
    if m["near"]:
        out.append(near_html(m["near"]))
    if m["skipped"]:
        out.append('<p class="more"><b>No commercial angle:</b> ' + E("; ".join(f"{x['title']} ({x['reason']})" for x in m["skipped"])) + ".</p>")
    elif m["skipped_text"]:
        out.append(f'<p class="more">{E(m["skipped_text"])}</p>')
    out.append("</section>")
    return "\n".join(out)


def render_web(issue, dashboard_url="", archive=None, logo_src="logo.png", archive_prefix="issues/"):
    n, ppl, nu, cross = stats(issue)
    parts = []
    for u in issue["units"]:
        if not u["items"]:
            continue
        parts.append(f'<h2>{E(u["unit"])} <span>{len(u["items"])}</span></h2>')
        for it in u["items"]:
            title = f'<a href="{E(it["url"])}" target="_blank" rel="noopener">{E(it["title"])}</a>' if it.get("url") else E(it["title"])
            parts.append(f'<div class="item"><div class="who">{who_html(it)}</div><h3>{title}</h3><p>{E(it["summary"])}</p><div class="src">{src_line(it)}</div></div>')
    if issue.get("innovation") is not None:
        parts.append(opp_html(issue=issue))
    if issue.get("also"):
        parts.append(f'<h2>{E(issue.get("also_title") or "Also published")}</h2><div class="also"><ul>' + "".join(f"<li>{E(x)}</li>" for x in issue["also"]) + "</ul></div>")
    arch = ""
    if archive:
        arch = '<div class="arch">All issues: ' + " · ".join(f'<a href="{archive_prefix}{E(a)}.html">{E(a)}</a>' for a in archive) + "</div>"
    dash = f'<a class="btn" href="{E(dashboard_url)}">Open the research dashboard</a>' if dashboard_url else ""
    if not n:
        lead = issue.get("lead") or "No new Faculty of Science outputs were indexed this week."
    else:
        lead = issue["lead"]
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
{gate_html(dashboard_url or "")}
<title>Science Weekly Digest</title>{FONTS}<style>{CSS}</style></head><body>
<div class="col"><article class="sheet" id="digest">
<div class="eyebrow"><i></i>Research digest</div>
<h1>New from Carleton Science</h1>
<div class="dates">{E(week_label(issue))} · issue {issue['issue']}</div>
<div class="prep">{PREPARED}</div>
<div class="stats"><div><b>{n}</b><span>new outputs this week</span></div><div><b>{ppl}</b><span>Faculty researchers</span></div><div><b>{nu}</b><span>units</span></div><div><b>{cross}</b><span>cross-unit paper{'s' if cross != 1 else ''}</span></div></div>
<p class="lead">{E(lead)}</p>
<div class="tools"><button class="btn" id="copy">Copy as email text</button>{dash}<span class="note" id="copy-note"></span></div>
{chr(10).join(parts)}
<div class="foot">{FOOT}</div>{arch}
</article></div>
<script>
document.getElementById("copy").onclick = async () => {{
  const txt = {json.dumps(render_text(issue, dashboard_url))};
  const note = document.getElementById("copy-note");
  try {{ await navigator.clipboard.writeText(txt); note.textContent = "Copied. Paste into an email."; }}
  catch {{ const ta = document.createElement("textarea"); ta.value = txt; ta.rows = 8; ta.style.width = "100%"; document.querySelector(".tools").after(ta); ta.select(); note.textContent = "Copy was blocked. Select the text below and copy it."; }}
}};
</script></body></html>"""


def render_text(issue, dashboard_url=""):
    L = [f"New from Carleton Science: {week_label(issue)} (issue {issue['issue']})", PREPARED, "", issue.get("lead", ""), ""]
    for u in issue["units"]:
        if not u["items"]:
            continue
        L.append(u["unit"].upper())
        for it in u["items"]:
            L += [it["title"], ", ".join(f"{n} ({x})" for n, x in it["who"]) + (f" {it['who_note']}" if it.get("who_note") else ""),
                  it["summary"], f"{it.get('url', '')}  {it.get('venue', '')}, {fmt_day(it['date'])}".strip(), ""]
    if issue.get("innovation") is not None:
        m = innov_model(issue)
        L += ["INNOVATION AND PARTNERING", tally(m), "", "RECOMMENDED"]
        if not m["rec"]:
            L.append("Nothing this week. No paper passed all four checks.")
        for o in m["rec"]:
            L += [o["heading"], o.get("who", ""), o.get("what", "")] + [f"{k}: {'; '.join(v) if isinstance(v, list) else v}" for k, v in rec_rows(o)] + [""]
        if m["near"]:
            L += near_text(m["near"])
        if m["skipped"]:
            L += ["No commercial angle: " + "; ".join(f"{x['title']} ({x['reason']})" for x in m["skipped"]), ""]
        elif m["skipped_text"]:
            L += [m["skipped_text"], ""]
    for x in issue.get("also") or []:
        L.append("- " + x)
    if dashboard_url:
        L += ["", "Dashboard: " + dashboard_url]
    L += ["", "Summaries written by Claude from abstracts; check the paper before quoting."]
    return "\n".join(L)


def render_email(issue, web_url="", dashboard_url="", logo_url=""):
    """Email-safe HTML: inline styles, no CSS variables, no scripts."""
    n, ppl, nu, cross = stats(issue)
    ink, muted, accent, line = "#15171c", "#6e7380", "#b0162b", "#e3e5e8"
    font = "font-family:Helvetica,Arial,sans-serif;"
    rows = []
    for u in issue["units"]:
        if not u["items"]:
            continue
        rows.append(f'<tr><td style="{font}font-size:12px;letter-spacing:1px;text-transform:uppercase;color:#4a4f5a;font-weight:bold;padding:24px 0 6px;border-bottom:2px solid {ink}">{E(u["unit"])}</td></tr>')
        for it in u["items"]:
            who = ", ".join(f'{E(nm)} <span style="color:{muted};font-weight:normal">{E(un)}</span>' for nm, un in it["who"])
            if it.get("who_note"):
                who += f' <span style="color:{muted};font-weight:normal">{E(it["who_note"])}</span>'
            t = f'<a href="{E(it["url"])}" style="color:{ink};text-decoration:none">{E(it["title"])}</a>' if it.get("url") else E(it["title"])
            rows.append(f'<tr><td style="padding:14px 0;border-bottom:1px solid {line}"><div style="{font}font-size:13px;font-weight:bold;color:{accent}">{who}</div>'
                        f'<div style="{font}font-size:16px;font-weight:bold;color:{ink};margin:4px 0 6px;line-height:1.35">{t}</div>'
                        f'<div style="font-family:Georgia,serif;font-size:15px;line-height:1.55;color:{ink}">{E(it["summary"])}</div>'
                        f'<div style="{font}font-size:12px;color:{muted};margin-top:6px">{src_line(it)}</div></td></tr>')
    if issue.get("innovation") is not None:
        m = innov_model(issue)
        green = "#1d6b3a"
        body = [f"<div style='font-family:Menlo,Consolas,monospace;font-size:12px;color:#4a4f5a;margin:0 0 6px'>{E(tally(m))}</div>",
                f"<div style='font-size:12.5px;color:{muted};margin:0 0 12px'>{CHECK_RULE}</div>",
                f"<div style='font-size:12px;letter-spacing:1px;text-transform:uppercase;color:#4a4f5a;font-weight:bold;margin:0 0 6px'>Recommended</div>"]
        if not m["rec"]:
            body.append("<p style='margin:0 0 6px'>Nothing this week. No paper passed all four checks.</p>")
        for o in m["rec"]:
            body.append(rec_email(o, muted, line))
        if m["near"]:
            body.append(near_email(m["near"], muted, accent, line))
        if m["skipped"]:
            body.append(f"<p style='margin:10px 0 0;color:{muted};font-size:12.5px'><b>No commercial angle:</b> {E('; '.join(x['title'] + ' (' + x['reason'] + ')' for x in m['skipped']))}.</p>")
        elif m["skipped_text"]:
            body.append(f"<p style='margin:10px 0 0;color:{muted};font-size:12.5px'>{E(m['skipped_text'])}</p>")
        rows.append(f'<tr><td style="padding:24px 0 0"><div style="{font}font-size:14px;line-height:1.55;color:{ink};background:#f3f4f6;border-left:3px solid {accent};padding:14px 16px">'
                    f'<div style="font-size:12px;letter-spacing:1px;text-transform:uppercase;color:#4a4f5a;font-weight:bold;margin-bottom:8px">Innovation and partnering</div>{"".join(body)}</div></td></tr>')
    if issue.get("also"):
        rows.append(f'<tr><td style="{font}font-size:12px;letter-spacing:1px;text-transform:uppercase;color:#4a4f5a;font-weight:bold;padding:24px 0 6px;border-bottom:2px solid {ink}">{E(issue.get("also_title") or "Also published")}</td></tr>')
        rows.append(f'<tr><td style="{font}font-size:14px;color:{ink};padding-top:8px"><ul style="padding-left:18px;margin:0">' + "".join(f"<li style='margin:0 0 8px'>{E(x)}</li>" for x in issue["also"]) + "</ul></td></tr>")
    links = " &nbsp;·&nbsp; ".join(x for x in [f'<a href="{E(web_url)}" style="color:{accent}">Read on the web</a>' if web_url else "",
                                                f'<a href="{E(dashboard_url)}" style="color:{accent}">Open the dashboard</a>' if dashboard_url else ""] if x)
    return f"""<!doctype html><html><body style="margin:0;background:#f3f4f6">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:#f3f4f6"><tr><td align="center" style="padding:20px 10px">
<table role="presentation" width="640" cellpadding="0" cellspacing="0" style="max-width:640px;width:100%;background:#ffffff;border:1px solid #d9dce1"><tr><td style="padding:28px">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0">
<tr><td style="{font}font-size:11px;letter-spacing:1px;text-transform:uppercase;color:{muted}">Research digest</td></tr>
<tr><td style="{font}font-size:30px;font-weight:bold;color:{ink};padding:6px 0 4px">New from Carleton Science</td></tr>
<tr><td style="{font}font-size:13px;color:#4a4f5a">{E(week_label(issue))} · issue {issue['issue']}<br>{PREPARED}</td></tr>
<tr><td style="{font}font-size:13px;color:{ink};padding:14px 0;border-bottom:1px solid {line};border-top:1px solid {line};margin-top:12px"><b>{n}</b> new outputs &nbsp;·&nbsp; <b>{ppl}</b> researchers &nbsp;·&nbsp; <b>{nu}</b> units &nbsp;·&nbsp; <b>{cross}</b> cross-unit</td></tr>
<tr><td style="font-family:Georgia,serif;font-size:16px;line-height:1.6;color:{ink};padding:16px 0 0">{E(issue.get('lead', ''))}</td></tr>
{f'<tr><td style="{font}font-size:13px;padding:12px 0 0">{links}</td></tr>' if links else ''}
{''.join(rows)}
<tr><td style="{font}font-size:12px;color:{muted};padding:24px 0 0;border-top:1px solid {line}">{FOOT}</td></tr>
</table></td></tr></table></td></tr></table></body></html>"""


if __name__ == "__main__":
    iss = json.load(open(sys.argv[1], encoding="utf-8"))
    open(sys.argv[2], "w", encoding="utf-8").write(render_web(iss))


# ---------------------------------------------------------------- quarterly partnership brief
BRIEF_FOOT = ("Each quarter the research lines with the strongest industry signals (companies that co-author, cite or fund the work, recent momentum, "
              "preprints with an open patent clock) are screened on four fixed checks: real market, verified partner, Carleton-led, and enough evidence. "
              "Only lines that pass all four are listed. Written by Claude from OpenAlex and public company information; verify before acting.")


def _chips(sig):
    out = []
    if sig.get("citers"):
        out.append(f"cited by {', '.join(sig['citers'][:3])}")
    if sig.get("companies"):
        out.append(f"co-authored with {', '.join(sig['companies'][:3])}")
    if sig.get("industry"):
        out.append(", ".join(sig["industry"][:2]))
    for p in (sig.get("preprints") or [])[:1]:
        out.append(f"preprint, patent clock to {p['grace_until']}")
    if sig.get("patents"):
        out.append(f"{len(sig['patents'])} Carleton patent(s)")
    if sig.get("n"):
        out.append(f"{sig['n']} papers in 3 years, {sig.get('recent', 0)} in the last 2")
    return out


def brief_model(b):
    rec = []
    for o in b.get("picks") or []:
        sig = o.get("signals") or {}
        rec.append(dict(o, who=f"{sig.get('name', '')} ({', '.join(sig.get('units') or [])})" if sig.get("name") else "", sig=" · ".join(_chips(sig))))
    near = sorted((norm_near(n) for n in b.get("near_misses") or []), key=lambda x: -x["passed"])
    n = b.get("screened", 0)
    tally_ = f"Screened {n} research line{'s' if n != 1 else ''} · {len(rec)} recommended · {len(near)} near miss{'es' if len(near) != 1 else ''}"
    return rec, near, tally_


BRIEF_RULE = CHECK_RULE.replace("A paper is recommended", "A research line is recommended")


def render_brief_web(b, quarters, logo_src="../logo.png", prefix=""):
    rec, near, tally_ = brief_model(b)
    body = [f'<p class="tally">{E(tally_)}</p>', f'<p class="rule">{BRIEF_RULE}</p>', '<h4 class="sub">Recommended</h4>']
    if not rec:
        body.append('<p class="none">Nothing this quarter. No research line passed all four checks.</p>')
    body += [rec_html(o, f'<p class="sig">{E(o["sig"])}</p>' if o.get("sig") else "") for o in rec]
    if near:
        body.append(near_html(near))
    arch = ('<div class="arch">All briefs: ' + " · ".join(f'<a href="{prefix}{E(q)}.html">{E(q)}</a>' for q in quarters) + "</div>") if quarters else ""
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
{gate_html("../")}
<title>Partnership Brief</title>{FONTS}<style>{CSS}</style></head><body>
<div class="col"><article class="sheet">
<div class="eyebrow"><i></i>Quarterly partnership brief</div>
<h1>Partnership and IP opportunities</h1>
<div class="dates">{E(b.get('quarter', ''))} · prepared {E(b.get('date', ''))}</div>
<div class="prep">{PREPARED}</div>
<section class="opp"><h2>This quarter <span>{len(rec) or "nothing"} to act on</span></h2>
{"".join(body)}
</section>
<div class="foot">{BRIEF_FOOT}</div>{arch}
</article></div></body></html>"""


def render_brief_email(b, web_url="", logo_url=""):
    ink, muted, accent, line = "#15171c", "#6e7380", "#b0162b", "#e3e5e8"
    font = "font-family:Helvetica,Arial,sans-serif;"
    rec, near, tally_ = brief_model(b)
    body = [f"<div style='font-family:Menlo,Consolas,monospace;font-size:12px;color:#4a4f5a;margin:0 0 6px'>{E(tally_)}</div>",
            f"<div style='font-size:12.5px;color:{muted};margin:0 0 12px'>{BRIEF_RULE}</div>",
            "<div style='font-size:12px;letter-spacing:1px;text-transform:uppercase;color:#4a4f5a;font-weight:bold;margin:0 0 6px'>Recommended</div>"]
    if not rec:
        body.append("<p style='margin:0 0 6px'>Nothing this quarter. No research line passed all four checks.</p>")
    body += [rec_email(o, muted, line, f"<div style='font-size:12px;color:{muted};margin:0 0 6px'>{E(o['sig'])}</div>" if o.get("sig") else "") for o in rec]
    if near:
        body.append(near_email(near, muted, accent, line))
    return f"""<!doctype html><html><body style="margin:0;background:#f3f4f6"><table role="presentation" width="100%" cellpadding="0" cellspacing="0"><tr><td align="center" style="padding:20px 10px">
<table role="presentation" width="640" cellpadding="0" cellspacing="0" style="max-width:640px;width:100%;background:#fff;border:1px solid #d9dce1"><tr><td style="padding:28px">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0">
<tr><td style="{font}font-size:11px;letter-spacing:1px;text-transform:uppercase;color:{muted}">Quarterly partnership brief</td></tr>
<tr><td style="{font}font-size:28px;font-weight:bold;color:{ink};padding:6px 0 4px">Partnership and IP opportunities</td></tr>
<tr><td style="{font}font-size:13px;color:#4a4f5a">{E(b.get('quarter', ''))}<br>{PREPARED}</td></tr>
{f'<tr><td style="{font}font-size:13px;padding:10px 0 0"><a href="{E(web_url)}" style="color:{accent}">Read on the web</a></td></tr>' if web_url else ''}
<tr><td style="padding:16px 0 0"><div style="{font}font-size:14px;line-height:1.55;color:{ink};background:#f3f4f6;border-left:3px solid {accent};padding:14px 16px">{"".join(body)}</div></td></tr>
<tr><td style="{font}font-size:12px;color:{muted};padding:20px 0 0">{BRIEF_FOOT}</td></tr>
</table></td></tr></table></td></tr></table></body></html>"""
