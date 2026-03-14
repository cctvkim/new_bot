import logging


def get_free_usdt(client) -> float:
    try:
        balance = client.fetch_balance()
        total = balance.get("total", {}).get("USDT", 0)
        used = balance.get("used", {}).get("USDT", 0)
        return float(total) - float(used)
    except Exception as e:
        logging.error(f"get_free_usdt error: {e}")
        return 0.0


def size_from_usdt(client, symbol: str, usdt: float, price: float) -> float:
    if usdt <= 0 or price <= 0:
        return 0.0

    try:
        qty = float(usdt) / float(price)
        market = client.market(symbol)

        step_size = None
        min_qty = None
        min_notional = None

        for f in market["info"].get("filters", []):
            ft = f.get("filterType")
            if ft == "LOT_SIZE":
                step_size = float(f.get("stepSize", 0))
                min_qty = float(f.get("minQty", 0))
            elif ft in ("MIN_NOTIONAL", "NOTIONAL"):
                min_notional = float(f.get("notional") or f.get("minNotional") or 0)

        if step_size and step_size > 0:
            qty = (qty // step_size) * step_size

        qty = client.amount_to_precision(symbol, qty)

        if min_qty and qty < min_qty:
            return 0.0

        if min_notional and qty * price < min_notional:
            return 0.0

        return float(qty)
    except Exception as e:
        logging.error(f"size_from_usdt error: {e}")
        return 0.0


def calc_order_amount(client, symbol: str, current_price: float, invest_ratio: float = 0.9) -> float:
    free_usdt = get_free_usdt(client)
    budget = free_usdt * invest_ratio
    return size_from_usdt(client, symbol, budget, current_price)


def build_sr_exit_prices(client, symbol: str, entry_price: float, support: float, resistance: float, is_long: bool):
    band = max(0.0, float(resistance) - float(support))

    if is_long:
        tp = entry_price + (0.4 * band)
        sl = entry_price * 0.988
    else:
        tp = entry_price - (0.4 * band)
        sl = entry_price * 1.012

    tp = client.price_to_precision(symbol, tp)
    sl = client.price_to_precision(symbol, sl)
    return tp, sl


def build_dev99_exit_prices(client, symbol: str, entry_price: float, ma99: float, is_long: bool):
    if is_long:
        tp = entry_price + (ma99 - entry_price) * 0.4
        sl = entry_price * 0.98
    else:
        tp = entry_price - (entry_price - ma99) * 0.4
        sl = entry_price * 1.02

    tp = client.price_to_precision(symbol, tp)
    sl = client.price_to_precision(symbol, sl)
    return tp, sl