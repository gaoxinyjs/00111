from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List

from .data_pipeline import FeatureEngineer, MarketDataCollector, MarketDataRequest
from .execution import PositionManager, RiskController
from .indicators import (
    MultiTimeframeMomentumSuite,
    ReversalIndicatorSuite,
    StructureIndicatorSuite,
    TrendIndicatorSuite,
    VWAPIndicatorSuite,
    VolumeIndicatorSuite,
)
from .scoring import IndicatorScoringEngine, SignalFusionEngine
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
    ) -> None:
        self._collector = data_collector
        self._feature_engineer = feature_engineer
        self._indicator_modules = indicator_modules
        self._scoring_engine = scoring_engine
        self._fusion_engine = fusion_engine
        self._position_manager = position_manager
        self._risk_controller = risk_controller
        self._env_keys = env_keys or load_env_keys()

    def run_cycle(self, context: StrategyContext) -> Dict[str, Any]:
        """
        Executes one 15m decision cycle. Intended to be called by an external scheduler.
        """

        raise NotImplementedError("Implement orchestration logic (data→features→scores→orders)")

    @classmethod
    def build_default(cls, client: Any) -> "StrategyRunner":
        """
        Convenience constructor wiring default modules and configs.
        """

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
        scoring_engine = IndicatorScoringEngine()
        fusion_engine = SignalFusionEngine()
        position_manager = PositionManager()
        risk_controller = RiskController()
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
        )
