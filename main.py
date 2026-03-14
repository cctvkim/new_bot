import logging
import time

from config import (
    SYMBOL,
    LEVERAGE,
    POLL_INTERVAL,
    DRY_RUN,
    DRY_RUN_AMOUNT,
    HEARTBEAT_SECONDS,
    USE_TELEGRAM,
)
from exchange import BinanceFuturesClient
from notifier import Notifier
from order_manager import OrderManager
from risk import calc_order_amount, get_free_usdt
from state import RuntimeState
from strategies.strategy_sr import check_sr_signal
from strategies.strategy_dev99 import check_dev99_signal
from indicators import calculate_ma99, calculate_deviation_pct

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)


def load_api():
    with open("api.txt", "r", encoding="utf-8") as f:
        lines = [line.strip() for line in f.readlines()]

    api_key = lines[0] if len(lines) > 0 else ""
    secret = lines[1] if len(lines) > 1 else ""
    telegram_token = lines[2] if len(lines) > 2 else ""
    channel_id = lines[3] if len(lines) > 3 else ""
    return api_key, secret, telegram_token, channel_id


def main():
    api_key, secret, telegram_token, channel_id = load_api()

    client = BinanceFuturesClient(api_key, secret)
    runtime = RuntimeState()

    notifier = None
    telegram_bot = None

    if USE_TELEGRAM and telegram_token and channel_id:
        try:
            from telegram_controller import TelegramController

            controller = TelegramController(
                telegram_token,
                channel_id,
                on_hold=lambda: set_hold(runtime, True),
                on_start=lambda: set_hold(runtime, False),
                get_status_text=lambda: build_status_text(runtime, order_manager, client),
            )
            controller.start_background()
            telegram_bot = controller.bot
        except Exception as e:
            logging.error(f"Telegram controller init failed: {e}")

    notifier = Notifier(telegram_bot=telegram_bot, channel_id=channel_id)
    order_manager = OrderManager(client, SYMBOL, notifier=notifier, runtime=runtime)

    if not DRY_RUN:
        client.set_leverage(SYMBOL, LEVERAGE)

    notifier.send(f"Bot started. symbol={SYMBOL}, leverage={LEVERAGE}, dry_run={DRY_RUN}")

    while True:
        try:
            now = time.time()

            order_manager.sync_position_state()

            if now - runtime.last_heartbeat_ts >= HEARTBEAT_SECONDS:
                runtime.last_heartbeat_ts = now
                free_usdt = get_free_usdt(client)
                
                balance_info = client.fetch_futures_balance_info()
                wallet_balance = float(balance_info["wallet_balance"])
                available_balance = float(balance_info["available_balance"])
                tradable_notional_10x = available_balance * 10.0

                notifier.send(
                    f"[HEARTBEAT] symbol={SYMBOL} dry_run={DRY_RUN} hold={runtime.hold} "
                    f"position={order_manager.get_position_side()} amount={order_manager.get_position_amount()} "
                    f"entry={order_manager.get_entry_price()} mode={order_manager.get_entry_mode()} "
                    f"dev_rung={runtime.dev_rung} wallet={wallet_balance:.2f} "
                    f"free_usdt={free_usdt:.2f}"
                    f"available={available_balance:.2f} tradable_10x={tradable_notional_10x:.2f}"
                )

            if runtime.hold:
                logging.info("HOLD 상태")
                time.sleep(POLL_INTERVAL)
                continue

            if now - runtime.last_orphan_check_ts >= 20:
                runtime.last_orphan_check_ts = now
                order_manager.cleanup_orphan_orders()

            current_price = float(client.fetch_ticker(SYMBOL)["last"])
            ohlcv_3m = client.fetch_ohlcv(SYMBOL, "3m", limit=100)
            ohlcv_15m = client.fetch_ohlcv(SYMBOL, "15m", limit=120)
            ohlcv_30m = client.fetch_ohlcv(SYMBOL, "30m", limit=100)
            
            closes_15m = [float(c[4]) for c in ohlcv_15m]
            ma99_last = calculate_ma99(closes_15m)
            dev_pct_now = calculate_deviation_pct(current_price, ma99_last)
            
            balance_info = client.fetch_futures_balance_info()
            wallet_balance = float(balance_info["wallet_balance"])
            available_balance = float(balance_info["available_balance"])
            tradable_notional_10x = available_balance * 10.0

            if order_manager.is_manual_position():
                if (not runtime.manual_detected) or (now - runtime.last_manual_alert_ts >= 300):
                    runtime.manual_detected = True
                    runtime.last_manual_alert_ts = now
                    notifier.send("수동 포지션 감지 → 자동매매 개입 중지")
                time.sleep(POLL_INTERVAL)
                continue
            else:
                runtime.manual_detected = False

            if DRY_RUN:
                amount = DRY_RUN_AMOUNT
            else:
                amount = calc_order_amount(client, SYMBOL, current_price, invest_ratio=0.9, leverage=LEVERAGE)

            if amount <= 0:
                logging.warning("Calculated amount is invalid. Skipping.")
                time.sleep(POLL_INTERVAL)
                continue

            next_rung = runtime.dev_rung + 1 if runtime.dev_rung > 0 else 1
            dev_signal = check_dev99_signal(current_price, ohlcv_15m, next_rung=next_rung)

            if now - runtime.last_dev_log_ts >= 60:
                runtime.last_dev_log_ts = now
                if dev_signal and "signal" in dev_signal:
                    logging.info(
                        f"DEV99 READY rung={next_rung} signal={dev_signal['signal']} "
                        f"dev={dev_signal['deviation_pct']:.3f}% trigger={dev_signal['trigger']} "
                        f"rsi={dev_signal['rsi']:.2f} ma99={dev_signal['ma99']:.4f}"
                    )
                elif dev_signal and dev_signal.get("debug_only"):
                    logging.info(
                        f"DEV99 NONE rung={next_rung} "
                        f"dev={dev_signal['deviation_pct']:.3f}% trigger={dev_signal['trigger']} "
                        f"rsi={dev_signal['rsi']:.2f} "
                        f"long_limit={dev_signal['long_rsi_limit']} short_limit={dev_signal['short_rsi_limit']} "
                        f"ma99={dev_signal['ma99']:.4f}"
                    )
                else:
                    logging.info(f"DEV99 NONE rung={next_rung}")

            if dev_signal and "signal" in dev_signal:
                existing_side = order_manager.get_position_side()
                if (not existing_side) or (existing_side == dev_signal["signal"]):
                    notifier.send(f"DEV99 SIGNAL: {dev_signal}")
                    order_manager.place_dev99_ladder_entry(
                        side=dev_signal["signal"],
                        total_amount=amount,
                        current_price=current_price,
                        ma99=dev_signal["ma99"],
                    )
                    order_manager.ensure_dev99_exits(current_price)
                    time.sleep(POLL_INTERVAL)
                    continue

            if order_manager.has_position():
                order_manager.ensure_dev99_exits(current_price)
                logging.info(
                    f"IN POSITION side={order_manager.get_position_side()} "
                    f"entry={order_manager.get_entry_price()} amount={order_manager.get_position_amount()} "
                    f"mode={order_manager.get_entry_mode()} dev_rung={runtime.dev_rung} "
                    f"current_price={current_price} sma99={ma99_last:.4f} dev={dev_pct_now:.3f}% "
                    f"wallet={wallet_balance:.2f} available={available_balance:.2f} "
                    f"tradable_10x={tradable_notional_10x:.2f}"
                )
                time.sleep(POLL_INTERVAL)
                continue

            sr_signal = check_sr_signal(current_price, ohlcv_3m, ohlcv_30m)

            if now - runtime.last_sr_log_ts >= 60:
                runtime.last_sr_log_ts = now
                if sr_signal and "signal" in sr_signal:
                    logging.info(
                        f"SR READY signal={sr_signal['signal']} "
                        f"support={sr_signal['support']:.4f} resistance={sr_signal['resistance']:.4f} "
                        f"rsi={sr_signal['rsi']:.2f} price={current_price}"
                    )
                elif sr_signal and sr_signal.get("debug_only"):
                    logging.info(
                        f"SR NONE support={sr_signal['support']:.4f} resistance={sr_signal['resistance']:.4f} "
                        f"rsi={sr_signal['rsi']:.2f} near_support={sr_signal['near_support']} "
                        f"near_resistance={sr_signal['near_resistance']} "
                        f"long_cross={sr_signal['long_cross']} short_cross={sr_signal['short_cross']} "
                        f"price={current_price}"
                    )
                else:
                    logging.info("SR NONE")

            if sr_signal and "signal" in sr_signal:
                notifier.send(f"SR SIGNAL: {sr_signal}")
                order_manager.place_sr_entry(
                    side=sr_signal["signal"],
                    amount=amount,
                    support=sr_signal["support"],
                    resistance=sr_signal["resistance"],
                    current_price=current_price,
                )
                time.sleep(POLL_INTERVAL)
                continue

            logging.info(
                f"NO SIGNAL current_price={current_price} "
                f"sma99={ma99_last:.4f} dev={dev_pct_now:.3f}% "
                f"wallet={wallet_balance:.2f} available={available_balance:.2f} "
                f"tradable_10x={tradable_notional_10x:.2f} "
                f"hold={runtime.hold} dev_rung={runtime.dev_rung}"
            )
            time.sleep(POLL_INTERVAL)

        except Exception as e:
            logging.exception(f"Main loop error: {e}")
            time.sleep(POLL_INTERVAL)


def set_hold(runtime: RuntimeState, hold: bool):
    runtime.hold = hold
    if hold:
        logging.info("HOLD activated")
    else:
        logging.info("HOLD released")


def build_status_text(runtime: RuntimeState, order_manager, client):
    free_usdt = get_free_usdt(client)
    return (
        f"status\n"
        f"hold={runtime.hold}\n"
        f"dry_run={DRY_RUN}\n"
        f"position_side={order_manager.get_position_side()}\n"
        f"position_amount={order_manager.get_position_amount()}\n"
        f"entry_price={order_manager.get_entry_price()}\n"
        f"entry_mode={order_manager.get_entry_mode()}\n"
        f"dev_rung={runtime.dev_rung}\n"
        f"dev_side={runtime.dev_side}\n"
        f"dev_ma99={runtime.dev_ma99}\n"
        f"free_usdt={free_usdt}"
    )


if __name__ == "__main__":
    main()