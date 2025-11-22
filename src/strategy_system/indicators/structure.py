from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Mapping


@dataclass
class StructureConfig:
    atr_multiplier: float = 1.5
    squeeze_threshold: float = 0.25
    structure_weight: float = 0.5
    volatility_weight: float = 0.5


class StructureIndicatorSuite:
    """Tracks market structure (HH/HL) and volatility regimes."""

    def __init__(self, config: StructureConfig | None = None) -> None:
        self._config = config or StructureConfig()

    def compute_score(self, features: Mapping[str, Any]) -> Dict[str, Any]:
        """
        Combines ATR 通道、Bollinger/Keltner、TTM Squeeze、结构破坏等信号。
        """

        raise NotImplementedError("Implement structure & volatility scoring")
