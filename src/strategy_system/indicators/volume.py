from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Mapping

import numpy as np


@dataclass
class VolumeConfig:
    obv_weight: float = 0.35
    vpt_weight: float = 0.25
    cvd_weight: float = 0.25
    mfi_weight: float = 0.15


class VolumeIndicatorSuite:
    """Evaluates volume/flow dynamics."""

    def __init__(self, config: VolumeConfig | None = None) -> None:
        self._config = config or VolumeConfig()

    def compute_score(self, features: Mapping[str, Any]) -> Dict[str, Any]:
        """
        Returns normalized score highlighting accumulation/distribution signals.
        """

        intervals = features.get("intervals", {})
        primary = intervals.get("15m", {})
        candles = primary.get("candles", [])
        latest = primary.get("latest", {})

        components = {
            "obv": self._obv_component(latest),
            "vpt": self._vpt_component(candles),
            "cvd": self._cvd_component(candles),
            "mfi": self._mfi_component(candles),
        }

        weighted_sum = (
            components["obv"] * self._config.obv_weight
            + components["vpt"] * self._config.vpt_weight
            + components["cvd"] * self._config.cvd_weight
            + components["mfi"] * self._config.mfi_weight
        )
        total_weight = (
            self._config.obv_weight
            + self._config.vpt_weight
            + self._config.cvd_weight
            + self._config.mfi_weight
        )
        score = weighted_sum / total_weight if total_weight else 0.0
        score = float(np.clip(score, -1.0, 1.0))

        return {"score": score, "details": components}

    # ------------------------------------------------------------------ #
    def _obv_component(self, latest: Mapping[str, Any]) -> float:
        obv = latest.get("obv")
        obv_ma = latest.get("obv_ma")
        if obv is None or obv_ma is None:
            return 0.0
        divergence = (obv - obv_ma) / (abs(obv_ma) + 1e-6)
        return float(np.tanh(divergence))

    def _vpt_component(self, candles: List[Mapping[str, Any]], lookback: int = 60) -> float:
        if len(candles) < 3:
            return 0.0
        subset = candles[-lookback:]
        vpt_values = []
        vpt = 0.0
        prev_close = subset[0]["close"]
        for candle in subset[1:]:
            close = candle["close"]
            if prev_close:
                pct_change = (close - prev_close) / prev_close
            else:
                pct_change = 0.0
            vpt += pct_change * candle.get("volume", 0.0)
            vpt_values.append(vpt)
            prev_close = close

        if len(vpt_values) < 2:
            return 0.0
        slope = vpt_values[-1] - vpt_values[-min(len(vpt_values), 5)]
        baseline = abs(vpt_values[-min(len(vpt_values), 5)]) + 1e-6
        return float(np.tanh(slope / baseline))

    def _cvd_component(self, candles: List[Mapping[str, Any]], lookback: int = 40) -> float:
        if len(candles) < 3:
            return 0.0
        subset = candles[-lookback:]
        deltas = []
        total_volume = 0.0
        for candle in subset:
            open_price = candle.get("open", 0.0)
            close_price = candle.get("close", 0.0)
            volume = candle.get("volume", 0.0)
            total_volume += volume
            direction = 1 if close_price >= open_price else -1
            deltas.append(direction * volume)
        if total_volume == 0:
            return 0.0
        imbalance = sum(deltas) / total_volume
        return float(np.clip(imbalance, -1.0, 1.0))

    def _mfi_component(self, candles: List[Mapping[str, Any]], period: int = 14) -> float:
        if len(candles) <= period:
            return 0.0
        typical_prices = []
        raw_money_flow = []
        for candle in candles[-(period + 1):]:
            high = candle.get("high", 0.0)
            low = candle.get("low", 0.0)
            close = candle.get("close", 0.0)
            volume = candle.get("volume", 0.0)
            tp = (high + low + close) / 3
            typical_prices.append(tp)
            raw_money_flow.append(tp * volume)

        positive_flow = 0.0
        negative_flow = 0.0
        for idx in range(1, len(typical_prices)):
            if typical_prices[idx] > typical_prices[idx - 1]:
                positive_flow += raw_money_flow[idx]
            else:
                negative_flow += raw_money_flow[idx]

        if negative_flow == 0:
            return 0.9

        money_flow_ratio = positive_flow / negative_flow if negative_flow else 0
        mfi = 100 - (100 / (1 + money_flow_ratio))
        normalized = (mfi - 50) / 50
        return float(np.clip(normalized, -1.0, 1.0))
