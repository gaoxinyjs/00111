from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Mapping

import numpy as np
import pandas as pd


@dataclass
class StructureConfig:
    atr_multiplier: float = 1.5
    squeeze_threshold: float = 0.25
    structure_weight: float = 0.5
    volatility_weight: float = 0.5


class StructureIndicatorSuite:
    """Tracks market structure (HH/HL) and volatility regimes."""

    def __init__(self, config: StructureConfig | None = None) -> None:
        self._config = config or StructureConfig()

    def compute_score(self, features: Mapping[str, Any]) -> Dict[str, Any]:
        """
        Combines ATR 通道、Bollinger/Keltner、TTM Squeeze、结构破坏等信号。
        """

        intervals = features.get("intervals", {})
        primary = intervals.get("15m", {})
        df: pd.DataFrame | None = primary.get("df")
        candles = primary.get("candles", [])
        latest = primary.get("latest", {})

        components = {
            "structure": self._structure_component(candles),
            "volatility": self._volatility_component(df, latest),
        }

        score = (
            components["structure"] * self._config.structure_weight
            + components["volatility"] * self._config.volatility_weight
        )
        score /= (self._config.structure_weight + self._config.volatility_weight)
        score = float(np.clip(score, -1.0, 1.0))

        return {"score": score, "details": components}

    # ------------------------------------------------------------------ #
    def _structure_component(self, candles: List[Mapping[str, Any]], lookback: int = 6) -> float:
        if len(candles) < lookback:
            return 0.0
        recent = candles[-lookback:]
        highs = [float(c.get("high", 0.0)) for c in recent]
        lows = [float(c.get("low", 0.0)) for c in recent]

        hh = all(x < y for x, y in zip(highs, highs[1:]))
        ll = all(x > y for x, y in zip(highs, highs[1:]))
        hl = all(x < y for x, y in zip(lows, lows[1:]))
        lh = all(x > y for x, y in zip(lows, lows[1:]))

        if hh and hl:
            return 1.0
        if ll and lh:
            return -1.0

        # fallback: compare last swing
        last_high_diff = highs[-1] - highs[-2]
        last_low_diff = lows[-1] - lows[-2]
        structure_score = 0.0
        if last_high_diff > 0 and last_low_diff > 0:
            structure_score = 0.6
        elif last_high_diff < 0 and last_low_diff < 0:
            structure_score = -0.6

        return float(np.clip(structure_score, -1.0, 1.0))

    def _volatility_component(self, df: pd.DataFrame | None, latest: Mapping[str, Any]) -> float:
        if df is None or df.empty:
            atr_pct = latest.get("atr_pct")
            if atr_pct is None:
                return 0.0
            atr_score = float(np.tanh((atr_pct - 2) / 4))
            return atr_score

        tail = df.tail(40)
        if "bb_width" in tail.columns and tail["bb_width"].notna().any():
            bb_width = float(tail["bb_width"].iloc[-1])
        else:
            bb_width = 0.0

        atr_pct = float(tail["atr_pct"].iloc[-1]) if "atr_pct" in tail.columns else 0.0
        squeeze = bb_width - (atr_pct / 100)
        squeeze_score = float(np.tanh((self._config.squeeze_threshold - squeeze) * 5))

        atr_score = float(np.tanh((atr_pct - 3) / 3))

        return np.clip(0.6 * squeeze_score + 0.4 * atr_score, -1.0, 1.0)
