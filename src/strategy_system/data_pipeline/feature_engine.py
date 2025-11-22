from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Mapping


@dataclass
class FeatureConfig:
    """Configures which indicators are required for downstream scoring."""

    enable_vwap: bool = True
    enable_bands: bool = True
    enable_volume_flows: bool = True


class FeatureEngineer:
    """
    Converts raw candle data into indicator-friendly feature sets.

    Indicator modules consume the normalized payload produced here instead of
    recalculating the same statistics repeatedly.
    """

    def __init__(self, config: FeatureConfig | None = None) -> None:
        self._config = config or FeatureConfig()

    def build_features(self, market_data: Mapping[str, Mapping[str, Any]]) -> Dict[str, Dict[str, Any]]:
        """
        Parameters
        ----------
        market_data: dict
            Nested dict output from MarketDataCollector.

        Returns
        -------
        dict
            {symbol: {interval: feature_payload}}
        """

        raise NotImplementedError("Implement feature engineering logic")
