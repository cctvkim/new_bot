import numpy as np
import pandas as pd

from indicators import calculate_rsi, get_support_resistance


def check_sr_signal(current_price: float, ohlcv_3m, ohlcv_30m):
    if not ohlcv_3m or not ohlcv_30m:
        return None

    closes_3m = np.array([float(c[4]) for c in ohlcv_3m], dtype=float)
    closes_30m = np.array([float(c[4]) for c in ohlcv_30m], dtype=float)

    if len(closes_3m) < 10 or len(closes_30m) < 20:
        return {
            "debug_only": True,
            "reason": "not_enough_bars",
            "bars_3m": len(closes_3m),
            "bars_30m": len(closes_30m),
        }

    support, resistance = get_support_resistance(closes_30m, sr_window=62)
    if support is None or resistance is None:
        return {
            "debug_only": True,
            "reason": "sr_none",
        }

    rsi_arr = calculate_rsi(closes_30m, periods=14)
    if len(rsi_arr) == 0 or np.isnan(rsi_arr[-1]):
        return {
            "debug_only": True,
            "reason": "rsi_invalid",
            "support": support,
            "resistance": resistance,
        }

    rsi = float(rsi_arr[-1])

    low_ema_1 = pd.Series([float(c[3]) for c in ohlcv_3m]).ewm(span=1, adjust=False).mean()
    low_ema_3 = pd.Series([float(c[3]) for c in ohlcv_3m]).ewm(span=3, adjust=False).mean()

    high_ema_1 = pd.Series([float(c[2]) for c in ohlcv_3m]).ewm(span=1, adjust=False).mean()
    high_ema_3 = pd.Series([float(c[2]) for c in ohlcv_3m]).ewm(span=3, adjust=False).mean()

    long_cross = low_ema_1.iloc[-2] <= low_ema_3.iloc[-2] and low_ema_1.iloc[-1] > low_ema_3.iloc[-1]
    short_cross = high_ema_1.iloc[-2] >= high_ema_3.iloc[-2] and high_ema_1.iloc[-1] < high_ema_3.iloc[-1]

    near_support = current_price <= support * 1.01
    near_resistance = current_price >= resistance * 0.99

    if near_support and rsi < 35 and long_cross:
        return {
            "signal": "long",
            "reason": "sr_long",
            "support": support,
            "resistance": resistance,
            "rsi": rsi,
        }

    if near_resistance and rsi > 65 and short_cross:
        return {
            "signal": "short",
            "reason": "sr_short",
            "support": support,
            "resistance": resistance,
            "rsi": rsi,
        }

    return {
        "debug_only": True,
        "reason": "no_sr_signal",
        "support": support,
        "resistance": resistance,
        "rsi": rsi,
        "near_support": near_support,
        "near_resistance": near_resistance,
        "long_cross": long_cross,
        "short_cross": short_cross,
    }