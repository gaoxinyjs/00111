#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
数据采集器
定时采集各类数据，数据完整性检查，数据质量验证
"""

import asyncio
import time
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any, Callable
from ..core.config_manager import get_config_manager
from ..core.logger import get_logger
from ..data.okx_client import OKXClient
from ..core.exception import DataException


class DataCollector:
    """数据采集器"""

    def __init__(self):
        """初始化数据采集器"""
        self.config_mgr = get_config_manager()
        self.logger = get_logger("data_collector")
        self.okx_client = OKXClient.get_instance()

        # 获取配置
        self.trading_pairs = self.config_mgr.get_config("trading", "trading_pairs")
        self.collection_interval = self.config_mgr.get_config(
            "main", "scheduler.data_collection_interval", 60
        )

        # 数据存储
        self.market_data_cache: Dict[str, Dict] = {}
        self.orderbook_cache: Dict[str, Dict] = {}
        self.kline_cache: Dict[str, List] = {}

        # 回调函数
        self.callbacks: Dict[str, List[Callable]] = {
            "ticker": [],
            "orderbook": [],
            "kline": [],
            "trade": [],
        }

    def register_callback(self, data_type: str, callback: Callable):
        """
        注册数据回调函数

        Args:
            data_type: 数据类型（ticker, orderbook, kline, trade）
            callback: 回调函数
        """
        if data_type in self.callbacks:
            self.callbacks[data_type].append(callback)
            self.logger.info(f"注册{data_type}数据回调函数")
        else:
            raise ValueError(f"不支持的数据类型: {data_type}")

    def _notify_callbacks(self, data_type: str, data: Any):
        """通知回调函数"""
        for callback in self.callbacks.get(data_type, []):
            try:
                callback(data)
            except Exception as e:
                self.logger.error(f"回调函数执行失败: {e}")

    def _process_ticker_data(self, symbol: str, ticker_data: Any) -> Dict[str, Any]:
        """处理 ticker 响应"""
        if ticker_data and isinstance(ticker_data, list) and len(ticker_data) > 0:
            ticker = ticker_data[0]
            current_price = float(ticker.get("last", 0))
            open_24h = float(ticker.get("open24h", 0))

            if (
                "changePercent24h" in ticker
                and ticker.get("changePercent24h") is not None
            ):
                change_24h = float(ticker.get("changePercent24h", 0))
            elif open_24h > 0:
                change_24h = ((current_price - open_24h) / open_24h) * 100
            else:
                change_24h = 0.0

            processed_data = {
                "symbol": symbol,
                "price": current_price,
                "bid_price": float(ticker.get("bidPx", 0)),
                "ask_price": float(ticker.get("askPx", 0)),
                "volume_24h": float(ticker.get("vol24h", 0)),
                "change_24h": change_24h,
                "high_24h": float(ticker.get("high24h", 0)),
                "low_24h": float(ticker.get("low24h", 0)),
                "open_24h": open_24h,
                "timestamp": datetime.now().isoformat(),
            }

            self.market_data_cache[symbol] = processed_data
            self._notify_callbacks("ticker", processed_data)

            self.logger.info(
                f"[行情数据] 交易对: {symbol} | 价格: {processed_data['price']} | "
                f"24h涨跌: {processed_data['change_24h']:.2f}% | 24h成交量: {processed_data['volume_24h']:.2f} | "
                f"24h最高: {processed_data['high_24h']} | 24h最低: {processed_data['low_24h']} | "
                f"买一价: {processed_data['bid_price']} | 卖一价: {processed_data['ask_price']}"
            )
            self.logger.debug(f"采集行情数据: {symbol} = {processed_data['price']}")
            return processed_data
        else:
            raise DataException(f"行情数据格式异常: {symbol}")

    def _process_orderbook_data(
        self, symbol: str, orderbook_data: Any
    ) -> Dict[str, Any]:
        """处理 orderbook 响应"""
        if (
            orderbook_data
            and isinstance(orderbook_data, list)
            and len(orderbook_data) > 0
        ):
            orderbook = orderbook_data[0]
            bids = orderbook.get("bids", [])
            asks = orderbook.get("asks", [])
            processed_data = {
                "symbol": symbol,
                "bids": [[float(b[0]), float(b[1])] for b in bids],
                "asks": [[float(a[0]), float(a[1])] for a in asks],
                "bid_total": sum(float(b[1]) for b in bids),
                "ask_total": sum(float(a[1]) for a in asks),
                "spread": float(asks[0][0]) - float(bids[0][0]) if asks and bids else 0,
                "timestamp": datetime.now().isoformat(),
            }

            self.orderbook_cache[symbol] = processed_data
            self._notify_callbacks("orderbook", processed_data)
            self.logger.debug(f"采集订单簿数据: {symbol}, 深度={len(bids)}+{len(asks)}")
            return processed_data
        else:
            raise DataException(f"订单簿数据格式异常: {symbol}")

    def _process_kline_data(
        self, symbol: str, interval: str, kline_data: Any
    ) -> List[Dict[str, Any]]:
        """处理 K 线响应"""
        if kline_data and isinstance(kline_data, list):
            processed_data = []
            for k in kline_data:
                if isinstance(k, list) and len(k) >= 6:
                    kline_item = {
                        "symbol": symbol,
                        "timestamp": k[0],
                        "open": float(k[1]),
                        "high": float(k[2]),
                        "low": float(k[3]),
                        "close": float(k[4]),
                        "volume": float(k[5]),
                        "interval": interval,
                    }
                    processed_data.append(kline_item)

            cache_key = f"{symbol}_{interval}"
            self.kline_cache[cache_key] = processed_data
            self._notify_callbacks(
                "kline",
                {"symbol": symbol, "interval": interval, "data": processed_data},
            )

            if processed_data:
                latest_kline = processed_data[-1]
                self.logger.info(
                    f"[K线数据] 交易对: {symbol} | 周期: {interval} | 条数: {len(processed_data)} | "
                    f"最新: 开={latest_kline.get('open')}, 高={latest_kline.get('high')}, "
                    f"低={latest_kline.get('low')}, 收={latest_kline.get('close')}, 量={latest_kline.get('volume')}"
                )
            self.logger.debug(
                f"采集K线数据: {symbol} {interval}, 共{len(processed_data)}条"
            )
            return processed_data
        else:
            raise DataException(f"K线数据格式异常: {symbol}")

    def collect_ticker(self, symbol: str) -> Dict[str, Any]:
        """
        采集行情数据

        Args:
            symbol: 交易对符号

        Returns:
            行情数据
        """
        try:
            ticker_data = self.okx_client.get_ticker(symbol)
            return self._process_ticker_data(symbol, ticker_data)
        except Exception as e:
            self.logger.error(f"采集行情数据失败 {symbol}: {e}")
            raise DataException(f"采集行情数据失败: {e}")

    async def collect_ticker_async(self, symbol: str) -> Dict[str, Any]:
        """异步采集行情数据"""
        try:
            ticker_data = await self.okx_client.get_ticker_async(symbol)
            return self._process_ticker_data(symbol, ticker_data)
        except Exception as e:
            self.logger.error(f"采集行情数据失败 {symbol} (async): {e}")
            raise DataException(f"采集行情数据失败: {e}")

    def collect_orderbook(self, symbol: str, depth: int = 20) -> Dict[str, Any]:
        """
        采集订单簿数据

        Args:
            symbol: 交易对符号
            depth: 深度

        Returns:
            订单簿数据
        """
        try:
            orderbook_data = self.okx_client.get_orderbook(symbol, depth)
            return self._process_orderbook_data(symbol, orderbook_data)
        except Exception as e:
            self.logger.error(f"采集订单簿数据失败 {symbol}: {e}")
            raise DataException(f"采集订单簿数据失败: {e}")

    async def collect_orderbook_async(
        self, symbol: str, depth: int = 20
    ) -> Dict[str, Any]:
        """异步采集订单簿数据"""
        try:
            orderbook_data = await self.okx_client.get_orderbook_async(symbol, depth)
            return self._process_orderbook_data(symbol, orderbook_data)
        except Exception as e:
            self.logger.error(f"采集订单簿数据失败 {symbol} (async): {e}")
            raise DataException(f"采集订单簿数据失败: {e}")

    def collect_kline(
        self, symbol: str, interval: str = "1H", limit: int = 100
    ) -> List[Dict[str, Any]]:
        """
        采集K线数据

        Args:
            symbol: 交易对符号
            interval: 时间间隔
            limit: 返回数量

        Returns:
            K线数据列表
        """
        try:
            kline_data = self.okx_client.get_kline(symbol, interval, limit)
            return self._process_kline_data(symbol, interval, kline_data)
        except Exception as e:
            self.logger.error(f"采集K线数据失败 {symbol}: {e}")
            raise DataException(f"采集K线数据失败: {e}")

    async def collect_kline_async(
        self, symbol: str, interval: str = "1H", limit: int = 100
    ) -> List[Dict[str, Any]]:
        """异步采集K线数据"""
        try:
            kline_data = await self.okx_client.get_kline_async(symbol, interval, limit)
            return self._process_kline_data(symbol, interval, kline_data)
        except Exception as e:
            self.logger.error(f"采集K线数据失败 {symbol} (async): {e}")
            raise DataException(f"采集K线数据失败: {e}")

    def collect_all_tickers(self) -> Dict[str, Dict[str, Any]]:
        """
        采集所有交易对的行情数据

        Returns:
            所有交易对的行情数据
        """
        all_tickers = {}

        for pair in self.trading_pairs:
            if pair.get("enabled", True):
                symbol = pair.get("symbol")
                try:
                    ticker = self.collect_ticker(symbol)
                    all_tickers[symbol] = ticker

                    # 避免API限流
                    time.sleep(0.1)
                except Exception as e:
                    self.logger.error(f"采集{symbol}行情失败: {e}")

        return all_tickers

    async def collect_all_tickers_async(self) -> Dict[str, Dict[str, Any]]:
        """异步采集所有交易对的行情数据"""
        all_tickers = {}
        for pair in self.trading_pairs:
            if pair.get("enabled", True):
                symbol = pair.get("symbol")
                try:
                    ticker = await self.collect_ticker_async(symbol)
                    all_tickers[symbol] = ticker
                    await asyncio.sleep(0.1)
                except Exception as e:
                    self.logger.error(f"采集{symbol}行情失败(async): {e}")
        return all_tickers

    def collect_all_orderbooks(self, depth: int = 20) -> Dict[str, Dict[str, Any]]:
        """
        采集所有交易对的订单簿数据

        Args:
            depth: 深度

        Returns:
            所有交易对的订单簿数据
        """
        all_orderbooks = {}

        for pair in self.trading_pairs:
            if pair.get("enabled", True):
                symbol = pair.get("symbol")
                try:
                    orderbook = self.collect_orderbook(symbol, depth)
                    all_orderbooks[symbol] = orderbook

                    # 避免API限流
                    time.sleep(0.1)
                except Exception as e:
                    self.logger.error(f"采集{symbol}订单簿失败: {e}")

        return all_orderbooks

    async def collect_all_orderbooks_async(
        self, depth: int = 20
    ) -> Dict[str, Dict[str, Any]]:
        """异步采集所有交易对的订单簿数据"""
        all_orderbooks = {}
        for pair in self.trading_pairs:
            if pair.get("enabled", True):
                symbol = pair.get("symbol")
                try:
                    orderbook = await self.collect_orderbook_async(symbol, depth)
                    all_orderbooks[symbol] = orderbook
                    await asyncio.sleep(0.1)
                except Exception as e:
                    self.logger.error(f"采集{symbol}订单簿失败(async): {e}")
        return all_orderbooks

    async def start_collection_loop(self):
        """
        启动数据采集循环（异步）
        """
        self.logger.info(f"启动数据采集循环，间隔{self.collection_interval}秒")

        while True:
            try:
                start_time = time.time()

                # 采集所有交易对的行情数据
                self.logger.info("开始采集行情数据...")
                await self.collect_all_tickers_async()

                # 采集订单簿数据（可选，避免频率过高）
                if int(time.time()) % (self.collection_interval * 2) == 0:
                    self.logger.info("开始采集订单簿数据...")
                    await self.collect_all_orderbooks_async()

                elapsed = time.time() - start_time
                self.logger.info(f"数据采集完成，耗时{elapsed:.2f}秒")

                # 等待下次采集
                await asyncio.sleep(max(0, self.collection_interval - elapsed))

            except Exception as e:
                self.logger.error(f"数据采集循环出错: {e}")
                await asyncio.sleep(self.collection_interval)

    def get_cached_data(self, data_type: str, symbol: Optional[str] = None) -> Any:
        """
        获取缓存的数据

        Args:
            data_type: 数据类型（ticker, orderbook, kline）
            symbol: 交易对符号

        Returns:
            缓存的数据
        """
        if data_type == "ticker":
            if symbol:
                return self.market_data_cache.get(symbol)
            return self.market_data_cache
        elif data_type == "orderbook":
            if symbol:
                return self.orderbook_cache.get(symbol)
            return self.orderbook_cache
        elif data_type == "kline":
            if symbol:
                # 返回所有时间周期的K线
                return {
                    k: v for k, v in self.kline_cache.items() if k.startswith(symbol)
                }
            return self.kline_cache
        else:
            raise ValueError(f"不支持的数据类型: {data_type}")


if __name__ == "__main__":
    # 测试数据采集器
    collector = DataCollector()

    # 测试采集单个交易对数据
    print("测试采集BTC-USDT行情...")
    try:
        ticker = collector.collect_ticker("BTC-USDT")
        print(f"行情数据: {ticker}")
    except Exception as e:
        print(f"采集失败: {e}")

    print("\n测试采集订单簿...")
    try:
        orderbook = collector.collect_orderbook("BTC-USDT", depth=10)
        print(
            f"订单簿深度: 买盘{len(orderbook['bids'])}档, 卖盘{len(orderbook['asks'])}档"
        )
        print(f"买卖价差: {orderbook['spread']}")
    except Exception as e:
        print(f"采集失败: {e}")
