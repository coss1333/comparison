import asyncio
import aiohttp
from typing import Dict, Optional, Tuple

# Normalize token symbols per exchange (base-quote pairs)
# We try to fetch USD or USDT quotes; if USDT we will convert to USD using a USDT-USD rate.
SYMBOLS = {
    "BTC": {
        "binance": "BTCUSDT",
        "coinbase": "BTC-USD",
        "kraken": "XBTUSD",
        "kucoin": "BTC-USDT",
        "bybit": "BTCUSDT",
        "okx": "BTC-USDT",
        "bitstamp": "btcusd",
    },
    "ETH": {
        "binance": "ETHUSDT",
        "coinbase": "ETH-USD",
        "kraken": "ETHUSD",
        "kucoin": "ETH-USDT",
        "bybit": "ETHUSDT",
        "okx": "ETH-USDT",
        "bitstamp": "ethusd",
    },
    "SOL": {
        "binance": "SOLUSDT",
        "coinbase": "SOL-USD",
        "kraken": "SOLUSD",
        "kucoin": "SOL-USDT",
        "bybit": "SOLUSDT",
        "okx": "SOL-USDT",
        "bitstamp": "solusd",
    },
    "BNB": {
        "binance": "BNBUSDT",
        # coinbase: not listed
        "kraken": None,  # BNB not on Kraken
        "kucoin": "BNB-USDT",
        "bybit": "BNBUSDT",
        "okx": "BNB-USDT",
        "bitstamp": None,
    },
}

# Helper: fetch JSON with timeout and graceful error handling
async def _get_json(session: aiohttp.ClientSession, url: str, params=None, headers=None):
    try:
        async with session.get(url, params=params, headers=headers, timeout=aiohttp.ClientTimeout(total=8)) as r:
            if r.status != 200:
                return None
            return await r.json(content_type=None)
    except Exception:
        return None

async def fetch_usdt_usd_rate(session: aiohttp.ClientSession) -> float:
    """Fetch USDT-USD rate from Coinbase (close to 1)."""
    data = await _get_json(session, "https://api.exchange.coinbase.com/products/USDT-USD/ticker")
    if data and "price" in data:
        return float(data["price"])
    # Fallback 1.0 if API unavailable
    return 1.0

async def binance_price(session, symbol: str) -> Optional[Tuple[float, str]]:
    data = await _get_json(session, "https://api.binance.com/api/v3/ticker/price", params={"symbol": symbol})
    if not data or "price" not in data:
        return None
    return float(data["price"]), "USDT" if symbol.endswith("USDT") else "USD"

async def coinbase_price(session, symbol: str) -> Optional[Tuple[float, str]]:
    if symbol is None: 
        return None
    data = await _get_json(session, f"https://api.exchange.coinbase.com/products/{symbol}/ticker")
    if not data or "price" not in data:
        return None
    return float(data["price"]), "USD"

async def kraken_price(session, symbol: str) -> Optional[Tuple[float, str]]:
    if symbol is None:
        return None
    data = await _get_json(session, "https://api.kraken.com/0/public/Ticker", params={"pair": symbol})
    if not data or "result" not in data or not data["result"]:
        return None
    key = list(data["result"].keys())[0]
    price = float(data["result"][key]["c"][0])  # last trade price
    return price, "USD"

async def kucoin_price(session, symbol: str) -> Optional[Tuple[float, str]]:
    data = await _get_json(session, "https://api.kucoin.com/api/v1/market/orderbook/level1", params={"symbol": symbol})
    if not data or "data" not in data or "price" not in data["data"]:
        return None
    return float(data["data"]["price"]), "USDT" if symbol.endswith("USDT") else "USD"

async def bybit_price(session, symbol: str) -> Optional[Tuple[float, str]]:
    # spot ticker
    data = await _get_json(session, "https://api.bybit.com/v5/market/tickers", params={"category":"spot","symbol":symbol})
    try:
        if data and data.get("result", {}).get("list"):
            price = float(data["result"]["list"][0]["lastPrice"])
            return price, "USDT" if symbol.endswith("USDT") else "USD"
    except Exception:
        return None
    return None

async def okx_price(session, symbol: str) -> Optional[Tuple[float, str]]:
    data = await _get_json(session, "https://www.okx.com/api/v5/market/ticker", params={"instId": symbol})
    try:
        if data and data.get("data"):
            price = float(data["data"][0]["last"])
            return price, "USDT" if symbol.endswith("USDT") else "USD"
    except Exception:
        return None
    return None

async def bitstamp_price(session, symbol: str) -> Optional[Tuple[float, str]]:
    if symbol is None:
        return None
    data = await _get_json(session, f"https://www.bitstamp.net/api/v2/ticker/{symbol}")
    if not data or "last" not in data:
        return None
    return float(data["last"]), "USD"

EXCHANGES = {
    "binance": binance_price,
    "coinbase": coinbase_price,
    "kraken": kraken_price,
    "kucoin": kucoin_price,
    "bybit": bybit_price,
    "okx": okx_price,
    "bitstamp": bitstamp_price,
}

async def fetch_prices_for_token(session: aiohttp.ClientSession, token: str, exchanges: list) -> Dict[str, float]:
    """Return mapping exchange -> price in USD for the given token."""
    tasks = []
    usdt_rate_task = asyncio.create_task(fetch_usdt_usd_rate(session))
    for ex in exchanges:
        sym = SYMBOLS.get(token, {}).get(ex)
        fn = EXCHANGES.get(ex)
        if not fn or sym is None:
            continue
        tasks.append(asyncio.create_task(fn(session, sym)))
    results = await asyncio.gather(*tasks, return_exceptions=True)
    usdt_usd = await usdt_rate_task
    out = {}
    i = 0
    for ex in exchanges:
        sym = SYMBOLS.get(token, {}).get(ex)
        fn = EXCHANGES.get(ex)
        if not fn or sym is None:
            continue
        res = results[i]
        i += 1
        if isinstance(res, Exception) or res is None:
            continue
        price, quote = res
        if quote == "USDT":
            price = price * usdt_usd
        out[ex] = price
    return out
