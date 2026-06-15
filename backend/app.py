from __future__ import annotations

import json
import os
import sys
from dataclasses import asdict, is_dataclass
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

BASE_DIR = Path(__file__).resolve().parents[1]
FRONTEND_DIR = BASE_DIR / "frontend"
sys.path.insert(0, str(Path(__file__).resolve().parent))

from data_sources.provider import fetch_company_metrics
from data_sources.provider import _fmp_api_key, _sec_user_agent
from data_sources.market_client import fetch_market_overview
from data_sources.performance_client import fetch_relative_performance
from evaluator import evaluate_company


class StockScreeningHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(FRONTEND_DIR), **kwargs)

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path == "/api/evaluate":
            self.handle_evaluate(parsed)
            return
        if parsed.path == "/api/markets":
            self.handle_markets()
            return
        if parsed.path == "/api/performance":
            self.handle_performance(parsed)
            return
        if parsed.path == "/health":
            self.write_json(
                {
                    "ok": True,
                    "fmp_configured": bool(_fmp_api_key()),
                    "sec_configured": bool(_sec_user_agent()),
                }
            )
            return
        super().do_GET()

    def handle_evaluate(self, parsed):
        ticker = parse_qs(parsed.query).get("ticker", [""])[0].strip().upper()
        if not ticker:
            self.write_json({"error": "Ticker is required"}, status=400)
            return
        try:
            metrics = fetch_company_metrics(ticker)
            evaluation = evaluate_company(metrics)
            self.write_json(evaluation)
        except Exception as exc:
            self.write_json({"error": str(exc)}, status=500)

    def handle_markets(self):
        try:
            self.write_json(fetch_market_overview())
        except Exception as exc:
            self.write_json({"error": str(exc), "markets": []}, status=500)

    def handle_performance(self, parsed):
        query = parse_qs(parsed.query)
        ticker = query.get("ticker", [""])[0].strip().upper()
        if not ticker:
            self.write_json({"error": "Ticker is required"}, status=400)
            return
        try:
            self.write_json(
                fetch_relative_performance(
                    ticker,
                    query.get("sector", [""])[0].strip(),
                    query.get("industry", [""])[0].strip(),
                )
            )
        except Exception as exc:
            self.write_json({"error": str(exc), "series": []}, status=500)

    def write_json(self, payload, status=200):
        body = json.dumps(to_jsonable(payload), indent=2).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def to_jsonable(value):
    if is_dataclass(value):
        return to_jsonable(asdict(value))
    if isinstance(value, dict):
        return {key: to_jsonable(item) for key, item in value.items()}
    if isinstance(value, list):
        return [to_jsonable(item) for item in value]
    return value


def run(host=None, port=None):
    host = host or os.environ.get("HOST", "127.0.0.1")
    port = port or int(os.environ.get("PORT", "8000"))
    server = ThreadingHTTPServer((host, port), StockScreeningHandler)
    print(f"Stock Screening Tool running at http://{host}:{port}")
    server.serve_forever()


if __name__ == "__main__":
    run()
