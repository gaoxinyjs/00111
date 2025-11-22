from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Mapping

import numpy as np


@dataclass
class ReversalConfig:
    boll_percent_weight: float = 0.4
    divergence_weight: float = 0.4
    stochastic_weight: float = 0.2


class ReversalIndicatorSuite:
    """Detects short-term reversal probabilities."""

    def __init__(self, config: ReversalConfig | None = None) -> None:
        self._config = config or ReversalConfig()

    def compute_score(self, features: Mapping[str, Any]) -> Dict[str, Any]:
        """
        Negative scores imply potential tops, positive scores indicate bottoms.
        """

        intervals = features.get("intervals", {})
        primary = intervals.get("15m", {})
        latest = primary.get("latest", {})
        candles = primary.get("candles", [])

        components = {
            "boll_percent": self._bollinger_percent_component(latest),
            "obv_divergence": self._obv_divergence_component(latest),
            "stoch_rsi": self._stoch_component(latest),
        }

        weighted_sum = (
            components["boll_percent"] * self._config.boll_percent_weight
            + components["obv_divergence"] * self._config.divergence_weight
            + components["stoch_rsi"] * self._config.stochastic_weight
        )
        total_weight = (
            self._config.boll_percent_weight
            + self._config.divergence_weight
            + self._config.stochastic_weight
        )
        score = weighted_sum / total_weight if total_weight else 0.0
        score = float(np.clip(score, -1.0, 1.0))

        return {"score": score, "details": components}

    def _bollinger_percent_component(self, latest: Mapping[str, Any]) -> float:
        upper = latest.get("bb_upper")
        lower = latest.get("bb_lower")
        close = latest.get("close")
        if None in {upper, lower, close} or upper == lower:
            return 0.0
        percent_b = (close - lower) / (upper - lower)
        normalized = (percent_b - 0.5) * 2
        return float(np.clip(normalized, -1.0, 1.0))

    def _obv_divergence_component(self, latest: Mapping[str, Any]) -> float:
        obv = latest.get("obv")
        obv_ma = latest.get("obv_ma")
        momentum = latest.get("momentum")
        if None in {obv, obv_ma}:
            return 0.0
        divergence = (obv - obv_ma) / (abs(obv_ma) + 1e-6)
        # 如果价格动量与OBV方向相反，则放大反转信号
        if momentum is not None and momentum < 0 and divergence > 0:
            divergence *= -1
        return float(np.tanh(divergence))

    def _stoch_component(self, latest: Mapping[str, Any]) -> float:
        k_value = latest.get("kdj_k")
        d_value = latest.get("kdj_d")
        if None in {k_value, d_value}:
            return 0.0
        spread = float(k_value) - float(d_value)
        level = (float(k_value) + float(d_value)) / 2
        if level < 20:
            return float(np.clip(0.5 + spread / 100, 0.0, 1.0))
        if level > 80:
            return float(np.clip(-0.5 + spread / 100, -1.0, 0.0))
        return float(np.tanh(spread / 50))
