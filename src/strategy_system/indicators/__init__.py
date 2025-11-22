"""
Custom indicator suites organized by analytical theme. Each module exposes a
`compute_*_score` function returning both indicator specifics and a normalized
score (-1 to 1) for fusion.
"""

from .trend import TrendIndicatorSuite
from .volume import VolumeIndicatorSuite
from .structure import StructureIndicatorSuite
from .multi_timeframe import MultiTimeframeMomentumSuite
from .vwap import VWAPIndicatorSuite
from .reversal import ReversalIndicatorSuite

__all__ = [
    "TrendIndicatorSuite",
    "VolumeIndicatorSuite",
    "StructureIndicatorSuite",
    "MultiTimeframeMomentumSuite",
    "VWAPIndicatorSuite",
    "ReversalIndicatorSuite",
]
