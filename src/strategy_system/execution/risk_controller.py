from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time
from typing import Any, Dict


@dataclass
class RiskConfig:
    minute_check_interval: int = 60  # seconds
    force_flat_time: time = time(hour=23, minute=45)
    tp_ratio: float = 0.06
    sl_ratio: float = 0.03


class RiskController:
    """Handles runtime monitoring, TP/SL enforcement, and forced exits."""

    def __init__(self, config: RiskConfig | None = None) -> None:
        self._config = config or RiskConfig()

    def evaluate_position(self, position_state: Dict[str, Any], deepseek_view: Dict[str, Any]) -> Dict[str, Any]:
        """
        Determines whether to hold, tighten stops, or exit immediately.
        """

        now = datetime.utcnow()
        if self._should_force_flat(now):
            return {"action": "close", "reason": "force_flat", "timestamp": now.isoformat()}

        entry_price = position_state.get("entry_price")
        current_price = position_state.get("current_price") or position_state.get("mark_price")
        direction = (position_state.get("direction") or "").lower()
        leverage = position_state.get("leverage") or 1

        if None in {entry_price, current_price} or direction not in {"long", "short"}:
            return {"action": "hold", "reason": "insufficient_data"}

        entry_price = float(entry_price)
        current_price = float(current_price)
        leverage = max(1, int(leverage))
        pnl_ratio = ((current_price - entry_price) / entry_price) * (1 if direction == "long" else -1)

        tp_ratio = self._config.tp_ratio / leverage
        sl_ratio = self._config.sl_ratio / leverage

        if pnl_ratio >= tp_ratio:
            return {"action": "close", "reason": "target_hit", "timestamp": now.isoformat()}
        if pnl_ratio <= -sl_ratio:
            return {"action": "close", "reason": "stop_loss", "timestamp": now.isoformat()}

        deepseek_direction = (deepseek_view or {}).get("direction", "").lower()
        deepseek_confidence = float(deepseek_view.get("confidence", 0.0) or 0.0)
        reversal_prob = float(deepseek_view.get("reversal_probability", 0.0) or 0.0)

        if deepseek_direction in {"long", "short"} and deepseek_direction != direction and deepseek_confidence >= 0.6:
            return {"action": "close", "reason": "ai_reverse", "timestamp": now.isoformat()}

        if reversal_prob >= 0.7 and pnl_ratio > 0:
            return {"action": "close", "reason": "ai_reversal_warning", "timestamp": now.isoformat()}

        # 动态跟踪止损：盈利达到目标一半时上移止损
        if pnl_ratio > tp_ratio * 0.5:
            sign = 1 if direction == "long" else -1
            adjusted_stop = entry_price * (1 + sign * max(pnl_ratio * 0.5, sl_ratio))
            return {
                "action": "tighten",
                "new_stop": adjusted_stop,
                "reason": "trail_profit",
                "timestamp": now.isoformat(),
            }

        return {"action": "hold", "reason": "stable", "timestamp": now.isoformat()}

    def _should_force_flat(self, now: datetime) -> bool:
        force_time = self._config.force_flat_time
        force_dt = now.replace(hour=force_time.hour, minute=force_time.minute, second=0, microsecond=0)
        if now >= force_dt:
            return True
        return False
