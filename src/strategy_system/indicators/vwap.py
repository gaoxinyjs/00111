from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Mapping, Tuple

import numpy as np


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

        intervals = features.get("intervals", {})
        primary = intervals.get("15m", {})
        candles = primary.get("candles", [])
        latest = primary.get("latest", {})

        vwap_value, band_width = self._compute_vwap_and_band(candles)
        close_price = latest.get("close")
        if vwap_value is None or close_price is None:
            return {"score": 0.0, "details": {"vwap": None, "band": None}}

        deviation = (close_price - vwap_value) / (band_width + 1e-6)
        score = float(np.tanh(deviation))
        details = {
            "vwap": vwap_value,
            "band": band_width,
            "price": close_price,
        }
        return {"score": score, "details": details}

    def _compute_vwap_and_band(self, candles: List[Mapping[str, Any]]) -> Tuple[float | None, float]:
        if not candles:
            return None, 0.0

        cumulative_pv = 0.0
        cumulative_volume = 0.0
        deviations = []

        for candle in candles:
            high = float(candle.get("high", 0.0))
            low = float(candle.get("low", 0.0))
            close = float(candle.get("close", 0.0))
            volume = float(candle.get("volume", 0.0))
            typical_price = (high + low + close) / 3
            cumulative_pv += typical_price * volume
            cumulative_volume += volume
            if cumulative_volume > 0:
                current_vwap = cumulative_pv / cumulative_volume
                deviations.append((close - current_vwap) ** 2)

        if cumulative_volume == 0:
            return None, 0.0

        final_vwap = cumulative_pv / cumulative_volume
        std_dev = np.sqrt(np.mean(deviations)) if deviations else 0.0
        band = self._config.band_std * std_dev
        return final_vwap, band
