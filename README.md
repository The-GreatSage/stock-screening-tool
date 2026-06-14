# Stock Screening Tool

A local stock screening web app that evaluates a ticker against a configurable investing checklist.

The first version is intentionally small:

- A Python standard-library web server
- A browser UI for entering a ticker
- A rule engine that scores quantitative filters
- Optional `yfinance` support when installed
- A Yahoo Finance public endpoint fallback for basic quote/profile data

This project is for research support only. It is not financial advice.

## Run

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python backend/app.py
```

Then open:

```text
http://127.0.0.1:8000
```

## Deploy To Render

The repository includes a `render.yaml` Blueprint for a free Render web
service.

1. In Render, create a new Blueprint.
2. Connect the private GitHub repository:
   `The-GreatSage/stock-screening-tool`
3. Render will use:
   - Build command: `pip install -r requirements.txt`
   - Start command: `python backend/app.py`
   - Health check: `/health`
4. Confirm the Blueprint to begin the first deployment.

Render supplies the public `$PORT`; the app binds to `0.0.0.0` when deployed.

Yahoo may restrict requests from shared cloud-hosting IP addresses. When that
happens, the app returns a partial evaluation with unavailable filters marked
`Unknown` instead of failing the entire request. A licensed market-data API is
recommended for reliable production use.

## Optional Data Dependency

For richer company fundamentals, install:

```bash
.venv/bin/python -m pip install yfinance
```

The app still starts without `yfinance`, but more filters will be marked as `Unknown`.

## Current Rule Coverage

Included in the current screen:

- ROIC >= 15%
- Cash buyback
- Profit margin >= 15% or operating margin >= 10%
- Earnings threshold >= $100M quarterly or >= $400M annually
- P/E < 15 or PEG < 1 or PEGY < 1
- Market cap between $100M and $7B, preferred above $200M
- P/E 40-50 end-of-run warning
- Debt-to-equity below 0.5
- Year-over-year revenue growth of 15-20%
- Insider ownership above 5%
- Margin shrinking while revenue is growing red flag
- Recent cluster purchase by multiple insiders
- Constant growth in revenue and earnings
- Strategic or major institutional investors with sizable positions

ROIC uses `NOPAT / average beginning-and-ending invested capital`. NOPAT uses
operating income after the latest effective tax rate. When Yahoo's invested
capital row is unavailable, invested capital is derived from debt, stockholders'
equity, and cash.
