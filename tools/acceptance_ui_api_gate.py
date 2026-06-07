"""Acceptance gate: validates /api/signals, /api/status, /api/bets, /api/markets
against a running server at http://127.0.0.1:8091.

Exit 0 on PASS, exit 1 on FAIL.
"""

import sys
import json
import urllib.request
import urllib.error

BASE = "http://127.0.0.1:8091"
ENDPOINTS = ["/api/status", "/api/signals", "/api/bets", "/api/markets"]


def fetch(path):
    url = BASE + path
    try:
        req = urllib.request.Request(url, headers={"Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=15) as resp:
            code = resp.status
            body = json.loads(resp.read().decode())
            return code, body
    except Exception as e:
        return 0, {"error": str(e)}


def main():
    errors = []
    results = {}

    # 1. Check all endpoints return HTTP 200 and no "error" key
    for ep in ENDPOINTS:
        code, body = fetch(ep)
        tag = f"GET {ep}"
        has_error = "error" in body
        results[tag] = {"status_code": code, "has_error": has_error}

        if code != 200:
            errors.append(f"{tag}: HTTP {code} (expected 200)")
        if has_error:
            errors.append(f'{tag}: response contains "error": {body["error"]}')

    # 2. Cross-validate status vs signals
    code_s, body_s = fetch("/api/status")
    code_g, body_g = fetch("/api/signals")

    if code_s == 200 and code_g == 200:
        total_bets = body_s.get("stats", {}).get("total_bets", 0)
        signals_count = body_g.get("count", 0)

        if total_bets > 0 and signals_count == 0:
            errors.append(
                f"Consistency FAIL: status.total_bets={total_bets} "
                f"but signals.count={signals_count}"
            )

        # PnL check: if any PnL is non-zero, signals should have data
        portfolio = body_s.get("portfolio", {})
        total_pnl = portfolio.get("total_pnl", 0)
        unrealized = portfolio.get("unrealized_pnl", 0)
        if (total_pnl != 0 or unrealized != 0) and signals_count == 0:
            errors.append(
                f"PnL without positions: total_pnl={total_pnl}, "
                f"unrealized={unrealized} but signals.count=0"
            )

        # ladder_orders check
        for sig in body_g.get("signals", []):
            lo = sig.get("ladder_orders")
            if lo is not None and not isinstance(lo, list):
                errors.append(
                    f"Bet {sig.get('id')}: ladder_orders is {type(lo)}, expected list"
                )

    # 3. Print results
    print("=" * 60)
    print("UI/API ACCEPTANCE GATE")
    print("=" * 60)
    for tag, r in results.items():
        status = "PASS" if r["status_code"] == 200 and not r["has_error"] else "FAIL"
        err_flag = " [error]" if r["has_error"] else ""
        print(f"  {tag}: HTTP {r['status_code']}{err_flag} -> {status}")

    print()
    if code_s == 200:
        stats = body_s.get("stats", {})
        portfolio = body_s.get("portfolio", {})
        print(f"  status.total_bets    = {stats.get('total_bets', 0)}")
        print(f"  status.total_signals = {stats.get('total_signals', 0)}")
        print(f"  portfolio.total_pnl  = {portfolio.get('total_pnl', 0)}")
        print(f"  portfolio.unrealized = {portfolio.get('unrealized_pnl', 0)}")
    if code_g == 200:
        print(f"  signals.count        = {body_g.get('count', 0)}")
    if code_s == 200:
        code_b, body_b = fetch("/api/bets")
        if code_b == 200:
            print(f"  bets.count           = {body_b.get('count', 0)}")
    if code_s == 200:
        code_m, body_m = fetch("/api/markets")
        if code_m == 200:
            print(f"  markets.count        = {body_m.get('count', 0)}")

    print()
    if errors:
        print("RESULT: FAIL")
        for e in errors:
            print(f"  - {e}")
        sys.exit(1)
    else:
        print("UI_API_GATE: PASSED")
        print("RESULT: PASS")
        sys.exit(0)


if __name__ == "__main__":
    main()
