from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Mapping


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

        raise NotImplementedError("Implement multi-timeframe RSI scoring")
