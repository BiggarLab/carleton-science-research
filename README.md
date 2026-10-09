# Carleton Science Research

A research dashboard and weekly publication digest for Carleton University's Faculty of Science.
An independent tool built from public data. It is not an official Carleton University site or publication.

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
| `worker/worker.js` | Relay that runs the shared research assistant on one key (OpenAI or Claude) |
| `docs/ai.json` | Address of that relay; empty turns the shared assistant off |

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
| Carleton patents, and companies patenting in a topic | USPTO Open Data Portal (US applications and patents) and/or EPO Open Patent Services (worldwide, incl. Canada and PCT) | free: a USPTO Open Data Portal key (data.uspto.gov, MyUSPTO) as secret `PATENTSVIEW_API_KEY`; and/or an EPO app from developers.epo.org as secrets `EPO_OPS_KEY` and `EPO_OPS_SECRET` |
| Grants, theses, patents from CVs | `config/cv_signals.csv` | your CV dataset, in the format of `config/cv_signals.example.csv` |

Industry pull drives the ranking; paper volume only breaks ties, so prolific publishers don't crowd out real signals. The weekly innovation screen also sees these signals for each new paper.

**Quarterly brief.** On the first Monday of January, April, July and October the job takes the 12 strongest lines, has Claude run the same four checks (market, verified partner, Carleton-led, enough evidence) with web search, keeps only lines that pass all four (at most three), and emails a short brief. It's also at `/brief/` on the site. To make one now: **Actions → Weekly research update → Run workflow**, tick *Also make the quarterly partnership brief now*. Cost is roughly 50 cents to a dollar per brief.

## The research assistant (AI chat)
The **Assistant** tab is a chat that searches the Faculty publication data and, when allowed, the web. Use it to match researchers to an industry partner, build a team for a grant call, prep for a meeting, or find committee members. Follow-up questions keep the conversation's context.

### Shared assistant (one key, held by you)
A small Cloudflare Worker (`worker/worker.js`) holds one AI key and relays questions. The key never reaches the website, the repo or anyone's browser. Visitors type a passcode once; there's a daily question cap.

1. Sign up free at **dash.cloudflare.com**. Go to **Compute (Workers) → Create → Hello World → Deploy**. Name it `carleton-science-ai`.
2. Click **Edit code**, delete everything, paste all of `worker/worker.js`, click **Deploy**.
3. Worker **Settings → Variables and Secrets → Add**:

| Name | Type | Value |
|---|---|---|
| `OPENAI_API_KEY` | Secret | your OpenAI key (platform.openai.com → API keys; set a monthly budget under Limits) |
| `PASSCODE` | Secret | a passcode you'll give colleagues |
| `PROVIDER` | Text | `openai` (or `anthropic`, with `ANTHROPIC_API_KEY` instead) |
| `MODEL` | Text | `gpt-5-mini` (cheap, good) or `gpt-5` (deeper) |
| `ALLOWED_ORIGIN` | Text | `https://biggarlab.github.io` |
| `OPENAI_BASE_URL` | Text | Azure only: your endpoint, e.g. `https://<name>.services.ai.azure.com/openai/v1` (then `MODEL` is the deployment name) |
| `RCS_API_KEY` | Secret | optional: a Carleton RCS LLM key (request through the ITS service desk). Adds "Carleton RCS" as a second choice in the chat settings |
| `RCS_MODEL` | Text | optional, default `gpt-oss:120b` |

4. Optional daily cap: **Storage & Databases → KV → Create** a namespace `LIMITS`; then Worker **Settings → Bindings → Add → KV namespace**, variable name `LIMITS`. Default cap is 200 questions a day; change with a text variable `DAILY_LIMIT`.
5. Copy the Worker's address (like `https://carleton-science-ai.<you>.workers.dev`). In this repo, edit `docs/ai.json` to `{"endpoint": "https://carleton-science-ai.<you>.workers.dev"}` and commit. The site picks it up within a minute.

To change the key, model or passcode later, edit them in Cloudflare; nothing in the repo changes. To switch the assistant off, set `docs/ai.json` back to `{"endpoint": ""}`.

Cost with `gpt-5-mini`: about 1 to 3 cents a question; web searches add about 1 cent each. The weekly digest still uses Claude (`ANTHROPIC_API_KEY` in GitHub secrets).

### Personal key (no Worker)
With `docs/ai.json` empty, the Assistant asks for a Claude API key, kept only in that browser and sent only to Anthropic. Fine for one person; use the Worker for colleagues.

## University-wide view
**https://biggarlab.github.io/carleton-science-research/university/** shows research strengths across all of Carleton, built every Monday by the *University-wide update* action (`scripts/university.py`, about 20 to 40 minutes).

**Who counts as a researcher.** There is no university-wide faculty list, so each person carries the evidence that put them on the page:
- **Science roster**: `config/roster.csv`, exact.
- **Department website**: listed as professor, instructor, lecturer or research chair on a carleton.ca department site (adjuncts, emeriti, contract instructors and students are left out).
- **NSERC or SSHRC grant**: held a research grant at Carleton in the last six years (scholarships and fellowships are left out) and publishes from Carleton in OpenAlex.

Departments, their Faculty and the websites read are in `config/university_units.json`; edit it if a unit is missing or misfiled. Outputs from people who are not identified still count toward strengths, attributed to a department from the affiliation text on the paper where possible.

**Strength rules** (shown on the page):
- **Established**: 30+ outputs (120+ for broad areas), at least 1.5x the world share of output in the topic (1.2x for broad areas), mean FWCI of 1.0 or more, and 3+ researchers.
- **Emerging**: real volume in the latest two full years, publishing at least 1.5x faster per year than before, with 2+ researchers.
- **Cross-Faculty**: researchers from two or more Faculties, or many outputs co-authored across Faculties.

To run it now: **Actions → University-wide update → Run workflow**.

## Password screen
The pages show a simple password box. It keeps casual visitors out but is cosmetic: the data files and this repo stay public.
To set or change the password: add a repository secret `SITE_PASSWORD`, then **Actions → Set site password → Run workflow**. To remove it, delete the secret and run the action again. Each browser asks once.

## Running it yourself
```
python scripts/update.py --no-email      # full run without sending email
python scripts/update.py --render-only   # rebuild digest pages from saved issues, no network
```
