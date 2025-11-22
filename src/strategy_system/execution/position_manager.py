from __future__ import annotations

from dataclasses import dataclass
from typing import Dict


@dataclass
class PositionSizingConfig:
    tiers: Dict[float, float] | None = None  # score_threshold -> position size
    leverage: int = 5
    take_profit_ratio: float = 0.06
    stop_loss_ratio: float = 0.03

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

        size = 0.0
        for threshold in sorted(self._config.tiers.keys()):
            if score >= threshold:
                size = self._config.tiers[threshold]
        return size

    def build_order(self, symbol: str, direction: str, entry_price: float, score: float) -> Dict[str, float | str]:
        """
        Builds an order payload containing size, TP/SL targets, etc.
        """

        direction = direction.lower()
        if direction not in {"long", "short"}:
            return {}

        size_ratio = self.determine_size(abs(score))
        if size_ratio <= 0:
            return {}

        leverage = self._config.leverage
        tp_ratio = self._config.take_profit_ratio / max(leverage, 1)
        sl_ratio = self._config.stop_loss_ratio / max(leverage, 1)
        sign = 1 if direction == "long" else -1

        take_profit = entry_price * (1 + sign * tp_ratio)
        stop_loss = entry_price * (1 - sign * sl_ratio)

        return {
            "symbol": symbol,
            "direction": direction,
            "entry_price": entry_price,
            "position_ratio": size_ratio,
            "leverage": leverage,
            "take_profit": take_profit,
            "stop_loss": stop_loss,
            "signal_score": score,
        }
