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

        raise NotImplementedError("Implement weighted/贝叶斯融合逻辑")
