from __future__ import annotations

from dataclasses import dataclass
from datetime import time
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

        raise NotImplementedError("Implement monitoring + forced exit logic")
