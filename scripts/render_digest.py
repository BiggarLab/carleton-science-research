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

PREPARED = "Prepared by the Associate Dean of Research, International and Innovation"
E = lambda s: html.escape(str(s or ""), quote=True)


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
        "so check the paper and the company before acting. The innovation section only appears when a paper has a plausible market "
        "and a named partner; most weeks it will be empty. Papers are matched to the Faculty list using OpenAlex, which can miss outputs "
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


TIER = {"act": "Act on", "conversation": "Worth a conversation"}


def opp_html(inn):
    ops = inn.get("opportunities") or []
    act = sum(1 for o in ops if o.get("tier", "act") == "act")
    conv = len(ops) - act
    count = f"{act} opportunit{'y' if act == 1 else 'ies'} this week" if act else "nothing this week"
    out = [f'<section class="opp" id="opp"><h2>Innovation and partnering <span>{count}</span></h2>']
    if not ops:
        out.append("<p>Nothing this week cleared the bar for a licensing or partnership conversation.</p>")
    for o in ops:
        tier = o.get("tier", "act")
        out.append(f'<h4>{E(o["heading"])}</h4>')
        out.append(f'<p><span class="k">What.</span> {E(o["what"])}</p>')
        out.append(f'<p><span class="k">Why there is market fit.</span> {E(o["market_fit"])}</p>')
        if o.get("partners"):
            out.append('<p><span class="k">Who to approach.</span></p><ul>')
            for p in o["partners"]:
                out.append(f"<li><b>{E(p['name'])}</b> ({E(p['location'])}). {E(p['why'])}</li>")
            out.append("</ul>")
        if o.get("blocker"):
            out.append(f'<p><span class="k">What holds it back.</span> {E(o["blocker"])}</p>')
        out.append(f'<p><span class="k">Suggested next step.</span> {E(o["next_step"])}</p>')
        if o.get("licensing_note"):
            out.append(f'<p><span class="k">Route.</span> {E(o["licensing_note"])}</p>')
    if inn.get("screened"):
        out.append(f'<p class="screened">{E(inn["screened"])}</p>')
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
        parts.append(opp_html(issue["innovation"]))
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
<title>Science Weekly Digest</title>{FONTS}<style>{CSS}</style></head><body>
<div class="col"><article class="sheet" id="digest">
<img class="logo" src="{E(logo_src)}" alt="Carleton University, Faculty of Science" width="800" height="297">
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
    inn = issue.get("innovation")
    if inn is not None:
        L.append("INNOVATION AND PARTNERING")
        if not inn.get("opportunities"):
            L.append("Nothing this week cleared the bar.")
        for o in inn.get("opportunities") or []:
            L += [o["heading"], "What: " + o["what"], "Market fit: " + o["market_fit"]]
            if o.get("blocker"):
                L.append("What holds it back: " + o["blocker"])
            L += [f"- {p['name']} ({p['location']}): {p['why']}" for p in o.get("partners", [])]
            L += ["Next step: " + o["next_step"]] + (["Route: " + o["licensing_note"]] if o.get("licensing_note") else []) + [""]
        if inn.get("screened"):
            L += [inn["screened"], ""]
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
    inn = issue.get("innovation")
    if inn is not None:
        body = []
        ops = inn.get("opportunities") or []
        if not ops:
            body.append("<p style='margin:0'>Nothing this week cleared the bar for a real licensing or partnership opportunity.</p>")
        for o in ops:
            tier = o.get("tier", "act")
            pill = f"<span style='display:inline-block;font-size:11px;padding:1px 6px;border-radius:3px;margin-right:6px;{'background:#b0162b;color:#fff' if tier == 'act' else 'background:#f7e3e6;color:#15171c'}'>{TIER.get(tier, '')}</span>"
            body.append(f"<p style='margin:0 0 6px;font-weight:bold;font-size:15px'>{E(o['heading'])}</p>")
            if o.get("blocker"):
                body.append(f"<p style='margin:0 0 8px'><b>What holds it back.</b> {E(o['blocker'])}</p>")
            for k, lab in (("what", "What."), ("market_fit", "Why there is market fit.")):
                body.append(f"<p style='margin:0 0 8px'><b>{lab}</b> {E(o[k])}</p>")
            if o.get("partners"):
                body.append("<p style='margin:0 0 4px'><b>Who to approach.</b></p><ul style='margin:0 0 8px;padding-left:18px'>" + "".join(f"<li style='margin:0 0 6px'><b>{E(p['name'])}</b> ({E(p['location'])}). {E(p['why'])}</li>" for p in o["partners"]) + "</ul>")
            body.append(f"<p style='margin:0 0 8px'><b>Suggested next step.</b> {E(o['next_step'])}</p>")
            if o.get("licensing_note"):
                body.append(f"<p style='margin:0 0 8px'><b>Route.</b> {E(o['licensing_note'])}</p>")
        if inn.get("screened"):
            body.append(f"<p style='margin:10px 0 0;color:{muted};font-size:12.5px'>{E(inn['screened'])}</p>")
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
{f'<tr><td style="padding:0 0 14px"><img src="{E(logo_url)}" width="200" alt="Carleton University, Faculty of Science" style="display:block;width:200px;height:auto"></td></tr>' if logo_url else ''}
<tr><td style="{font}font-size:11px;letter-spacing:1px;text-transform:uppercase;color:{muted}">Carleton University · Faculty of Science · Research digest</td></tr>
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
