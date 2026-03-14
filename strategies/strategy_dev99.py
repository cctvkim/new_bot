import numpy as np

from config import (
    DEV_ENTRY_LEVELS,
    DEV_LONG_RSI_FIRST,
    DEV_LONG_RSI_NEXT,
    DEV_SHORT_RSI_FIRST,
    DEV_SHORT_RSI_NEXT,
)
from indicators import calculate_rsi, calculate_ma99, calculate_deviation_pct


def check_dev99_signal(current_price: float, ohlcv_15m, next_rung: int = 1):
    if not ohlcv_15m:
        return None

    closes_15m = np.array([float(c[4]) for c in ohlcv_15m], dtype=float)
    if len(closes_15m) < 99:
        return None

    ema99_last = calculate_ma99(closes_15m)
    if ema99_last is None:
        return None

    dev_pct = calculate_deviation_pct(current_price, ema99_last)
    if dev_pct is None:
        return None

    rsi_arr = calculate_rsi(closes_15m, periods=14)
    if len(rsi_arr) == 0 or np.isnan(rsi_arr[-1]):
        return None
    rsi = float(rsi_arr[-1])

    rung_idx = max(0, min(next_rung - 1, len(DEV_ENTRY_LEVELS) - 1))
    trigger = DEV_ENTRY_LEVELS[rung_idx]

    long_rsi = DEV_LONG_RSI_FIRST if next_rung == 1 else DEV_LONG_RSI_NEXT
    short_rsi = DEV_SHORT_RSI_FIRST if next_rung == 1 else DEV_SHORT_RSI_NEXT

    if dev_pct <= -trigger and rsi <= long_rsi:
        return {
            "signal": "long",
            "reason": f"dev99_long_r{next_rung}",
            "ma99": ema99_last,
            "deviation_pct": dev_pct,
            "rsi": rsi,
            "rung": next_rung,
            "trigger": trigger,
        }

    if dev_pct >= trigger and rsi >= short_rsi:
        return {
            "signal": "short",
            "reason": f"dev99_short_r{next_rung}",
            "ma99": ema99_last,
            "deviation_pct": dev_pct,
            "rsi": rsi,
            "rung": next_rung,
            "trigger": trigger,
        }

    return {
        "debug_only": True,
        "reason": "no_dev_signal",
        "ma99": ema99_last,
        "deviation_pct": dev_pct,
        "rsi": rsi,
        "rung": next_rung,
        "trigger": trigger,
        "long_rsi_limit": long_rsi,
        "short_rsi_limit": short_rsi,
    }