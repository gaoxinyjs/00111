from __future__ import annotations

from dataclasses import dataclass, fields
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from ..analysis.deepseek_client import DeepSeekClient
from ..core.config_manager import get_config_manager
from ..core.logger import get_logger
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
from .scoring import DeepSeekSignal, FusionConfig, IndicatorScoringEngine, ScoringWeights, SignalFusionEngine
from .env_loader import StrategyEnvKeys, load_env_keys
from .state_store import StateStore


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
        deepseek_client: DeepSeekClient | None = None,
    ) -> None:
        self._logger = get_logger("strategy.runner")
        self._collector = data_collector
        self._feature_engineer = feature_engineer
        self._indicator_modules = indicator_modules
        self._scoring_engine = scoring_engine
        self._fusion_engine = fusion_engine
        self._position_manager = position_manager
        self._risk_controller = risk_controller
        self._env_keys = env_keys or load_env_keys()
        self._strategy_config = strategy_config
        self._deepseek_client = deepseek_client or DeepSeekClient()
        self._deepseek_cache: Dict[str, Dict[str, Any]] = {}
        self._active_position: Optional[Dict[str, Any]] = None
        root = Path(__file__).resolve().parents[2]
        self._state_store = StateStore(path=root / "data" / "strategy_state.json")
        loaded_state = self._state_store.load()
        self._active_position = loaded_state.get("active_position")
        self._last_signals: Dict[str, Any] = loaded_state.get("last_signals", {})
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

        market_requests = [
            MarketDataRequest(symbol=symbol, intervals=context.intervals, limit=context.data_limit)
            for symbol in context.symbols
        ]
        raw_market = self._collector.collect(market_requests)
        features = self._feature_engineer.build_features(raw_market)
        if not features:
            self._logger.warning("Feature engineering produced empty result set")
            return {"status": "no_data", "signals": {}}

        symbol_results: Dict[str, Dict[str, Any]] = {}
        for symbol, feature_payload in features.items():
            indicator_outputs = self._evaluate_indicators(symbol, feature_payload)
            indicator_score = self._scoring_engine.score(indicator_outputs)
            deepseek_signal = self._obtain_deepseek_signal(feature_payload)
            fusion_result = self._fusion_engine.fuse(indicator_score["indicator_score"], deepseek_signal)
            symbol_results[symbol] = {
                "indicator_outputs": indicator_outputs,
                "indicator_score": indicator_score,
                "deepseek_signal": {
                    "direction": deepseek_signal.direction,
                    "confidence": deepseek_signal.confidence,
                },
                "final_signal": fusion_result,
            }

        active_feedback = self._evaluate_active_position(symbol_results, features)
        best_symbol, best_payload = self._select_best_symbol(symbol_results)

        if not best_symbol or best_payload["final_signal"]["direction"] == "hold":
            self._persist_state(symbol_results)
            return {
                "status": "no_trade",
                "signals": symbol_results,
                "position": self._active_position,
                "position_feedback": active_feedback,
            }

        entry_price = features[best_symbol]["latest_price"]
        final_score = float(best_payload["final_signal"]["score"])
        order = self._position_manager.build_order(
            best_symbol, best_payload["final_signal"]["direction"], entry_price, final_score
        )

        if not order:
            return {
                "status": "no_trade",
                "signals": symbol_results,
                "position_feedback": active_feedback,
            }

        position_change: Dict[str, Any] = {}
        if self._active_position:
            position_change["closed"] = self._active_position

        order["opened_at"] = datetime.utcnow().isoformat()
        self._active_position = order
        position_change["opened"] = order

        self._persist_state(symbol_results)
        return {
            "status": "trade",
            "order": order,
            "signals": symbol_results,
            "position_feedback": active_feedback,
            "position_change": position_change,
        }

    @classmethod
    def build_default(cls, client: Any | None = None) -> "StrategyRunner":
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
        deepseek_client = DeepSeekClient()

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
            deepseek_client=deepseek_client,
        )

    # ------------------------------------------------------------------ #
    def _evaluate_indicators(self, symbol: str, feature_payload: Dict[str, Any]) -> Dict[str, Any]:
        results: Dict[str, Any] = {}
        for name, module in self._indicator_modules.items():
            try:
                results[name] = module.compute_score(feature_payload)
            except Exception as exc:  # pragma: no cover - defensive
                self._logger.warning("Indicator %s failed for %s: %s", name, symbol, exc)
                results[name] = {"score": 0.0, "error": str(exc)}
        return results

    def _obtain_deepseek_signal(self, feature_payload: Dict[str, Any]) -> DeepSeekSignal:
        market_data = feature_payload.get("deepseek_market_data", {})
        if not market_data:
            return DeepSeekSignal(direction="hold", confidence=0.0)
        symbol = feature_payload.get("symbol")
        cache_entry = self._deepseek_cache.get(symbol or "")
        if cache_entry:
            age = datetime.utcnow() - cache_entry["timestamp"]
            if age <= timedelta(minutes=2):
                return cache_entry["signal"]

        try:
            ai_signal = self._deepseek_client.generate_signal(market_data)
            direction = ai_signal.get("direction", "hold")
            confidence = float(ai_signal.get("confidence", 0.0) or 0.0)
            confidence = max(0.0, min(1.0, confidence))
            if direction not in {"long", "short"}:
                direction = "hold"
            signal = DeepSeekSignal(direction=direction, confidence=confidence)
            if symbol:
                self._deepseek_cache[symbol] = {"timestamp": datetime.utcnow(), "signal": signal}
            return signal
        except Exception as exc:  # pragma: no cover - defensive
            symbol = feature_payload.get("symbol", "UNKNOWN")
            self._logger.warning("DeepSeek signal failed for %s: %s", symbol, exc)
            return DeepSeekSignal(direction="hold", confidence=0.0)

    def _select_best_symbol(
        self, symbol_results: Dict[str, Dict[str, Any]]
    ) -> Tuple[Optional[str], Optional[Dict[str, Any]]]:
        best_symbol: Optional[str] = None
        best_payload: Optional[Dict[str, Any]] = None
        best_strength = 0.0

        for symbol, payload in symbol_results.items():
            final_signal = payload["final_signal"]
            direction = final_signal.get("direction")
            if direction == "hold":
                continue
            strength = abs(float(final_signal.get("score", 0.0)))
            if strength > best_strength:
                best_strength = strength
                best_symbol = symbol
                best_payload = payload

        return best_symbol, best_payload

    def _evaluate_active_position(
        self,
        symbol_results: Dict[str, Dict[str, Any]],
        features: Dict[str, Dict[str, Any]],
    ) -> Optional[Dict[str, Any]]:
        if not self._active_position:
            return None

        symbol = self._active_position.get("symbol")
        if symbol not in symbol_results or symbol not in features:
            return None

        position_state = dict(self._active_position)
        position_state["current_price"] = features[symbol]["latest_price"]
        deepseek_view = {
            "direction": symbol_results[symbol]["deepseek_signal"]["direction"],
            "confidence": symbol_results[symbol]["deepseek_signal"]["confidence"],
        }
        feedback = self._risk_controller.evaluate_position(position_state, deepseek_view)

        if feedback["action"] == "close":
            self._active_position = None
        elif feedback["action"] == "tighten":
            self._active_position["stop_loss"] = feedback["new_stop"]

        return feedback

    def _persist_state(self, symbol_results: Dict[str, Dict[str, Any]]) -> None:
        last_signals = {}
        timestamp = datetime.utcnow().isoformat()
        for symbol, payload in symbol_results.items():
            last_signals[symbol] = {
                "final_signal": payload.get("final_signal"),
                "indicator_score": payload.get("indicator_score"),
                "timestamp": timestamp,
            }
        self._state_store.save(
            {
                "active_position": self._active_position,
                "last_signals": last_signals,
            }
        )

    def run_monitor_cycle(self) -> Dict[str, Any]:
        """
        Lightweight 1-minute monitor that refreshes active position data only.
        """

        if not self._active_position:
            return {"status": "no_position"}

        symbol = self._active_position.get("symbol")
        if not symbol:
            return {"status": "invalid_position"}

        request = MarketDataRequest(symbol=symbol, intervals=["15m", "4h"], limit=120)
        raw_market = self._collector.collect([request])
        features = self._feature_engineer.build_features(raw_market)
        feature_payload = features.get(symbol)
        if not feature_payload:
            return {"status": "no_data"}

        indicator_outputs = self._evaluate_indicators(symbol, feature_payload)
        indicator_score = self._scoring_engine.score(indicator_outputs)
        deepseek_signal = self._obtain_deepseek_signal(feature_payload)
        symbol_result = {
            "indicator_outputs": indicator_outputs,
            "indicator_score": indicator_score,
            "deepseek_signal": {
                "direction": deepseek_signal.direction,
                "confidence": deepseek_signal.confidence,
            },
            "final_signal": self._fusion_engine.fuse(indicator_score["indicator_score"], deepseek_signal),
        }
        symbol_results = {symbol: symbol_result}
        feedback = self._evaluate_active_position(symbol_results, {symbol: feature_payload})
        self._persist_state(symbol_results)
        return {"status": "monitor", "position_feedback": feedback, "signals": symbol_results}
