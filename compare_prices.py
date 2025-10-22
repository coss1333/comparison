from typing import Dict, List, Tuple

def compute_spreads(prices: Dict[str, Dict[str, float]]) -> Dict[str, Dict]:
    """ 
    prices: {token: {exchange: price_usd}}
    returns per-token: min, max, spread_abs, spread_pct, best_buy, best_sell, table(list of tuples)
    """
    out = {}
    for token, mp in prices.items():
        if not mp:
            out[token] = {"table":[], "summary":"нет данных"}
            continue
        items = sorted(mp.items(), key=lambda kv: kv[1])
        min_ex, min_p = items[0]
        max_ex, max_p = items[-1]
        spread_abs = max_p - min_p
        spread_pct = (spread_abs / min_p)*100 if min_p else 0.0
        out[token] = {
            "min": (min_ex, min_p),
            "max": (max_ex, max_p),
            "spread_abs": spread_abs,
            "spread_pct": spread_pct,
            "best_buy": (min_ex, min_p),
            "best_sell": (max_ex, max_p),
            "table": items,
        }
    return out

def format_markdown(prices: Dict[str, Dict[str, float]], spreads: Dict[str, Dict], threshold_pct: float) -> str:
    lines = []
    lines.append("📊 *Сравнение цен по биржам* (USD)")
    for token in prices.keys():
        s = spreads[token]
        lines.append(f"\n*{token}* — лучший бид/оффер и спред:")
        if not s.get("table"):
            lines.append("_нет данных_")
            continue
        min_ex, min_p = s["min"]
        max_ex, max_p = s["max"]
        lines.append(f"• Лучшее место купить: *{min_ex}* — `${min_p:,.2f}`")
        lines.append(f"• Лучшее место продать: *{max_ex}* — `${max_p:,.2f}`")
        lines.append(f"• Разница: `${s['spread_abs']:,.2f}` ({s['spread_pct']:.3f}%)")
        if s['spread_pct'] >= threshold_pct:
            lines.append(f"🚨 *СПРЕД* превышает порог {threshold_pct:.3f}%")
        # table
        lines.append("Биржи:")
        for ex, p in s["table"]:
            lines.append(f"  - `{ex}` — `${p:,.2f}`")
    return "\n".join(lines)
