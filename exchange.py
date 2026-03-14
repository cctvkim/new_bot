import logging
import ccxt

from cache import TTLCache


class BinanceFuturesClient:
    def __init__(self, api_key: str, secret: str):
        self.exchange = ccxt.binance({
            "apiKey": api_key,
            "secret": secret,
            "enableRateLimit": True,
            "options": {
                "defaultType": "future",
                "adjustForTimeDifference": True,
            },
        })
        self.exchange.options["recvWindow"] = 10000
        self.exchange.timeout = 20000

        self.exchange.load_markets()
        try:
            self.exchange.load_time_difference()
        except Exception as e:
            logging.warning(f"load_time_difference failed: {e}")

        self.cache = TTLCache()

    def set_leverage(self, symbol: str, leverage: int):
        return self.exchange.set_leverage(leverage, symbol)

    def fetch_ticker(self, symbol: str, ttl: float = 1.5):
        key = f"ticker:{symbol}"
        cached = self.cache.get(key)
        if cached is not None:
            return cached

        data = self.exchange.fetch_ticker(symbol)
        self.cache.set(key, data, ttl)
        return data

    def fetch_ohlcv(self, symbol: str, timeframe: str, limit: int = 200, ttl: float = None):
        if ttl is None:
            if timeframe == "3m":
                ttl = 10
            elif timeframe == "15m":
                ttl = 30
            elif timeframe == "30m":
                ttl = 60
            else:
                ttl = 10

        key = f"ohlcv:{symbol}:{timeframe}:{limit}"
        cached = self.cache.get(key)
        if cached is not None:
            return cached

        data = self.exchange.fetch_ohlcv(symbol, timeframe, limit=limit)
        self.cache.set(key, data, ttl)
        return data

    def fetch_balance(self, ttl: float = 30):
        key = "balance"
        cached = self.cache.get(key)
        if cached is not None:
            return cached

        data = self.exchange.fetch_balance(params={"type": "future"})
        self.cache.set(key, data, ttl)
        return data
    
    def fetch_futures_balance_info(self, ttl: float = 30):
        balance = self.fetch_balance(ttl=ttl)

        total_usdt = 0.0
        free_usdt = 0.0
        used_usdt = 0.0

        try:
            usdt_info = balance.get("USDT", {}) or {}

            total_usdt = float(usdt_info.get("total", 0.0) or 0.0)
            free_usdt = float(usdt_info.get("free", 0.0) or 0.0)
            used_usdt = float(usdt_info.get("used", 0.0) or 0.0)

            # 혹시 ccxt 구조가 다르게 들어오는 경우 대비
            if total_usdt == 0.0 and isinstance(balance.get("total"), dict):
                total_usdt = float(balance["total"].get("USDT", 0.0) or 0.0)
            if free_usdt == 0.0 and isinstance(balance.get("free"), dict):
                free_usdt = float(balance["free"].get("USDT", 0.0) or 0.0)
            if used_usdt == 0.0 and isinstance(balance.get("used"), dict):
                used_usdt = float(balance["used"].get("USDT", 0.0) or 0.0)

        except Exception as e:
            logging.error(f"fetch_futures_balance_info error: {e}")

        return {
            "wallet_balance": total_usdt,
            "available_balance": free_usdt,
            "used_balance": used_usdt,
        }

    def fetch_open_orders(self, symbol: str, ttl: float = 3):
        key = f"open_orders:{symbol}"
        cached = self.cache.get(key)
        if cached is not None:
            return cached

        data = self.exchange.fetch_open_orders(symbol)
        self.cache.set(key, data, ttl)
        return data

    def fetch_positions(self, symbol: str, ttl: float = 3):
        key = f"positions:{symbol}"
        cached = self.cache.get(key)
        if cached is not None:
            return cached

        data = self.exchange.fetch_positions(symbols=[symbol])
        self.cache.set(key, data, ttl)
        return data

    def get_position_amount(self, symbol: str) -> float:
        try:
            positions = self.fetch_positions(symbol, ttl=2)
            for p in positions:
                sym = p.get("symbol", "").replace(":USDT", "")
                if sym == symbol:
                    return float((p.get("info") or {}).get("positionAmt", 0))
        except Exception as e:
            logging.error(f"get_position_amount error: {e}")
        return 0.0

    def get_entry_price(self, symbol: str) -> float:
        try:
            positions = self.fetch_positions(symbol, ttl=2)
            for p in positions:
                sym = p.get("symbol", "").replace(":USDT", "")
                if sym == symbol:
                    return float((p.get("info") or {}).get("entryPrice", 0))
        except Exception as e:
            logging.error(f"get_entry_price error: {e}")
        return 0.0

    def cancel_order(self, order_id: str, symbol: str):
        self.cache.clear(f"open_orders:{symbol}")
        self.cache.clear(f"positions:{symbol}")
        return self.exchange.cancel_order(order_id, symbol)

    def cancel_all_orders(self, symbol: str):
        self.cache.clear(f"open_orders:{symbol}")
        self.cache.clear(f"positions:{symbol}")

        orders = self.exchange.fetch_open_orders(symbol)
        results = []
        for order in orders:
            try:
                results.append(self.exchange.cancel_order(order["id"], symbol))
            except Exception as e:
                logging.warning(f"cancel_all_orders failed for {order.get('id')}: {e}")
        return results

    def create_market_order(self, symbol: str, side: str, amount: float, client_order_id: str = None):
        params = {}
        if client_order_id:
            params["newClientOrderId"] = client_order_id

        if side.lower() == "buy":
            result = self.exchange.create_market_buy_order(symbol, amount, params=params)
        else:
            result = self.exchange.create_market_sell_order(symbol, amount, params=params)

        self.cache.clear(f"positions:{symbol}")
        self.cache.clear(f"open_orders:{symbol}")
        self.cache.clear("balance")
        self.cache.clear(f"ticker:{symbol}")
        return result

    def create_take_profit_market_order(self, symbol: str, side: str, amount: float, trigger_price: float, client_order_id: str = None):
        params = {
            "stopPrice": self.exchange.price_to_precision(symbol, trigger_price),
            "reduceOnly": True,
            "workingType": "MARK_PRICE",
        }
        if client_order_id:
            params["newClientOrderId"] = client_order_id

        result = self.exchange.create_order(
            symbol=symbol,
            type="TAKE_PROFIT_MARKET",
            side=side,
            amount=amount,
            params=params,
        )
        self.cache.clear(f"open_orders:{symbol}")
        return result

    def create_stop_market_order(self, symbol: str, side: str, amount: float, stop_price: float, client_order_id: str = None):
        params = {
            "stopPrice": self.exchange.price_to_precision(symbol, stop_price),
            "reduceOnly": True,
            "workingType": "MARK_PRICE",
        }
        if client_order_id:
            params["newClientOrderId"] = client_order_id

        result = self.exchange.create_order(
            symbol=symbol,
            type="STOP_MARKET",
            side=side,
            amount=amount,
            params=params,
        )
        self.cache.clear(f"open_orders:{symbol}")
        return result

    def price_to_precision(self, symbol: str, price: float) -> float:
        return float(self.exchange.price_to_precision(symbol, price))

    def amount_to_precision(self, symbol: str, amount: float) -> float:
        return float(self.exchange.amount_to_precision(symbol, amount))

    def market(self, symbol: str):
        return self.exchange.market(symbol)