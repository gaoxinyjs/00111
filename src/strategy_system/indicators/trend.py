from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Mapping

import numpy as np


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

        intervals = features.get("intervals", {})
        short = self._latest(intervals, "15m")
        mid = self._latest(intervals, "4h")

        components = {
            "macd": self._macd_component(short, mid),
            "ema_ribbon": self._ema_ribbon_component(short),
            "supertrend": self._supertrend_component(short),
            "adx": self._adx_component(short),
        }

        weighted_sum = (
            components["macd"] * self._config.macd_weight
            + components["ema_ribbon"] * self._config.ema_weight
            + components["supertrend"] * self._config.supertrend_weight
            + components["adx"] * self._config.adx_weight
        )
        total_weight = (
            self._config.macd_weight
            + self._config.ema_weight
            + self._config.supertrend_weight
            + self._config.adx_weight
        )
        score = weighted_sum / total_weight if total_weight else 0.0
        score = float(np.clip(score, -1.0, 1.0))

        return {"score": score, "details": components}

    # ------------------------------------------------------------------ #
    # Component calculators
    # ------------------------------------------------------------------ #
    def _latest(self, intervals: Mapping[str, Dict[str, Any]], key: str) -> Mapping[str, Any]:
        payload = intervals.get(key)
        return payload.get("latest", {}) if payload else {}

    def _macd_component(self, short: Mapping[str, Any], mid: Mapping[str, Any]) -> float:
        macd = short.get("macd")
        macd_signal = short.get("macd_signal")
        long_macd = mid.get("macd") if mid else None
        if macd is None or macd_signal is None:
            return 0.0

        short_diff = macd - macd_signal
        short_component = float(np.tanh(short_diff * 5))

        long_component = 0.0
        if long_macd is not None:
            long_component = float(np.tanh(long_macd * 2))

        return 0.7 * short_component + 0.3 * long_component

    def _ema_ribbon_component(self, latest: Mapping[str, Any]) -> float:
        ema_fast = latest.get("ema_12")
        ema_mid = latest.get("ema_26")
        ema_slow = latest.get("ema_50")
        if None in {ema_fast, ema_mid, ema_slow}:
            return 0.0

        if ema_fast > ema_mid > ema_slow:
            return 1.0
        if ema_fast < ema_mid < ema_slow:
            return -1.0

        spread_fast_mid = ema_fast - ema_mid
        spread_mid_slow = ema_mid - ema_slow
        normalized = float(np.tanh((spread_fast_mid + spread_mid_slow) / max(abs(ema_mid), 1e-6)))
        return normalized

    def _supertrend_component(self, latest: Mapping[str, Any]) -> float:
        atr = latest.get("atr")
        close = latest.get("close")
        ema = latest.get("ema_50")
        if None in {atr, close, ema} or atr == 0:
            return 0.0

        distance = (float(close) - float(ema)) / float(atr)
        return float(np.tanh(distance))

    def _adx_component(self, latest: Mapping[str, Any]) -> float:
        adx = latest.get("adx")
        plus_di = latest.get("plus_di")
        minus_di = latest.get("minus_di")
        if None in {adx, plus_di, minus_di}:
            return 0.0

        adx = float(adx)
        if adx < 15:
            return 0.0

        direction_score = float(np.tanh((plus_di - minus_di) / 20))
        strength_multiplier = min(1.0, (adx - 15) / 20)
        return direction_score * strength_multiplier
