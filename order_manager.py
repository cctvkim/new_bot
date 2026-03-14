import logging
import uuid
import time

from config import DEV_ENTRY_SHARES, BOT_ORDER_PREFIXES, DRY_RUN
from risk import build_sr_exit_prices, build_dev99_exit_prices


class OrderManager:
    def __init__(self, client, symbol: str, notifier=None, runtime=None):
        self.client = client
        self.symbol = symbol
        self.notifier = notifier
        self.runtime = runtime

    def _send(self, msg: str):
        if self.notifier:
            self.notifier.send(msg)
        else:
            logging.info(msg)

    def _reset_dev_state(self):
        self.runtime.dev_rung = 0
        self.runtime.dev_side = None
        self.runtime.dev_ma99 = None

    def _reset_dry_position(self):
        self.runtime.dry_position_side = None
        self.runtime.dry_position_amount = 0.0
        self.runtime.dry_entry_mode = None
        self.runtime.dry_entry_price = None

    def sync_position_state(self):
        """
        포지션이 완전히 없으면 DEV 상태도 초기화.
        DRY_RUN에서도 포지션이 없으면 dry state를 정리.
        """
        if DRY_RUN:
            if abs(float(self.runtime.dry_position_amount)) <= 0:
                self._reset_dry_position()
                self._reset_dev_state()
            return

        try:
            amt = abs(float(self.client.get_position_amount(self.symbol)))
            if amt <= 0:
                self._reset_dev_state()
        except Exception as e:
            logging.error(f"sync_position_state error: {e}")

    def has_position(self) -> bool:
        if DRY_RUN:
            return abs(float(self.runtime.dry_position_amount)) > 0
        amt = self.client.get_position_amount(self.symbol)
        return abs(float(amt)) > 0

    def get_position_side(self):
        if DRY_RUN:
            return self.runtime.dry_position_side
        amt = self.client.get_position_amount(self.symbol)
        if amt > 0:
            return "long"
        if amt < 0:
            return "short"
        return None

    def get_entry_price(self):
        if DRY_RUN:
            return self.runtime.dry_entry_price
        return self.client.get_entry_price(self.symbol)

    def get_entry_mode(self):
        if DRY_RUN:
            return self.runtime.dry_entry_mode
        return None

    def get_position_amount(self):
        if DRY_RUN:
            return float(self.runtime.dry_position_amount)
        return abs(float(self.client.get_position_amount(self.symbol)))

    def _set_dry_position(self, side, amount, entry_price, mode):
        cur_amt = float(self.runtime.dry_position_amount)
        cur_price = self.runtime.dry_entry_price

        if cur_amt > 0 and cur_price:
            new_amt = cur_amt + amount
            avg_price = ((cur_amt * cur_price) + (amount * entry_price)) / new_amt
            self.runtime.dry_position_amount = new_amt
            self.runtime.dry_entry_price = avg_price
        else:
            self.runtime.dry_position_amount = amount
            self.runtime.dry_entry_price = entry_price

        self.runtime.dry_position_side = side
        self.runtime.dry_entry_mode = mode

    def is_manual_position(self) -> bool:
        if DRY_RUN:
            return False

        amt = self.client.get_position_amount(self.symbol)
        if abs(float(amt)) <= 0:
            return False

        try:
            orders = self.client.fetch_open_orders(self.symbol)
        except Exception as e:
            logging.error(f"is_manual_position fetch_open_orders error: {e}")
            return False

        for order in orders:
            info = order.get("info", {}) or {}
            coid = info.get("clientOrderId") or order.get("clientOrderId") or ""
            if coid.startswith(BOT_ORDER_PREFIXES):
                return False

        return True

    def cancel_all_orders(self):
        if DRY_RUN:
            return
        try:
            self.client.cancel_all_orders(self.symbol)
        except Exception as e:
            logging.error(f"cancel_all_orders error: {e}")

    def cleanup_orphan_orders(self):
        if DRY_RUN:
            return

        try:
            amt = self.client.get_position_amount(self.symbol)
            open_orders = self.client.fetch_open_orders(self.symbol)
            if abs(float(amt)) == 0 and open_orders:
                self._send("포지션 없음 + 오픈오더 존재 → orphan orders 정리")
                self.client.cancel_all_orders(self.symbol)
        except Exception as e:
            logging.error(f"cleanup_orphan_orders error: {e}")

    def ensure_dev99_exits(self, current_price: float):
        if not self.has_position():
            return

        if self.get_entry_mode() != "DEV99":
            return

        side = self.get_position_side()
        entry_price = self.get_entry_price()
        amount = self.get_position_amount()
        ma99 = self.runtime.dev_ma99
        rung = self.runtime.dev_rung

        if not side or not entry_price or not amount or not ma99:
            return

        tp_price, sl_price = build_dev99_exit_prices(
            self.client, self.symbol, entry_price, ma99, is_long=(side == "long")
        )

        if DRY_RUN:
            if rung < 3:
                self._send(f"[DRY_RUN] DEV99 R{rung} TP 유지 필요 | side={side} tp={tp_price}")
            else:
                self._send(f"[DRY_RUN] DEV99 R{rung} TP+SL 유지 필요 | side={side} tp={tp_price} sl={sl_price}")
            return

        try:
            open_orders = self.client.fetch_open_orders(self.symbol)
            has_tp = False
            has_sl = False
            for order in open_orders:
                typ = (order.get("info", {}).get("type") or order.get("type") or "").upper()
                if "TAKE_PROFIT" in typ:
                    has_tp = True
                if "STOP" in typ:
                    has_sl = True

            exit_side = "sell" if side == "long" else "buy"

            if not has_tp:
                self.client.create_take_profit_market_order(
                    symbol=self.symbol,
                    side=exit_side,
                    amount=amount,
                    trigger_price=tp_price,
                    client_order_id=f"tp_dev_fix_{uuid.uuid4().hex[:8]}",
                )
                self._send(f"DEV99 TP 보강 | side={side} rung={rung} tp={tp_price}")

            if rung >= 3 and not has_sl:
                self.client.create_stop_market_order(
                    symbol=self.symbol,
                    side=exit_side,
                    amount=amount,
                    stop_price=sl_price,
                    client_order_id=f"sl_dev_fix_{uuid.uuid4().hex[:8]}",
                )
                self._send(f"DEV99 SL 보강 | side={side} rung={rung} sl={sl_price}")

        except Exception as e:
            logging.error(f"ensure_dev99_exits error: {e}")

    def place_sr_entry(self, side: str, amount: float, support: float, resistance: float, current_price: float):
        if amount <= 0:
            return None
        if self.has_position():
            return None
        if self.is_manual_position():
            self._send("수동 포지션 감지 → SR 자동진입 스킵")
            return None

        tp_price, sl_price = build_sr_exit_prices(
            self.client,
            self.symbol,
            current_price,
            support,
            resistance,
            is_long=(side == "long"),
        )

        if DRY_RUN:
            self._set_dry_position(side, amount, current_price, "SR")
            self._send(
                f"[DRY_RUN][SR ENTRY] side={side} amount={amount} entry={current_price} tp={tp_price} sl={sl_price}"
            )
            return True

        try:
            entry_side = "buy" if side == "long" else "sell"
            exit_side = "sell" if side == "long" else "buy"

            order = self.client.create_market_order(
                symbol=self.symbol,
                side=entry_side,
                amount=amount,
                client_order_id=f"entry_sr_{uuid.uuid4().hex[:8]}",
            )
            entry_price = self.client.get_entry_price(self.symbol) or current_price

            self.client.create_take_profit_market_order(
                symbol=self.symbol,
                side=exit_side,
                amount=amount,
                trigger_price=tp_price,
                client_order_id=f"tp_sr_{uuid.uuid4().hex[:8]}",
            )
            self.client.create_stop_market_order(
                symbol=self.symbol,
                side=exit_side,
                amount=amount,
                stop_price=sl_price,
                client_order_id=f"sl_sr_{uuid.uuid4().hex[:8]}",
            )

            self._send(f"[SR ENTRY] side={side} amount={amount} entry={entry_price} tp={tp_price} sl={sl_price}")
            return order
        except Exception as e:
            logging.error(f"place_sr_entry error: {e}")
            return None

    def place_dev99_ladder_entry(self, side: str, total_amount: float, current_price: float, ma99: float):
        if total_amount <= 0:
            return None

        if self.is_manual_position():
            self._send("수동 포지션 감지 → DEV99 자동진입 스킵")
            return None

        current_rung = self.runtime.dev_rung
        if current_rung >= 4:
            return None

        existing_side = self.get_position_side()
        if existing_side and existing_side != side:
            return None

        rung_no = current_rung + 1
        rung_amount = float(total_amount) * float(DEV_ENTRY_SHARES[current_rung])

        if rung_amount <= 0:
            return None

        if DRY_RUN:
            self._set_dry_position(side, rung_amount, current_price, "DEV99")
            self.runtime.dev_rung = rung_no
            self.runtime.dev_side = side
            self.runtime.dev_ma99 = ma99

            tp_price, sl_price = build_dev99_exit_prices(
                self.client,
                self.symbol,
                self.runtime.dry_entry_price,
                ma99,
                is_long=(side == "long"),
            )

            if rung_no < 3:
                self._send(
                    f"[DRY_RUN][DEV99 R{rung_no}] side={side} add={rung_amount} avg={self.runtime.dry_entry_price} tp={tp_price}"
                )
            else:
                self._send(
                    f"[DRY_RUN][DEV99 R{rung_no}] side={side} add={rung_amount} avg={self.runtime.dry_entry_price} tp={tp_price} sl={sl_price}"
                )
            return True

        try:
            entry_side = "buy" if side == "long" else "sell"
            exit_side = "sell" if side == "long" else "buy"

            self.client.create_market_order(
                symbol=self.symbol,
                side=entry_side,
                amount=rung_amount,
                client_order_id=f"entry_dev_r{rung_no}_{uuid.uuid4().hex[:8]}",
            )

            entry_price = self.client.get_entry_price(self.symbol) or current_price
            total_live_amount = abs(float(self.client.get_position_amount(self.symbol)))

            self.cancel_all_orders()

            self.runtime.dev_rung = rung_no
            self.runtime.dev_side = side
            self.runtime.dev_ma99 = ma99

            tp_price, sl_price = build_dev99_exit_prices(
                self.client, self.symbol, entry_price, ma99, is_long=(side == "long")
            )

            self.client.create_take_profit_market_order(
                symbol=self.symbol,
                side=exit_side,
                amount=total_live_amount,
                trigger_price=tp_price,
                client_order_id=f"tp_dev_r{rung_no}_{uuid.uuid4().hex[:8]}",
            )

            if rung_no >= 3:
                self.client.create_stop_market_order(
                    symbol=self.symbol,
                    side=exit_side,
                    amount=total_live_amount,
                    stop_price=sl_price,
                    client_order_id=f"sl_dev_r{rung_no}_{uuid.uuid4().hex[:8]}",
                )

            if rung_no < 3:
                self._send(
                    f"[DEV99 R{rung_no}] side={side} add={rung_amount} total={total_live_amount} entry={entry_price} tp={tp_price}"
                )
            else:
                self._send(
                    f"[DEV99 R{rung_no}] side={side} add={rung_amount} total={total_live_amount} entry={entry_price} tp={tp_price} sl={sl_price}"
                )

            return True

        except Exception as e:
            logging.error(f"place_dev99_ladder_entry error: {e}")
            return None