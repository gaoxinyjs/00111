from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Mapping

import numpy as np

@dataclass
class MultiTimeframeConfig:
    rsi_high_threshold: float = 55.0
    rsi_low_threshold: float = 45.0
    weights: Dict[str, float] | None = None

    def __post_init__(self) -> None:
        if self.weights is None:
            self.weights = {"15m": 0.4, "4h": 0.4, "1d": 0.2}


class MultiTimeframeMomentumSuite:
    """Evaluates RSI/Stoch RSI alignment across multiple periods."""

    def __init__(self, config: MultiTimeframeConfig | None = None) -> None:
        self._config = config or MultiTimeframeConfig()

    def compute_score(self, features: Mapping[str, Any]) -> Dict[str, Any]:
        """
        Produces chain-of-command style signals (e.g., 4h>55 while 15m回踩) to
        refine entries.
        """

        intervals = features.get("intervals", {})
        details: Dict[str, float] = {}

        weighted_sum = 0.0
        total_weight = 0.0
        directions = []

        for timeframe, weight in self._config.weights.items():
            latest = intervals.get(timeframe, {}).get("latest", {})
            rsi = latest.get("rsi")
            if rsi is None:
                continue
            component = self._score_rsi(float(rsi))
            details[timeframe] = component
            weighted_sum += component * weight
            total_weight += weight
            directions.append(np.sign(component))

        alignment_bonus = 0.0
        if directions and all(d > 0 for d in directions):
            alignment_bonus = 0.1
        elif directions and all(d < 0 for d in directions):
            alignment_bonus = -0.1

        base_score = weighted_sum / total_weight if total_weight else 0.0
        score = float(np.clip(base_score + alignment_bonus, -1.0, 1.0))

        return {"score": score, "details": details}

    def _score_rsi(self, rsi: float) -> float:
        if rsi >= self._config.rsi_high_threshold:
            return float(np.tanh((rsi - self._config.rsi_high_threshold) / 10))
        if rsi <= self._config.rsi_low_threshold:
            return float(-np.tanh((self._config.rsi_low_threshold - rsi) / 10))
        midpoint = (self._config.rsi_high_threshold + self._config.rsi_low_threshold) / 2
        return float((rsi - midpoint) / (self._config.rsi_high_threshold - self._config.rsi_low_threshold))
