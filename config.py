SYMBOL = "BTC/USDT"

TIMEFRAME_FAST = "3m"
TIMEFRAME_MAIN = "15m"
TIMEFRAME_SR = "30m"

RSI_LONG = 30
RSI_SHORT = 70

LEVERAGE = 10
POLL_INTERVAL = 5

USE_TELEGRAM = True
HEARTBEAT_SECONDS = 3600

# ---- safe testing ----
DRY_RUN = True
DRY_RUN_AMOUNT = 0.001   # BTC 테스트용. 심볼 바꾸면 수정

# ---- DEV99 ladder ----
DEV_ENTRY_LEVELS = [2, 3, 5, 7]          # %
DEV_ENTRY_SHARES = [1/9, 1/9, 2/9, 5/9]  # 1,1,2,5
DEV_LONG_RSI_FIRST = 40
DEV_LONG_RSI_NEXT = 35
DEV_SHORT_RSI_FIRST = 60
DEV_SHORT_RSI_NEXT = 65

BOT_ORDER_PREFIXES = (
    "entry_sr_",
    "entry_dev_",
    "tp_sr_",
    "tp_dev_",
    "sl_sr_",
    "sl_dev_",
)