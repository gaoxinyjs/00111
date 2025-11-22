from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Mapping


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

        raise NotImplementedError("Implement OBV/VPT/CVD/MFI scoring logic")
