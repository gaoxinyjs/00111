from __future__ import annotations

from dataclasses import dataclass, field
from datetime import time
from typing import Dict, List, Optional

from ..core.config_manager import get_config_manager, ConfigManager


@dataclass(frozen=True)
class FusionSettings:
    deepseek_weight: float = 0.6
    indicator_weight: float = 0.4
    long_threshold: float = 0.7
    short_threshold: float = -0.7

    def as_dict(self) -> Dict[str, float]:
        return {
            "deepseek_weight": self.deepseek_weight,
            "indicator_weight": self.indicator_weight,
            "long_threshold": self.long_threshold,
            "short_threshold": self.short_threshold,
        }


@dataclass(frozen=True)
class RiskSettings:
    minute_check_interval: int = 60
    force_flat_time: time = time(hour=23, minute=45)
    tp_ratio: float = 0.06
    sl_ratio: float = 0.03

    @classmethod
    def from_dict(cls, payload: Optional[Dict[str, object]] = None) -> "RiskSettings":
        payload = payload or {}
        force_time = payload.get("force_flat_time", "23:45")
        if isinstance(force_time, str):
            hour, minute = (int(part) for part in force_time.split(":"))
            force_time_obj = time(hour=hour, minute=minute)
        elif isinstance(force_time, time):
            force_time_obj = force_time
        else:
            force_time_obj = cls.force_flat_time

        return cls(
            minute_check_interval=int(payload.get("minute_check_interval", 60)),
            force_flat_time=force_time_obj,
            tp_ratio=float(payload.get("tp_ratio", 0.06)),
            sl_ratio=float(payload.get("sl_ratio", 0.03)),
        )


@dataclass(frozen=True)
class StrategyConfig:
    symbols: List[str] = field(default_factory=list)
    intervals: List[str] = field(default_factory=list)
    data_limit: int = 200
    indicator_weights: Dict[str, float] = field(default_factory=dict)
    fusion: FusionSettings = field(default_factory=FusionSettings)
    position_tiers: Dict[float, float] = field(default_factory=dict)
    risk: RiskSettings = field(default_factory=RiskSettings)

    @classmethod
    def from_dict(cls, payload: Optional[Dict[str, object]]) -> "StrategyConfig":
        payload = payload or {}
        indicator_weights = {
            key: float(value)
            for key, value in (payload.get("indicator_weights") or {}).items()
        }
        fusion = FusionSettings(**(payload.get("fusion") or {}))
        risk = RiskSettings.from_dict(payload.get("risk"))

        tiers_raw = payload.get("position_tiers") or {}
        position_tiers: Dict[float, float] = {}
        for threshold, size in tiers_raw.items():
            try:
                threshold_f = float(threshold)
                size_f = float(size)
            except (TypeError, ValueError):
                continue
            position_tiers[threshold_f] = size_f

        return cls(
            symbols=list(payload.get("symbols", [])),
            intervals=list(payload.get("intervals", [])),
            data_limit=int(payload.get("data_limit", 200)),
            indicator_weights=indicator_weights,
            fusion=fusion,
            position_tiers=position_tiers,
            risk=risk,
        )


def load_strategy_config(config_manager: Optional[ConfigManager] = None) -> StrategyConfig:
    """
    Loads the strategy.yaml contents into a structured dataclass.
    """

    config_manager = config_manager or get_config_manager()
    try:
        raw_config = config_manager.get_config("strategy")
    except KeyError:
        raw_config = {}
    return StrategyConfig.from_dict(raw_config)
