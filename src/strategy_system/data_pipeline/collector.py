from __future__ import annotations

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any, Dict, List, Mapping, Optional, Sequence

from src.core.logger import get_logger
from src.data.okx_client import OKXClient


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

    def __init__(self, client: Any | None = None) -> None:
        self._client = client or OKXClient()
        self._logger = get_logger("strategy.market_collector")

    def collect(self, requests: List[MarketDataRequest]) -> Dict[str, Dict[str, Any]]:
        """
        Pulls data for each symbol/interval pair.

        Returns a nested mapping: {symbol: {interval: dataframe_like}}. Concrete
        implementations can return pandas DataFrames or custom structures.
        """

        aggregated: Dict[str, Dict[str, Any]] = {}
        for request in requests:
            symbol_payload = {
                "symbol": request.symbol,
                "intervals": {},
            }

            ticker_info = self._fetch_ticker(request.symbol)
            if ticker_info:
                symbol_payload["ticker"] = ticker_info

            for interval in request.intervals:
                candles = self._fetch_interval(request.symbol, interval, request.limit)
                if not candles:
                    continue
                symbol_payload["intervals"][interval] = candles

            if not symbol_payload["intervals"]:
                self._logger.warning(
                    "No candle data collected for %s (intervals=%s)",
                    request.symbol,
                    ",".join(request.intervals),
                )
                continue

            aggregated[request.symbol] = symbol_payload

        return aggregated

    # --------------------------------------------------------------------- #
    # Internal helpers
    # --------------------------------------------------------------------- #
    def _fetch_interval(self, symbol: str, interval: str, limit: int) -> List[Dict[str, Any]]:
        method = getattr(self._client, "get_kline", None)
        if method is None:
            raise AttributeError("Client does not expose get_kline()")

        try:
            raw_candles = method(symbol, interval, limit)
        except RuntimeError as exc:
            # 兼容在事件循环中的同步调用限制，自动回退到异步方法
            if "不能使用同步方法" in str(exc):
                coro_method = getattr(self._client, "async_get_kline", None)
                if coro_method is None:
                    raise
                raw_candles = self._run_async(coro_method(symbol, interval, limit))
            else:
                raise

        if not raw_candles:
            return []

        normalized: List[Dict[str, Any]] = []
        for entry in raw_candles:
            try:
                candle = self._normalize_candle(symbol, interval, entry)
            except (ValueError, TypeError):
                continue
            normalized.append(candle)
        return normalized

    def _fetch_ticker(self, symbol: str) -> Dict[str, Any]:
        method = getattr(self._client, "get_ticker", None)
        if method is None:
            return {}

        try:
            raw = method(symbol)
        except RuntimeError as exc:
            if "不能使用同步方法" in str(exc):
                coro_method = getattr(self._client, "async_get_ticker", None)
                if coro_method is None:
                    self._logger.warning("Client lacks async_get_ticker(), ticker skipped for %s", symbol)
                    return {}
                raw = self._run_async(coro_method(symbol))
            else:
                self._logger.warning("Failed to fetch ticker for %s: %s", symbol, exc)
                return {}
        except Exception as exc:
            self._logger.warning("Failed to fetch ticker for %s: %s", symbol, exc)
            return {}

        # OKX返回列表
        if isinstance(raw, list):
            raw = raw[0] if raw else {}

        if not isinstance(raw, Mapping):
            return {}

        try:
            price = float(raw.get("last", 0))
            open_24h = float(raw.get("open24h", 0))
            change_pct = float(raw.get("changePercent24h", 0)) if raw.get("changePercent24h") is not None else None
        except (TypeError, ValueError):
            price = 0.0
            open_24h = 0.0
            change_pct = None

        if change_pct is None and open_24h:
            try:
                change_pct = ((price - open_24h) / open_24h) * 100 if open_24h else 0.0
            except ZeroDivisionError:
                change_pct = 0.0

        ticker = {
            "symbol": symbol,
            "price": price,
            "bid_price": self._safe_float(raw.get("bidPx")),
            "ask_price": self._safe_float(raw.get("askPx")),
            "volume_24h": self._safe_float(raw.get("vol24h")),
            "change_24h": change_pct if change_pct is not None else 0.0,
            "high_24h": self._safe_float(raw.get("high24h")),
            "low_24h": self._safe_float(raw.get("low24h")),
            "timestamp": raw.get("ts"),
        }
        return ticker

    def _normalize_candle(self, symbol: str, interval: str, entry: Any) -> Dict[str, Any]:
        if isinstance(entry, Mapping):
            timestamp = int(entry.get("ts") or entry.get("timestamp"))
            open_price = float(entry.get("open"))
            high_price = float(entry.get("high"))
            low_price = float(entry.get("low"))
            close_price = float(entry.get("close"))
            volume = float(entry.get("volume"))
        elif isinstance(entry, (list, tuple)) and len(entry) >= 6:
            timestamp = int(entry[0])
            open_price = float(entry[1])
            high_price = float(entry[2])
            low_price = float(entry[3])
            close_price = float(entry[4])
            volume = float(entry[5])
        else:
            raise ValueError("Unexpected candle format")

        return {
            "symbol": symbol,
            "interval": interval,
            "timestamp": timestamp,
            "open": open_price,
            "high": high_price,
            "low": low_price,
            "close": close_price,
            "volume": volume,
        }

    def _safe_float(self, value: Any, default: float = 0.0) -> float:
        try:
            if value is None:
                return default
            return float(value)
        except (TypeError, ValueError):
            return default

    def _run_async(self, coro: Any) -> Any:
        """
        Runs coroutine even when the current thread already has a running event loop
        (common inside notebooks or async schedulers) by spinning up a dedicated
        temporary loop.
        """

        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                temp_loop = asyncio.new_event_loop()
                try:
                    return temp_loop.run_until_complete(coro)
                finally:
                    temp_loop.close()
        except RuntimeError:
            # 没有当前事件循环，直接使用asyncio.run
            pass

        return asyncio.run(coro)
