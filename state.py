from enum import Enum
from dataclasses import dataclass
from typing import Optional


class BotState(Enum):
    IDLE = "IDLE"
    IN_POSITION = "IN_POSITION"
    HOLD = "HOLD"


@dataclass
class PositionState:
    side: Optional[str] = None
    entry_price: Optional[float] = None
    amount: float = 0.0
    entry_mode: Optional[str] = None  # "SR" or "DEV99"


@dataclass
class RuntimeState:
    hold: bool = False
    last_heartbeat_ts: float = 0.0
    last_orphan_check_ts: float = 0.0

    manual_detected: bool = False
    last_manual_alert_ts: float = 0.0

    dev_rung: int = 0
    dev_side: Optional[str] = None
    dev_ma99: Optional[float] = None
    last_dev_log_ts: float = 0.0
    last_sr_log_ts: float = 0.0

    dry_position_side: Optional[str] = None
    dry_position_amount: float = 0.0
    dry_entry_mode: Optional[str] = None
    dry_entry_price: Optional[float] = None