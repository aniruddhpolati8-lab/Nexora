
from __future__ import annotations

import json
import urllib.parse
import urllib.request
from datetime import datetime


TIMEOUT = 10


# ============================================================
# HTTP
# ============================================================

def _get_json(url: str) -> dict:
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Nexora/1.0"
        }
    )

    with urllib.request.urlopen(
        request,
        timeout=TIMEOUT
    ) as response:
        return json.loads(
            response.read().decode("utf-8")
        )


# ============================================================
# STOCK / MARKET DATA
# ============================================================

def stock(
    symbol: str
) -> dict:

    symbol = symbol.strip().upper()

    if not symbol:
        return {
            "error": "No stock symbol provided."
        }

    if len(symbol) > 20:
        return {
            "error": "Invalid symbol."
        }

    # Public Yahoo Finance endpoint.
    url = (
        "https://query1.finance.yahoo.com/v8/"
        "finance/chart/"
        + urllib.parse.quote(symbol)
        + "?range=1d&interval=5m"
    )

    try:

        data = _get_json(url)

        result = data["chart"]["result"][0]
        meta = result["meta"]

        price = meta.get(
            "regularMarketPrice"
        )

        previous = meta.get(
            "previousClose"
        )

        change = None
        change_percent = None

        if (
            price is not None
            and previous
            and previous != 0
        ):
            change = price - previous
            change_percent = (
                change / previous
            ) * 100

        return {
            "symbol": symbol,
            "price": price,
            "previous_close": previous,
            "change": change,
            "change_percent": change_percent,
            "currency": meta.get(
                "currency"
            ),
            "exchange": meta.get(
                "exchangeName"
            ),
            "timestamp": datetime.now().isoformat()
        }

    except Exception as exc:

        return {
            "error": "Unable to retrieve market data.",
            "type": type(exc).__name__
        }


# ============================================================
# FORMAT
# ============================================================

def format_stock(
    data: dict
) -> str:

    if "error" in data:
        return data["error"]

    symbol = data.get(
        "symbol",
        "UNKNOWN"
    )

    price = data.get(
        "price"
    )

    currency = data.get(
        "currency",
        ""
    )

    change = data.get(
        "change"
    )

    percent = data.get(
        "change_percent"
    )

    if price is None:
        return (
            f"No current price data "
            f"was available for {symbol}."
        )

    response = (
        f"{symbol}: {price:.2f} {currency}"
    )

    if change is not None:
        response += (
            f"\nChange: {change:+.2f}"
        )

    if percent is not None:
        response += (
            f" ({percent:+.2f}%)"
        )

    return response


# ============================================================
# MAIN FUNCTION
# ============================================================

def get_finance(
    query: str
) -> str:

    query = query.strip()

    if not query:
        return (
            "Tell me a market symbol, "
            "for example: AAPL."
        )

    words = query.upper().split()

    # Remove common command words.
    ignored = {
        "STOCK",
        "STOCKS",
        "PRICE",
        "SHARE",
        "SHARES",
        "OF",
        "THE",
        "CURRENT",
        "LATEST",
        "PRICE?"
    }

    symbols = [
        word.strip(".,?!")
        for word in words
        if word not in ignored
    ]

    if not symbols:
        return (
            "I couldn't identify a market symbol."
        )

    symbol = symbols[0]

    data = stock(symbol)

    return format_stock(data)


# ============================================================
# STATUS
# ============================================================

def status() -> dict:

    return {
        "finance": True,
        "market_data": True,
        "timestamp": datetime.now().isoformat()
    }


# ============================================================
# TEST
# ============================================================

if __name__ == "__main__":

    print("Nexora Finance Engine")
    print("-" * 30)

    print(
        get_finance(
            "AAPL"
        )
    )
