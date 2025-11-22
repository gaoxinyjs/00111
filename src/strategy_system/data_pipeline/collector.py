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
    Fetches multi-interval candles plus auxiliary market data (orderbook, funding,
    OI, taker flows, etc.) with caching-based degradation for robustness.
    """

    def __init__(self, client: Any | None = None, orderbook_depth: int = 20) -> None:
        self._client = client or OKXClient()
        self._logger = get_logger("strategy.market_collector")
        self._depth = orderbook_depth
        self._ticker_cache: Dict[str, Dict[str, Any]] = {}
        self._orderbook_cache: Dict[str, Dict[str, Any]] = {}
        self._funding_cache: Dict[str, Dict[str, Any]] = {}
        self._oi_cache: Dict[str, Dict[str, Any]] = {}
        self._taker_cache: Dict[str, Dict[str, Any]] = {}
        self._long_short_cache: Dict[str, Dict[str, Any]] = {}
        self._mark_cache: Dict[str, Dict[str, Any]] = {}
        self._liquidation_cache: Dict[str, Dict[str, Any]] = {}

    def collect(self, requests: List[MarketDataRequest]) -> Dict[str, Dict[str, Any]]:
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
                if candles:
                    symbol_payload["intervals"][interval] = candles

            extras = self._fetch_extras(request.symbol)
            if extras:
                symbol_payload["extras"] = extras

            if not symbol_payload["intervals"]:
                self._logger.warning(
                    "No candle data collected for %s (intervals=%s)",
                    request.symbol,
                    ",".join(request.intervals),
                )
                continue

            aggregated[request.symbol] = symbol_payload

        return aggregated

    # ------------------------------------------------------------------ #
    # Candle helpers
    # ------------------------------------------------------------------ #
    def _fetch_interval(self, symbol: str, interval: str, limit: int) -> List[Dict[str, Any]]:
        try:
            raw_candles = self._call_client("get_kline", "async_get_kline", symbol, interval, limit)
        except Exception as exc:
            self._logger.warning("Kline fetch failed for %s/%s: %s", symbol, interval, exc)
            return []

        normalized: List[Dict[str, Any]] = []
        for entry in raw_candles or []:
            try:
                candle = self._normalize_candle(symbol, interval, entry)
            except (ValueError, TypeError):
                continue
            normalized.append(candle)
        return normalized

    def _fetch_ticker(self, symbol: str) -> Dict[str, Any]:
        try:
            raw = self._call_client("get_ticker", "async_get_ticker", symbol)
        except Exception as exc:
            self._logger.debug("Ticker fetch failed for %s: %s", symbol, exc)
            return self._ticker_cache.get(symbol, {})

        if isinstance(raw, list):
            raw = raw[0] if raw else {}
        if not isinstance(raw, Mapping):
            return self._ticker_cache.get(symbol, {})

        try:
            price = float(raw.get("last", 0))
            open_24h = float(raw.get("open24h", 0))
            change_pct = (
                float(raw.get("changePercent24h", 0)) if raw.get("changePercent24h") is not None else None
            )
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
        self._ticker_cache[symbol] = ticker
        return ticker

    # ------------------------------------------------------------------ #
    # Extras for DeepSeek / signal fusion
    # ------------------------------------------------------------------ #
    def _fetch_extras(self, symbol: str) -> Dict[str, Any]:
        return {
            "orderbook": self._fetch_orderbook(symbol),
            "funding": self._fetch_funding(symbol),
            "open_interest": self._fetch_open_interest(symbol),
            "taker_volume": self._fetch_taker_volume(symbol),
            "long_short_ratio": self._fetch_long_short(symbol),
            "mark_price": self._fetch_mark_price(symbol),
            "liquidations": self._fetch_liquidations(symbol),
        }

    def _fetch_orderbook(self, symbol: str) -> Dict[str, Any]:
        try:
            raw = self._call_client("get_orderbook", "async_get_orderbook", symbol, self._depth)
        except Exception as exc:
            self._logger.debug("Orderbook fetch failed for %s: %s", symbol, exc)
            return self._orderbook_cache.get(symbol, {})

        if isinstance(raw, list):
            raw = raw[0] if raw else {}
        bids = raw.get("bids") or []
        asks = raw.get("asks") or []
        data = {
            "symbol": symbol,
            "bids": [[self._safe_float(px), self._safe_float(sz)] for px, sz, *_ in bids],
            "asks": [[self._safe_float(px), self._safe_float(sz)] for px, sz, *_ in asks],
            "timestamp": raw.get("ts"),
        }
        self._orderbook_cache[symbol] = data
        return data

    def _fetch_funding(self, symbol: str) -> Dict[str, Any]:
        try:
            raw = self._call_client("get_funding_rate", "async_get_funding_rate", symbol)
        except Exception as exc:
            self._logger.debug("Funding fetch failed for %s: %s", symbol, exc)
            return self._funding_cache.get(symbol, {})

        latest = raw[0] if isinstance(raw, list) and raw else {}
        data = {
            "symbol": symbol,
            "current_rate": self._safe_float(latest.get("fundingRate")),
            "next_rate": self._safe_float(latest.get("nextFundingRate")),
            "funding_time": latest.get("fundingTime"),
            "next_funding_time": latest.get("nextFundingTime"),
        }
        self._funding_cache[symbol] = data
        return data

    def _fetch_open_interest(self, symbol: str) -> Dict[str, Any]:
        try:
            raw = self._call_client("get_open_interest", "async_get_open_interest", symbol)
        except Exception as exc:
            self._logger.debug("Open interest fetch failed for %s: %s", symbol, exc)
            return self._oi_cache.get(symbol, {})

        latest = raw[0] if isinstance(raw, list) and raw else {}
        data = {
            "symbol": symbol,
            "amount": self._safe_float(latest.get("oi")),
            "amount_ccy": self._safe_float(latest.get("oiCcy")),
            "timestamp": latest.get("ts"),
        }
        self._oi_cache[symbol] = data
        return data

    def _fetch_taker_volume(self, symbol: str) -> Dict[str, Any]:
        try:
            raw = self._call_client("get_taker_volume", "async_get_taker_volume", symbol, "5m")
        except Exception as exc:
            self._logger.debug("Taker volume fetch failed for %s: %s", symbol, exc)
            return self._taker_cache.get(symbol, {})

        latest = raw[0] if isinstance(raw, list) and raw else {}
        buy_vol = self._safe_float(latest.get("buyVol"))
        sell_vol = self._safe_float(latest.get("sellVol"))
        total = buy_vol + sell_vol
        data = {
            "symbol": symbol,
            "buy_vol": buy_vol,
            "sell_vol": sell_vol,
            "taker_buy_ratio": buy_vol / total if total > 0 else 0.5,
            "timestamp": latest.get("ts"),
        }
        self._taker_cache[symbol] = data
        return data

    def _fetch_long_short(self, symbol: str) -> Dict[str, Any]:
        try:
            raw = self._call_client("get_long_short_ratio", "async_get_long_short_ratio", symbol, "5m")
        except Exception as exc:
            self._logger.debug("Long/short ratio fetch failed for %s: %s", symbol, exc)
            return self._long_short_cache.get(symbol, {})

        latest = raw[0] if isinstance(raw, list) and raw else {}
        data = {
            "symbol": symbol,
            "long_ratio": self._safe_float(latest.get("longAccount")),
            "short_ratio": self._safe_float(latest.get("shortAccount")),
            "long_short_ratio": self._safe_float(latest.get("longAccount"))
            / (self._safe_float(latest.get("shortAccount")) or 1.0),
            "timestamp": latest.get("ts"),
        }
        self._long_short_cache[symbol] = data
        return data

    def _fetch_mark_price(self, symbol: str) -> Dict[str, Any]:
        try:
            raw = self._call_client("get_mark_price", "async_get_mark_price", symbol)
        except Exception as exc:
            self._logger.debug("Mark price fetch failed for %s: %s", symbol, exc)
            return self._mark_cache.get(symbol, {})

        latest = raw[0] if isinstance(raw, list) and raw else {}
        data = {
            "symbol": symbol,
            "mark_price": self._safe_float(latest.get("markPx")),
            "index_price": self._safe_float(latest.get("indexPx")),
            "last": self._safe_float(latest.get("last")),
            "timestamp": latest.get("ts"),
        }
        self._mark_cache[symbol] = data
        return data

    def _fetch_liquidations(self, symbol: str) -> Dict[str, Any]:
        try:
            raw = self._call_client("get_liquidation_orders", "async_get_liquidation_orders", symbol, 50)
        except Exception as exc:
            self._logger.debug("Liquidations fetch failed for %s: %s", symbol, exc)
            return self._liquidation_cache.get(symbol, {})

        long_total = 0.0
        short_total = 0.0
        largest = None
        for order in raw or []:
            price = self._safe_float(order.get("fillPx"))
            size = abs(self._safe_float(order.get("fillSz")))
            notional = price * size
            side = (order.get("posSide") or order.get("side") or "").lower()
            if side == "long":
                long_total += notional
            elif side == "short":
                short_total += notional
            if not largest or notional > largest.get("notional", 0):
                largest = {"notional": notional, "side": side, "price": price, "timestamp": order.get("fillTime")}

        data = {
            "symbol": symbol,
            "long_volume": long_total,
            "short_volume": short_total,
            "net_volume": long_total - short_total,
            "largest_liquidation": largest,
        }
        self._liquidation_cache[symbol] = data
        return data

    # ------------------------------------------------------------------ #
    # Utilities
    # ------------------------------------------------------------------ #
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

    def _call_client(self, sync_name: str, async_name: str, *args, **kwargs):
        """
        Executes either sync or async client method, automatically falling back to
        async when sync variants complain about running inside an event loop.
        """

        sync_method = getattr(self._client, sync_name, None)
        if sync_method is not None:
            try:
                return sync_method(*args, **kwargs)
            except RuntimeError as exc:
                if "不能使用同步方法" not in str(exc):
                    raise
            except Exception:
                raise

        async_method = getattr(self._client, async_name, None)
        if async_method is None:
            raise AttributeError(f"Client does not expose {sync_name} or {async_name}")
        return self._run_async(async_method(*args, **kwargs))

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
        by spinning up a temporary private loop.
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
            pass

        return asyncio.run(coro)