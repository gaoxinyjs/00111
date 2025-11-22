from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Mapping


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

        raise NotImplementedError("Implement Bollinger%B/OBV背离等逻辑")
