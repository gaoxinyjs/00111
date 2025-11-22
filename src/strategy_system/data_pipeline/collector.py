from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Sequence


@dataclass
class MarketDataRequest:
    """Represents the configuration for a single market data pull."""

    symbol: str
    intervals: Sequence[str]
    limit: int = 200


class MarketDataCollector:
    """
    Fetches candle data for multiple symbols/intervals.

    This skeleton wires into the existing OKX/data clients later. Right now it
    only describes the public interface expected by the strategy runner.
    """

    def __init__(self, client: Any) -> None:
        self._client = client

    def collect(self, requests: List[MarketDataRequest]) -> Dict[str, Dict[str, Any]]:
        """
        Pulls data for each symbol/interval pair.

        Returns a nested mapping: {symbol: {interval: dataframe_like}}. Concrete
        implementations can return pandas DataFrames or custom structures.
        """

        raise NotImplementedError("Implement exchange data fetching logic")
