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
| `config/innovation_criteria.md` | Rules for the innovation and partnering section |
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

Expected cost: the weekly digest is a few cents a week, plus about one cent per web search in the innovation screen. Ask AI on the public site is about 5 to 10 cents a question if you turn it on.

## Keeping the roster current
Edit `config/roster.csv` on GitHub (click the file, then the pencil). To add someone, add a row with name, `sort_name` as "Last, First", units separated by semicolons, rank, stream and roles. Leave `openalex_ids` blank; the next run looks them up and writes a note saying "please check". Adding their ORCID makes the match exact. To remove someone, delete the row.

## Optional: Ask AI on the public site
Inside Claude the dashboard's Ask AI uses each viewer's own Claude account. On the public site it needs a small relay so your API key stays hidden:
1. Create a free Cloudflare account, then **Workers → Create → Hello World**, and replace its code with `worker/worker.js`.
2. In the Worker's **Settings → Variables**, add the secret `ANTHROPIC_API_KEY` and the variable `ALLOWED_ORIGIN` = `https://biggarlab.github.io`.
3. Optional daily cap: create a KV namespace, bind it as `LIMITS`, and set `DAILY_LIMIT` (default 300).
4. Put the Worker's URL in `docs/index.html` on the line `const AI_ENDPOINT = "";` and commit.

## Running it yourself
```
python scripts/update.py --no-email      # full run without sending email
python scripts/update.py --render-only   # rebuild digest pages from saved issues, no network
```
