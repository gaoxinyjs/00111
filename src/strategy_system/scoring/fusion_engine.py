from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping


@dataclass
class DeepSeekSignal:
    direction: str  # "long", "short", "flat"
    confidence: float  # 0~1 作为先验


@dataclass
class FusionConfig:
    deepseek_weight: float = 0.6
    indicator_weight: float = 0.4
    long_threshold: float = 0.7
    short_threshold: float = -0.7


class SignalFusionEngine:
    """Combines AI prior with indicator likelihood into final trade signals."""

    def __init__(self, config: FusionConfig | None = None) -> None:
        self._config = config or FusionConfig()

    def fuse(self, indicator_score: float, deepseek_signal: DeepSeekSignal) -> Mapping[str, float | str]:
        """
        Returns a dict describing final direction, confidence, and raw scores.
        """

        weights_sum = self._config.deepseek_weight + self._config.indicator_weight
        if weights_sum == 0:
            weights_sum = 1.0

        ai_direction_value = self._direction_to_numeric(deepseek_signal.direction)
        deepseek_component = ai_direction_value * deepseek_signal.confidence

        blended = (
            deepseek_component * self._config.deepseek_weight
            + indicator_score * self._config.indicator_weight
        ) / weights_sum
        blended = float(max(-1.0, min(1.0, blended)))

        direction = "hold"
        if blended >= self._config.long_threshold:
            direction = "long"
        elif blended <= self._config.short_threshold:
            direction = "short"

        result = {
            "score": blended,
            "direction": direction,
            "confidence": min(1.0, abs(blended)),
            "components": {
                "indicator": indicator_score,
                "deepseek_direction": deepseek_signal.direction,
                "deepseek_confidence": deepseek_signal.confidence,
                "deepseek_component": deepseek_component,
            },
        }
        return result

    def _direction_to_numeric(self, direction: str) -> float:
        direction = (direction or "hold").lower()
        if direction == "long":
            return 1.0
        if direction == "short":
            return -1.0
        return 0.0
