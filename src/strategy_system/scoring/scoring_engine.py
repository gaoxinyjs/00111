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

        raise NotImplementedError("Aggregate weighted indicator scores")
