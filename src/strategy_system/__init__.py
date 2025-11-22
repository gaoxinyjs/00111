"""
Strategy system package hosting modular trading components:

- data_pipeline: market data ingestion and feature generation
- indicators: custom indicator groups producing normalized scores
- scoring: fusion of indicator scores with AI outputs
- execution: position sizing and risk monitoring
- strategy_runner: orchestration entry point
"""

from .strategy_runner import StrategyRunner

__all__ = ["StrategyRunner"]
