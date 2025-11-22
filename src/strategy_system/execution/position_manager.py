from __future__ import annotations

from dataclasses import dataclass
from typing import Dict


@dataclass
class PositionSizingConfig:
    tiers: Dict[float, float] | None = None  # score_threshold -> position size
    leverage: int = 5

    def __post_init__(self) -> None:
        if self.tiers is None:
            # Example mapping: score threshold => position ratio
            self.tiers = {0.6: 0.05, 0.7: 0.08, 0.8: 0.10, 0.9: 0.15}


class PositionManager:
    """Maps signal strength to concrete order instructions."""

    def __init__(self, config: PositionSizingConfig | None = None) -> None:
        self._config = config or PositionSizingConfig()

    def determine_size(self, score: float) -> float:
        """
        Returns position ratio based on configured tiers.
        """

        raise NotImplementedError("Translate score to position ratio")

    def build_order(self, symbol: str, direction: str, entry_price: float, score: float) -> Dict[str, float | str]:
        """
        Builds an order payload containing size, TP/SL targets, etc.
        """

        raise NotImplementedError("Create order structure with TP/SL based on ATR/percent rules")
