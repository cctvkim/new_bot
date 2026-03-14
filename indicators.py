import numpy as np


def ema(data, span):
    data = np.array(data, dtype=float)
    if len(data) == 0:
        return np.array([])

    alpha = 2 / (span + 1)
    result = np.zeros(len(data), dtype=float)
    result[0] = data[0]

    for i in range(1, len(data)):
        result[i] = alpha * data[i] + (1 - alpha) * result[i - 1]

    return result


def calculate_rsi(data, periods=14):
    data = np.array(data, dtype=float)
    if len(data) < periods + 1:
        return np.array([])

    delta = np.diff(data)
    gain = np.maximum(delta, 0)
    loss = -np.minimum(delta, 0)

    avg_gain = np.zeros(len(data), dtype=float)
    avg_loss = np.zeros(len(data), dtype=float)

    avg_gain[periods] = np.mean(gain[:periods])
    avg_loss[periods] = np.mean(loss[:periods])

    for i in range(periods + 1, len(data)):
        avg_gain[i] = (avg_gain[i - 1] * (periods - 1) + gain[i - 1]) / periods
        avg_loss[i] = (avg_loss[i - 1] * (periods - 1) + loss[i - 1]) / periods

    rs = np.divide(
        avg_gain[periods:],
        avg_loss[periods:],
        out=np.zeros_like(avg_gain[periods:]),
        where=avg_loss[periods:] != 0,
    )
    rsi = 100 - (100 / (1 + rs))
    return np.concatenate([np.full(periods, np.nan), rsi])


def find_reversal_levels(prices, window=None):
    arr = np.array(prices, dtype=float)
    if window is not None and arr.size > window:
        arr = arr[-window:]

    if arr.size < 3:
        return [], []

    signs = np.sign(np.diff(arr))
    zero_cross = np.diff(signs)

    maxima_idx = np.where(zero_cross < 0)[0] + 1
    minima_idx = np.where(zero_cross > 0)[0] + 1

    return arr[maxima_idx].tolist(), arr[minima_idx].tolist()


def get_support_resistance(prices, sr_window=62):
    arr = np.array(prices, dtype=float)
    if arr.size == 0:
        return None, None

    max_prices, min_prices = find_reversal_levels(arr, window=sr_window)

    support = float(min(min_prices)) if min_prices else float(arr.min())
    resistance = float(max(max_prices)) if max_prices else float(arr.max())

    return support, resistance


def calculate_ma99(prices):
    arr = np.array(prices, dtype=float)
    if len(arr) < 99:
        return None
    return float(np.mean(arr[-99:]))


def calculate_deviation_pct(current_price, ma_price):
    if current_price is None or ma_price is None or ma_price == 0:
        return None
    return ((float(current_price) - float(ma_price)) / float(ma_price)) * 100.0