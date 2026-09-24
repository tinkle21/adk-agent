# AU Investment Property Research Agent

A [Google ADK](https://google.github.io/adk-docs/) agent that looks for Australian
investment properties and runs a scan automatically every 2 days.

## What counts as a good investment

A listing is a **match** only if all three rules pass:

| # | Rule | Default |
|---|------|---------|
| 1 | Listed for sale on **realestate.com.au** | locations and filters in `config.toml` |
| 2 | Asking price is close to the **property.com.au estimated value**, and that estimate has **high confidence** | within ±5% |
| 3 | Estimated **rent covers the loan repayment**. The loan is the asking price less a 20% deposit, at 6.1% p.a. | 30-year principal & interest |

Example: a $500,000 property means a $400,000 loan. At 6.1% over 30 years the
repayment is **$2,424/month**, so it needs about **$559/week** rent (a 5.82% gross
yield) to pass rule 3.

Listings that fail just one rule by a small margin are reported as **near misses**.
Listings with no price ("Contact agent", "Auction") are skipped, because there is
nothing to compare with the estimate.

All thresholds live in [`config.toml`](config.toml): locations, price band, bedrooms,
tolerance, accepted confidence levels, deposit, rate, term and minimum rent coverage.

## How it works

```
realestate.com.au search pages ──► listings ──► property.com.au profile page ──► screener ──► reports/
                                                 (value, confidence, rent)       (3 rules)    YYYY-MM-DD.md/.json
```

- `property_agent/sources/realestate.py`: reads listings from the JSON that
  realestate.com.au embeds in its search pages.
- `property_agent/sources/property_com_au.py`: finds the property.com.au page for each
  address and reads the estimated value, confidence and rental estimate.
- `property_agent/screener.py`: applies the three rules.
- `property_agent/scan.py`: runs one full scan and writes the report. The scheduled job
  runs this and needs no LLM.
- `property_agent/agent.py`: the ADK agent (`root_agent`) for asking questions
  interactively.

Estimates are cached for 14 days in `data/valuation_cache.json` so each scan makes
fewer requests. Listings not seen in earlier scans are marked 🆕 in the report.

## ⚠️ Getting past bot protection (required for live scans)

realestate.com.au and property.com.au both block plain HTTP clients (they return
**HTTP 429**). For live scans, route requests through a scraping/unblocker service
that renders pages from Australian IPs, such as ScraperAPI, ZenRows, Bright Data or
Oxylabs. Set `FETCH_URL_TEMPLATE`, where `{url}` stands for the target page:

```bash
FETCH_URL_TEMPLATE='https://api.scraperapi.com/?api_key=KEY&render=true&country_code=au&url={url}'
```

Without it, the scan reports the block under "Problems during the scan" instead
of results.

Check each site's terms of use before scraping. For a durable setup, consider
licensed data instead: PropTrack (the engine behind property.com.au estimates) and
Domain both sell listing/AVM APIs. The sources are small classes, so you can swap
one in without touching the screener.

## Setup

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env        # add GOOGLE_API_KEY and FETCH_URL_TEMPLATE
```

### Run a scan

```bash
set -a; source .env; set +a
python -m property_agent.scan                                     # live
python -m property_agent.scan --offline examples/sample_listings.json --no-write   # demo, no network
```

### Talk to the agent

```bash
adk web          # browser UI, pick "property_agent"
adk run property_agent
```

Example prompts:
- "Run a scan of Ipswich and Logan and show me the matches."
- "Check https://www.realestate.com.au/property-house-qld-…"
- "Asking $520k, estimate $530k high confidence, rent $610/week. Does it pass?"
- "What rent do I need for a $650k place?"

## Every-2-days schedule

`.github/workflows/property-scan.yml` runs on GitHub Actions. It triggers daily at
21:00 UTC (7am AEST) and skips every other day, so it runs exactly every 48 hours.
Each run:

1. runs `python -m property_agent.scan`
2. commits `reports/` and `data/` back to the repo (the report history, the
   seen-listings record and the estimate cache)
3. shows the report on the run's summary page and uploads it as an artifact

Setup: add a repository secret `FETCH_URL_TEMPLATE` (Settings → Secrets and variables →
Actions). Use **Run workflow** to trigger a scan on demand.

Running it yourself instead? A cron entry works too:

```cron
0 7 */2 * * cd /path/to/adk-agent && .venv/bin/python -m property_agent.scan
```

## Tests

```bash
python -m pytest -q
```

## Caveats

- Automated estimates can be well off for unusual properties. "High confidence" is
  PropTrack's own rating.
- Rule 3 compares gross rent with the repayment only. It excludes rates, strata,
  insurance, property management, maintenance, vacancy, stamp duty and LMI.
- This is a research tool, not financial advice.
