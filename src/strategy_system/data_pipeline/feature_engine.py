from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Mapping, Tuple

import numpy as np
import pandas as pd

from src.core.logger import get_logger
from src.data.data_processor import DataProcessor

@dataclass
class FeatureConfig:
    """Configures which indicators are required for downstream scoring."""

    enable_vwap: bool = True
    enable_bands: bool = True
    enable_volume_flows: bool = True


class FeatureEngineer:
    """
    Converts raw candle data into indicator-friendly feature sets.

    Indicator modules consume the normalized payload produced here instead of
    recalculating the same statistics repeatedly.
    """

    def __init__(self, config: FeatureConfig | None = None, data_processor: DataProcessor | None = None) -> None:
        self._config = config or FeatureConfig()
        self._processor = data_processor or DataProcessor()
        self._logger = get_logger("strategy.feature_engineer")

    def build_features(self, market_data: Mapping[str, Mapping[str, Any]]) -> Dict[str, Dict[str, Any]]:
        """
        Parameters
        ----------
        market_data: dict
            Nested dict output from MarketDataCollector.

        Returns
        -------
        dict
            {symbol: {interval: feature_payload}}
        """

        symbol_features: Dict[str, Dict[str, Any]] = {}

        for symbol, payload in market_data.items():
            intervals_data: Dict[str, Dict[str, Any]] = {}
            ticker = payload.get("ticker", {})
            extras = payload.get("extras", {})

            for interval, candles in payload.get("intervals", {}).items():
                if not candles:
                    continue
                df = self._processor.calculate_indicators(candles)
                latest = df.iloc[-1].to_dict() if not df.empty else {}
                intervals_data[interval] = {
                    "candles": candles,
                    "df": df,
                    "latest": latest,
                }

            if not intervals_data:
                self._logger.warning("No indicator data produced for %s", symbol)
                continue

            multi_tf_snapshot = self._build_multi_timeframe_snapshot(intervals_data)
            indicator_snapshot = self._extract_primary_indicators(intervals_data)
            latest_price = self._infer_latest_price(ticker, intervals_data)

            deepseek_payload = self._assemble_deepseek_payload(
                symbol=symbol,
                ticker=ticker,
                intervals=intervals_data,
                multi_tf_snapshot=multi_tf_snapshot,
                indicator_snapshot=indicator_snapshot,
                extras=extras,
            )

            symbol_features[symbol] = {
                "symbol": symbol,
                "ticker": ticker,
                "latest_price": latest_price,
                "intervals": intervals_data,
                "multi_timeframe": multi_tf_snapshot,
                "indicator_snapshot": indicator_snapshot,
                "deepseek_market_data": deepseek_payload,
                "extras": extras,
            }

        return symbol_features

    # ------------------------------------------------------------------ #
    # Helper methods
    # ------------------------------------------------------------------ #
    def _extract_primary_indicators(self, intervals: Mapping[str, Dict[str, Any]], primary: str = "15m") -> Dict[str, Any]:
        primary_payload = intervals.get(primary)
        if not primary_payload:
            primary_payload = next(iter(intervals.values()))
        return primary_payload.get("latest", {})

    def _infer_latest_price(self, ticker: Mapping[str, Any], intervals: Mapping[str, Dict[str, Any]]) -> float:
        if ticker:
            price = ticker.get("price")
            try:
                if price is not None:
                    return float(price)
            except (TypeError, ValueError):
                pass

        for payload in intervals.values():
            latest = payload.get("latest") or {}
            if "close" in latest:
                return float(latest["close"])
        return 0.0

    def _build_multi_timeframe_snapshot(self, intervals: Mapping[str, Dict[str, Any]]) -> Dict[str, Any]:
        snapshot: Dict[str, Any] = {
            "overall_trend": "neutral",
            "trend_strength": 0.0,
            "entry_direction": "hold",
            "entry_timing": "等待确认",
            "confidence": 0.0,
        }

        mapping = {
            "1d": ("trend_24H", "strength_24H"),
            "4h": ("trend_4H", "strength_4H"),
            "1h": ("trend_1H", "strength_1H"),
            "15m": ("trend_15M", "strength_15M"),
        }

        contributions = []
        for interval, (trend_key, strength_key) in mapping.items():
            payload = intervals.get(interval)
            if not payload:
                continue

            df = payload.get("df")
            if df is None or df.empty or "close" not in df.columns:
                continue

            trend, strength = self._derive_trend_and_strength(df)
            snapshot[trend_key] = trend
            snapshot[strength_key] = strength
            contributions.append(strength if trend == "bullish" else -strength)

        if contributions:
            aggregate = float(np.tanh(sum(contributions)))
            snapshot["trend_strength"] = abs(aggregate)
            if aggregate > 0.05:
                snapshot["overall_trend"] = "bullish"
                snapshot["entry_direction"] = "long"
                snapshot["entry_timing"] = "顺势回调做多"
            elif aggregate < -0.05:
                snapshot["overall_trend"] = "bearish"
                snapshot["entry_direction"] = "short"
                snapshot["entry_timing"] = "反弹做空"
            else:
                snapshot["overall_trend"] = "neutral"
                snapshot["entry_direction"] = "hold"
                snapshot["entry_timing"] = "等待趋势确定"

            snapshot["confidence"] = min(1.0, abs(aggregate))

        return snapshot

    def _derive_trend_and_strength(self, df: pd.DataFrame, lookback: int = 30) -> Tuple[str, float]:
        if df.empty:
            return "neutral", 0.0

        closes = df["close"].tail(lookback if len(df) > lookback else len(df))
        if closes.empty:
            return "neutral", 0.0

        first = float(closes.iloc[0])
        last = float(closes.iloc[-1])
        if first == 0:
            return "neutral", 0.0

        pct_change = (last - first) / first
        strength = float(np.tanh(abs(pct_change) * 5))
        trend = "bullish" if pct_change > 0 else "bearish"

        if "rsi" in df.columns and not np.isnan(df["rsi"].iloc[-1]):
            rsi = float(df["rsi"].iloc[-1])
            if 45 <= rsi <= 55:
                strength *= 0.5
            elif rsi < 45 and trend == "bullish":
                trend = "neutral"
                strength *= 0.4
            elif rsi > 55 and trend == "bearish":
                trend = "neutral"
                strength *= 0.4

        return trend, strength

    def _assemble_deepseek_payload(
        self,
        symbol: str,
        ticker: Mapping[str, Any],
        intervals: Mapping[str, Dict[str, Any]],
        multi_tf_snapshot: Mapping[str, Any],
        indicator_snapshot: Mapping[str, Any],
        extras: Mapping[str, Any],
    ) -> Dict[str, Any]:
        def _candles(interval: str) -> list:
            payload = intervals.get(interval)
            return payload.get("candles", []) if payload else []

        orderbook = extras.get("orderbook", {})
        funding = extras.get("funding", {})
        open_interest = extras.get("open_interest", {})
        taker_volume = extras.get("taker_volume", {})
        long_short = extras.get("long_short_ratio", {})
        mark_price = extras.get("mark_price", {})
        liquidations = extras.get("liquidations", {})

        return {
            "symbol": symbol,
            "price": ticker.get("price"),
            "change_24h": ticker.get("change_24h"),
            "high_24h": ticker.get("high_24h"),
            "low_24h": ticker.get("low_24h"),
            "volume_24h": ticker.get("volume_24h"),
            "kline": _candles("15m"),
            "kline_1H": _candles("1h"),
            "kline_4H": _candles("4h"),
            "kline_1D": _candles("1d"),
            "multi_timeframe": dict(multi_tf_snapshot),
            "indicators": dict(indicator_snapshot),
            "orderbook": orderbook,
            "funding": funding,
            "derivatives": {
                "open_interest": open_interest,
                "taker_volume": taker_volume,
                "long_short_ratio": long_short,
                "liquidations": liquidations,
            },
            "impact": {},
            "chain": {},
            "sentiment": {},
            "macro": {},
            "mark_price": mark_price,
        }
