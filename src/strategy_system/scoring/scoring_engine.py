from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Mapping


@dataclass
class ScoringWeights:
    trend: float = 0.3
    volume: float = 0.2
    structure: float = 0.2
    multi_timeframe: float = 0.15
    vwap: float = 0.1
    reversal: float = -0.05

    def as_dict(self) -> Dict[str, float]:
        return {
            "trend": self.trend,
            "volume": self.volume,
            "structure": self.structure,
            "multi_timeframe": self.multi_timeframe,
            "vwap": self.vwap,
            "reversal": self.reversal,
        }


@dataclass
class IndicatorScoringEngine:
    """
    Converts indicator suite outputs into a single normalized score.
    """

    weights: ScoringWeights = field(default_factory=ScoringWeights)

    def score(self, indicator_results: Mapping[str, Mapping[str, float]]) -> Dict[str, float]:
        """
        Parameters
        ----------
        indicator_results: dict
            {category: {"score": value, ...}}

        Returns
        -------
        dict
            {"indicator_score": float, "breakdown": {...}}
        """

        weights = self.weights.as_dict()
        weighted_sum = 0.0
        total_weight = 0.0
        breakdown: Dict[str, Dict[str, float]] = {}

        for category, result in indicator_results.items():
            raw_score = float(result.get("score", 0.0))
            weight = weights.get(category, 0.0)
            weighted_value = raw_score * weight
            weighted_sum += weighted_value
            total_weight += abs(weight)
            breakdown[category] = {
                "raw": raw_score,
                "weight": weight,
                "weighted": weighted_value,
            }

        indicator_score = weighted_sum / total_weight if total_weight else 0.0
        indicator_score = max(-1.0, min(1.0, indicator_score))

        return {"indicator_score": indicator_score, "breakdown": breakdown}
