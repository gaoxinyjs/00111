from __future__ import annotations

from dataclasses import dataclass, fields
from typing import Any, Dict, List

from ..core.config_manager import get_config_manager
from .config import StrategyConfig, load_strategy_config
from .data_pipeline import FeatureEngineer, MarketDataCollector, MarketDataRequest
from .execution import PositionManager, PositionSizingConfig, RiskController, RiskConfig
from .indicators import (
    MultiTimeframeMomentumSuite,
    ReversalIndicatorSuite,
    StructureIndicatorSuite,
    TrendIndicatorSuite,
    VWAPIndicatorSuite,
    VolumeIndicatorSuite,
)
from .scoring import FusionConfig, IndicatorScoringEngine, ScoringWeights, SignalFusionEngine
from .env_loader import StrategyEnvKeys, load_env_keys


@dataclass
class StrategyContext:
    symbols: List[str]
    intervals: List[str]
    data_limit: int = 200


class StrategyRunner:
    """
    High-level orchestrator gluing together data ingestion, scoring, and execution.
    """

    def __init__(
        self,
        data_collector: MarketDataCollector,
        feature_engineer: FeatureEngineer,
        indicator_modules: Dict[str, Any],
        scoring_engine: IndicatorScoringEngine,
        fusion_engine: SignalFusionEngine,
        position_manager: PositionManager,
        risk_controller: RiskController,
        env_keys: StrategyEnvKeys | None = None,
        strategy_config: StrategyConfig | None = None,
    ) -> None:
        self._collector = data_collector
        self._feature_engineer = feature_engineer
        self._indicator_modules = indicator_modules
        self._scoring_engine = scoring_engine
        self._fusion_engine = fusion_engine
        self._position_manager = position_manager
        self._risk_controller = risk_controller
        self._env_keys = env_keys or load_env_keys()
        self._strategy_config = strategy_config
        self._default_context = (
            StrategyContext(
                symbols=strategy_config.symbols,
                intervals=strategy_config.intervals,
                data_limit=strategy_config.data_limit,
            )
            if strategy_config
            else None
        )

    def run_cycle(self, context: StrategyContext | None = None) -> Dict[str, Any]:
        """
        Executes one 15m decision cycle. Intended to be called by an external scheduler.
        """

        if context is None:
            if not self._default_context:
                raise ValueError("Strategy context not provided and no default configuration loaded.")
            context = self._default_context

        raise NotImplementedError("Implement orchestration logic (data→features→scores→orders)")

    @classmethod
    def build_default(cls, client: Any) -> "StrategyRunner":
        """
        Convenience constructor wiring default modules and configs.
        """

        config_manager = get_config_manager()
        strategy_cfg = load_strategy_config(config_manager)
        collector = MarketDataCollector(client=client)
        features = FeatureEngineer()
        indicator_modules = {
            "trend": TrendIndicatorSuite(),
            "volume": VolumeIndicatorSuite(),
            "structure": StructureIndicatorSuite(),
            "multi_timeframe": MultiTimeframeMomentumSuite(),
            "vwap": VWAPIndicatorSuite(),
            "reversal": ReversalIndicatorSuite(),
        }
        weight_kwargs: Dict[str, float] = {}
        for field in fields(ScoringWeights):
            if field.name in strategy_cfg.indicator_weights:
                weight_kwargs[field.name] = strategy_cfg.indicator_weights[field.name]
        scoring_weights = ScoringWeights(**weight_kwargs) if weight_kwargs else ScoringWeights()
        scoring_engine = IndicatorScoringEngine(weights=scoring_weights)
        fusion_engine = SignalFusionEngine(
            config=FusionConfig(**strategy_cfg.fusion.as_dict())
        )
        position_manager = PositionManager(
            config=PositionSizingConfig(tiers=strategy_cfg.position_tiers or None)
        )
        risk_controller = RiskController(
            config=RiskConfig(
                minute_check_interval=strategy_cfg.risk.minute_check_interval,
                force_flat_time=strategy_cfg.risk.force_flat_time,
                tp_ratio=strategy_cfg.risk.tp_ratio,
                sl_ratio=strategy_cfg.risk.sl_ratio,
            )
        )
        env_keys = load_env_keys()

        return cls(
            data_collector=collector,
            feature_engineer=features,
            indicator_modules=indicator_modules,
            scoring_engine=scoring_engine,
            fusion_engine=fusion_engine,
            position_manager=position_manager,
            risk_controller=risk_controller,
            env_keys=env_keys,
            strategy_config=strategy_cfg,
        )
