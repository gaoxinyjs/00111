from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Mapping


@dataclass
class VWAPConfig:
    anchor: str = "weekly"
    band_std: float = 1.0


class VWAPIndicatorSuite:
    """Anchored VWAP and VWAP bands based confidence scoring."""

    def __init__(self, config: VWAPConfig | None = None) -> None:
        self._config = config or VWAPConfig()

    def compute_score(self, features: Mapping[str, Any]) -> Dict[str, Any]:
        """
        Highlights whether price is respecting key VWAP levels and bands.
        """

        raise NotImplementedError("Implement anchored VWAP scoring")
