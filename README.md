# Carleton Science Research

A research dashboard and weekly publication digest for Carleton University's Faculty of Science.
Prepared by the Associate Dean of Research, International and Innovation.

- **Dashboard:** https://biggarlab.github.io/carleton-science-research/
- **Latest digest:** https://biggarlab.github.io/carleton-science-research/digest/

Every Monday a GitHub Action pulls new outputs for everyone in `config/roster.csv` from OpenAlex, rebuilds the dashboard data, asks Claude for plain-language summaries and an innovation and partnering screen, publishes the digest and emails it.

This is a tool for discovery, not assessment. Counts come from OpenAlex and miss some outputs.

## What's where

| Path | What it is |
|---|---|
| `docs/` | The website (GitHub Pages serves this folder) |
| `docs/index.html` | The dashboard |
| `docs/data.json` | Publication data, rebuilt weekly |
| `docs/digest/` | Latest digest, plus `issues/` archive |
| `config/roster.csv` | Faculty list: edit this when people join or leave |
| `config/innovation_criteria.md` | Rules for the innovation section and the quarterly brief |
| `config/cv_signals.example.csv` | Format for adding CV data (grants, theses, patents) |
| `scripts/signals.py` | Partnership and IP signals |
| `docs/signals.json` | Ranked research lines, rebuilt weekly |
| `docs/brief/` | Quarterly partnership briefs |
| `config/settings.json` | Site address and Claude model |
| `scripts/update.py` | The weekly job |
| `state/` | Which papers have already been in a digest, and each issue's content |
| `worker/worker.js` | Optional relay that turns on Ask AI on the public site |

## One-time setup

### 1. Turn on the website
Repo **Settings → Pages**. Under *Build and deployment*, choose **Deploy from a branch**, branch `main`, folder `/docs`, and save. After a minute the site is live at the address above.

### 2. Add the keys as encrypted secrets
Repo **Settings → Secrets and variables → Actions → New repository secret**. Add each of these. Paste keys only here, never into chats, emails or files.

| Name | Value |
|---|---|
| `ANTHROPIC_API_KEY` | Claude API key from platform.claude.com → API Keys |
| `OPENALEX_API_KEY` | Free key from openalex.org/settings/api |
| `RESEND_API_KEY` | Free key from resend.com → API Keys |
| `DIGEST_TO` | The address the digest goes to (for Resend's free sender, use the same address you signed up to Resend with) |

To send from an Outlook or Gmail account instead of Resend, skip `RESEND_API_KEY` and add `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASS` (Gmail: smtp.gmail.com, 587, your address, an app password).

### 3. Run it once to test
**Actions → Weekly research update → Run workflow.** Untick *Send the email* for a dry run, or leave it ticked to get an email. It takes about 10 to 20 minutes. After that it runs by itself every Monday morning.

## Getting a Claude API key
1. Sign in at **platform.claude.com** (this is separate from a Claude chat subscription).
2. **Settings → Billing:** add a card and buy a small amount of prepaid credit (US$10 lasts months).
3. **Settings → Limits:** set a monthly spend limit, for example US$20.
4. **API Keys → Create Key**, name it `carleton-science-digest`, copy it once, and paste it into the GitHub secret above.

Expected cost: the weekly digest is a few cents a week, plus about one cent per web search in the innovation screen. The Assistant tab is about 5 to 15 cents a question.

## Keeping the roster current
Edit `config/roster.csv` on GitHub (click the file, then the pencil). To add someone, add a row with name, `sort_name` as "Last, First", units separated by semicolons, rank, stream and roles. Leave `openalex_ids` blank; the next run looks them up and writes a note saying "please check". Adding their ORCID makes the match exact. To remove someone, delete the row.

## Partnership signals and the quarterly brief
The **Partnership signals** tab ranks *research lines* (one researcher working on one topic, two or more papers in three years) by evidence that industry already cares:

| Signal | Source | Needs |
|---|---|---|
| Companies on the author list | OpenAlex | nothing extra |
| Companies whose papers cite our work | OpenAlex | nothing extra |
| Industry funding (Mitacs, NSERC Alliance/CRD/Engage, OCI, company funders) | OpenAlex funders and award IDs | nothing extra |
| Preprints in the last 12 months (patent grace period still open) | OpenAlex | nothing extra |
| NSERC grants: partner organizations, co-researchers, area of application and the plain-language summary of planned work | NSERC awards database (nserc-crsng.canada.ca) | nothing extra; one search per person, cached in `state/nserc_cache.json` and refreshed monthly |
| Carleton patents, and companies patenting in a topic | USPTO PatentSearch (US) and/or EPO Open Patent Services (worldwide, incl. Canada and PCT) | free: a USPTO key from account.uspto.gov/api-manager as secret `PATENTSVIEW_API_KEY`; and/or an EPO app from developers.epo.org as secrets `EPO_OPS_KEY` and `EPO_OPS_SECRET` |
| Grants, theses, patents from CVs | `config/cv_signals.csv` | your CV dataset, in the format of `config/cv_signals.example.csv` |

Industry pull drives the ranking; paper volume only breaks ties, so prolific publishers don't crowd out real signals. The weekly innovation screen also sees these signals for each new paper.

**Quarterly brief.** On the first Monday of January, April, July and October the job takes the 12 strongest lines, has Claude run the same four checks (market, verified partner, Carleton-led, enough evidence) with web search, keeps only lines that pass all four (at most three), and emails a short brief. It's also at `/brief/` on the site. To make one now: **Actions → Weekly research update → Run workflow**, tick *Also make the quarterly partnership brief now*. Cost is roughly 50 cents to a dollar per brief.

## The research assistant (AI chat)
The **Assistant** tab is a chat that searches the Faculty publication data and, when you allow it, the web. Use it to match researchers to an industry partner, build a team for a grant call, prep for a meeting, or find committee members. Follow-up questions keep the conversation's context.

On the public site it uses **your own Claude API key, saved in your browser only**:
1. Open the dashboard, go to **Assistant**, paste your key (from platform.claude.com → API Keys) and click **Save key**.
2. The key is sent only to Anthropic. It is never in this repo, the website code, or GitHub. Other visitors see a "connect your key" box and can't use yours.
3. Untick *Remember on this device* on a shared computer; the key is then forgotten when the tab closes. **Forget key** removes it at any time.

Each question costs roughly 5 to 15 cents (Sonnet, with a few web searches). The spending limit you set on platform.claude.com caps the total.

Optional alternative: to let colleagues use the assistant without their own key, deploy `worker/worker.js` as a Cloudflare Worker holding the key, then put its URL in `docs/index.html` on the line `const AI_ENDPOINT = "";`.

## Running it yourself
```
python scripts/update.py --no-email      # full run without sending email
python scripts/update.py --render-only   # rebuild digest pages from saved issues, no network
```
