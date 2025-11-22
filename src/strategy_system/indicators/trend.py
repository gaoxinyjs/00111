from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Mapping


@dataclass
class TrendConfig:
    macd_weight: float = 0.4
    ema_weight: float = 0.3
    supertrend_weight: float = 0.2
    adx_weight: float = 0.1


class TrendIndicatorSuite:
    """Calculates trend/momentum related scores."""

    def __init__(self, config: TrendConfig | None = None) -> None:
        self._config = config or TrendConfig()

    def compute_score(self, features: Mapping[str, Any]) -> Dict[str, Any]:
        """
        Parameters
        ----------
        features: dict
            Feature payload for a single symbol/interval.

        Returns
        -------
        dict
            {"score": float, "details": {...}}
        """

        raise NotImplementedError("Calculate MACD/EMA/SuperTrend/ADX composite score")
