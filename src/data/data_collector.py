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
from ..data.okx_client import get_okx_client
from ..core.exception import DataException


class DataCollector:
    """数据采集器"""
    
    def __init__(self):
        """初始化数据采集器"""
        self.config_mgr = get_config_manager()
        self.logger = get_logger("data_collector")
        self.okx_client = None  # 异步初始化
        
        # 获取配置
        self.trading_pairs = self.config_mgr.get_config('trading', 'trading_pairs')
        self.collection_interval = self.config_mgr.get_config('main', 'scheduler.data_collection_interval', 60)
        
        # 数据存储
        self.market_data_cache: Dict[str, Dict] = {}
        self.orderbook_cache: Dict[str, Dict] = {}
        self.kline_cache: Dict[str, List] = {}
        self.funding_cache: Dict[str, Dict] = {}
        self.open_interest_cache: Dict[str, Dict] = {}
        self.taker_volume_cache: Dict[str, Dict] = {}
        self.long_short_cache: Dict[str, Dict] = {}
        self.trade_cache: Dict[str, List] = {}
        
        # 回调函数
        self.callbacks: Dict[str, List[Callable]] = {
            'ticker': [],
            'orderbook': [],
            'kline': [],
            'trade': []
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
    
    async def collect_ticker(self, symbol: str) -> Dict[str, Any]:
        """
        采集行情数据（异步版本）
        
        Args:
            symbol: 交易对符号
            
        Returns:
            行情数据
        """
        try:
            if self.okx_client is None:
                self.okx_client = await get_okx_client()
            ticker_data = await self.okx_client.async_get_ticker(symbol)
            
            # 数据处理
            if ticker_data and isinstance(ticker_data, list) and len(ticker_data) > 0:
                ticker = ticker_data[0]
                
                # 计算24小时涨跌幅
                current_price = float(ticker.get('last', 0))
                open_24h = float(ticker.get('open24h', 0))
                
                # 如果API返回了changePercent24h字段，直接使用；否则手动计算
                if 'changePercent24h' in ticker and ticker.get('changePercent24h') is not None:
                    change_24h = float(ticker.get('changePercent24h', 0))
                elif open_24h > 0:
                    # 手动计算：(当前价格 - 24小时前开盘价) / 24小时前开盘价 * 100
                    change_24h = ((current_price - open_24h) / open_24h) * 100
                else:
                    change_24h = 0.0
                
                processed_data = {
                    'symbol': symbol,
                    'price': current_price,
                    'bid_price': float(ticker.get('bidPx', 0)),
                    'ask_price': float(ticker.get('askPx', 0)),
                    'volume_24h': float(ticker.get('vol24h', 0)),
                    'change_24h': change_24h,
                    'high_24h': float(ticker.get('high24h', 0)),
                    'low_24h': float(ticker.get('low24h', 0)),
                    'open_24h': open_24h,  # 保存24小时前开盘价，用于调试
                    'timestamp': datetime.now().isoformat()
                }
                
                # 更新缓存
                self.market_data_cache[symbol] = processed_data
                
                # 通知回调
                self._notify_callbacks('ticker', processed_data)
                
                # 记录行情数据
                self.logger.info(
                    f"[行情数据] 交易对: {symbol} | "
                    f"价格: {processed_data['price']} | "
                    f"24h涨跌: {processed_data['change_24h']:.2f}% | "
                    f"24h成交量: {processed_data['volume_24h']:.2f} | "
                    f"24h最高: {processed_data['high_24h']} | "
                    f"24h最低: {processed_data['low_24h']} | "
                    f"买一价: {processed_data['bid_price']} | "
                    f"卖一价: {processed_data['ask_price']}"
                )
                self.logger.debug(f"采集行情数据: {symbol} = {processed_data['price']}")
                return processed_data
            else:
                raise DataException(f"行情数据格式异常: {symbol}")
        
        except Exception as e:
            self.logger.error(f"采集行情数据失败 {symbol}: {e}")
            raise DataException(f"采集行情数据失败: {e}")
    
    async def collect_orderbook(self, symbol: str, depth: int = 20) -> Dict[str, Any]:
        """
        采集订单簿数据（异步版本）
        
        Args:
            symbol: 交易对符号
            depth: 深度
            
        Returns:
            订单簿数据
        """
        try:
            if self.okx_client is None:
                self.okx_client = await get_okx_client()
            orderbook_data = await self.okx_client.async_get_orderbook(symbol, depth)
            
            if orderbook_data and isinstance(orderbook_data, list) and len(orderbook_data) > 0:
                orderbook = orderbook_data[0]
                
                # 处理买卖盘
                bids = orderbook.get('bids', [])
                asks = orderbook.get('asks', [])
                
                processed_data = {
                    'symbol': symbol,
                    'bids': [[float(b[0]), float(b[1])] for b in bids],
                    'asks': [[float(a[0]), float(a[1])] for a in asks],
                    'bid_total': sum(float(b[1]) for b in bids),
                    'ask_total': sum(float(a[1]) for a in asks),
                    'spread': float(asks[0][0]) - float(bids[0][0]) if asks and bids else 0,
                    'timestamp': datetime.now().isoformat()
                }
                
                # 更新缓存
                self.orderbook_cache[symbol] = processed_data
                
                # 通知回调
                self._notify_callbacks('orderbook', processed_data)
                
                self.logger.debug(f"采集订单簿数据: {symbol}, 深度={len(bids)}+{len(asks)}")
                return processed_data
            else:
                raise DataException(f"订单簿数据格式异常: {symbol}")
        
        except Exception as e:
            self.logger.error(f"采集订单簿数据失败 {symbol}: {e}")
            raise DataException(f"采集订单簿数据失败: {e}")
    
    async def collect_funding_rate(self, symbol: str) -> Dict[str, Any]:
        """采集资金费率数据"""
        try:
            if self.okx_client is None:
                self.okx_client = await get_okx_client()
            funding_data = await self.okx_client.async_get_funding_rate(symbol)
            if funding_data and isinstance(funding_data, list):
                latest = funding_data[0]
                processed = {
                    'symbol': symbol,
                    'current_rate': float(latest.get('fundingRate', 0) or 0),
                    'next_rate': float(latest.get('nextFundingRate', 0) or 0),
                    'funding_time': latest.get('fundingTime'),
                    'next_funding_time': latest.get('nextFundingTime'),
                    'interest_rate': float(latest.get('interestRate', 0) or 0),
                    'settle_time': latest.get('settleTime')
                }
                self.funding_cache[symbol] = processed
                return processed
        except Exception as e:
            self.logger.warning(f"采集{symbol}资金费率失败: {e}")
        return self.funding_cache.get(symbol, {})
    
    async def collect_open_interest(self, symbol: str) -> Dict[str, Any]:
        """采集未平仓量"""
        try:
            if self.okx_client is None:
                self.okx_client = await get_okx_client()
            oi_data = await self.okx_client.async_get_open_interest(symbol)
            if oi_data and isinstance(oi_data, list):
                latest = oi_data[0]
                processed = {
                    'symbol': symbol,
                    'amount': float(latest.get('oi', 0) or 0),
                    'amount_ccy': float(latest.get('oiCcy', 0) or 0),
                    'timestamp': latest.get('ts')
                }
                self.open_interest_cache[symbol] = processed
                return processed
        except Exception as e:
            self.logger.warning(f"采集{symbol}未平仓量失败: {e}")
        return self.open_interest_cache.get(symbol, {})
    
    async def collect_taker_volume(self, symbol: str, period: str = '5m') -> Dict[str, Any]:
        """采集主动买卖量"""
        try:
            if self.okx_client is None:
                self.okx_client = await get_okx_client()
            taker_data = await self.okx_client.async_get_taker_volume(symbol, period=period)
            if taker_data and isinstance(taker_data, list):
                latest = taker_data[0]
                buy_vol = float(latest.get('buyVol', 0) or 0)
                sell_vol = float(latest.get('sellVol', 0) or 0)
                buy_value = float(latest.get('buyVolValue', 0) or 0)
                sell_value = float(latest.get('sellVolValue', 0) or 0)
                processed = {
                    'symbol': symbol,
                    'period': period,
                    'buy_vol': buy_vol,
                    'sell_vol': sell_vol,
                    'buy_value': buy_value,
                    'sell_value': sell_value,
                    'taker_buy_ratio': buy_vol / (buy_vol + sell_vol) if (buy_vol + sell_vol) > 0 else 0.5,
                    'timestamp': latest.get('ts')
                }
                self.taker_volume_cache[symbol] = processed
                return processed
        except Exception as e:
            self.logger.warning(f"采集{symbol}主动买卖量失败: {e}")
        return self.taker_volume_cache.get(symbol, {})
    
    async def collect_long_short_ratio(self, symbol: str, period: str = '5m') -> Dict[str, Any]:
        """采集多空账户占比"""
        try:
            if self.okx_client is None:
                self.okx_client = await get_okx_client()
            ratio_data = await self.okx_client.async_get_long_short_ratio(symbol, period=period)
            if ratio_data and isinstance(ratio_data, list):
                latest = ratio_data[0]
                long_ratio = float(latest.get('longAccount', 0) or 0)
                short_ratio = float(latest.get('shortAccount', 0) or 0)
                processed = {
                    'symbol': symbol,
                    'period': period,
                    'long_ratio': long_ratio,
                    'short_ratio': short_ratio,
                    'long_short_ratio': long_ratio / short_ratio if short_ratio > 0 else None,
                    'timestamp': latest.get('ts')
                }
                self.long_short_cache[symbol] = processed
                return processed
        except Exception as e:
            self.logger.warning(f"采集{symbol}多空账户占比失败: {e}")
        return self.long_short_cache.get(symbol, {})
    
    async def collect_recent_trades(self, symbol: str, limit: int = 120) -> List[Dict[str, Any]]:
        """采集最近成交明细"""
        processed_trades: List[Dict[str, Any]] = []
        try:
            if self.okx_client is None:
                self.okx_client = await get_okx_client()
            trades = await self.okx_client.async_get_trades(symbol, limit=limit)
            if trades and isinstance(trades, list):
                for trade in trades:
                    try:
                        price = float(trade.get('px', 0) or 0)
                        size = float(trade.get('sz', 0) or 0)
                        side = trade.get('side', '').lower()
                        processed_trades.append({
                            'trade_id': trade.get('tradeId'),
                            'price': price,
                            'size': abs(size),
                            'side': side,
                            'notional': price * abs(size),
                            'ts': int(trade.get('ts', 0) or 0)
                        })
                    except Exception:
                        continue
                self.trade_cache[symbol] = processed_trades
                return processed_trades
        except Exception as e:
            self.logger.warning(f"采集{symbol}成交明细失败: {e}")
        return self.trade_cache.get(symbol, [])
    
    async def collect_kline(self, symbol: str, interval: str = '1H', limit: int = 100) -> List[Dict[str, Any]]:
        """
        采集K线数据（异步版本）
        
        Args:
            symbol: 交易对符号
            interval: 时间间隔
            limit: 返回数量
            
        Returns:
            K线数据列表
        """
        try:
            if self.okx_client is None:
                self.okx_client = await get_okx_client()
            kline_data = await self.okx_client.async_get_kline(symbol, interval, limit)
            
            if kline_data and isinstance(kline_data, list):
                processed_data = []
                for k in kline_data:
                    if isinstance(k, list) and len(k) >= 6:
                        kline_item = {
                            'symbol': symbol,
                            'timestamp': k[0],  # 时间戳
                            'open': float(k[1]),
                            'high': float(k[2]),
                            'low': float(k[3]),
                            'close': float(k[4]),
                            'volume': float(k[5]),
                            'interval': interval
                        }
                        processed_data.append(kline_item)
                
                # 更新缓存
                self.kline_cache[f"{symbol}_{interval}"] = processed_data
                
                # 通知回调
                self._notify_callbacks('kline', {
                    'symbol': symbol,
                    'interval': interval,
                    'data': processed_data
                })
                
                # 记录K线数据摘要
                if processed_data:
                    latest_kline = processed_data[-1]
                    self.logger.info(
                        f"[K线数据] 交易对: {symbol} | "
                        f"周期: {interval} | "
                        f"条数: {len(processed_data)} | "
                        f"最新: 开={latest_kline.get('open')}, "
                        f"高={latest_kline.get('high')}, "
                        f"低={latest_kline.get('low')}, "
                        f"收={latest_kline.get('close')}, "
                        f"量={latest_kline.get('volume')}"
                    )
                self.logger.debug(f"采集K线数据: {symbol} {interval}, 共{len(processed_data)}条")
                return processed_data
            else:
                raise DataException(f"K线数据格式异常: {symbol}")
        
        except Exception as e:
            self.logger.error(f"采集K线数据失败 {symbol}: {e}")
            raise DataException(f"采集K线数据失败: {e}")
    
    async def collect_all_tickers(self) -> Dict[str, Dict[str, Any]]:
        """
        采集所有交易对的行情数据（异步版本）
        
        Returns:
            所有交易对的行情数据
        """
        all_tickers = {}
        
        for pair in self.trading_pairs:
            if pair.get('enabled', True):
                symbol = pair.get('symbol')
                try:
                    ticker = await self.collect_ticker(symbol)
                    all_tickers[symbol] = ticker
                    
                    # 避免API限流
                    await asyncio.sleep(0.1)
                except Exception as e:
                    self.logger.error(f"采集{symbol}行情失败: {e}")
        
        return all_tickers
    
    async def collect_all_orderbooks(self, depth: int = 20) -> Dict[str, Dict[str, Any]]:
        """
        采集所有交易对的订单簿数据（异步版本）
        
        Args:
            depth: 深度
            
        Returns:
            所有交易对的订单簿数据
        """
        all_orderbooks = {}
        
        for pair in self.trading_pairs:
            if pair.get('enabled', True):
                symbol = pair.get('symbol')
                try:
                    orderbook = await self.collect_orderbook(symbol, depth)
                    all_orderbooks[symbol] = orderbook
                    
                    # 避免API限流
                    await asyncio.sleep(0.1)
                except Exception as e:
                    self.logger.error(f"采集{symbol}订单簿失败: {e}")
        
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
                await self.collect_all_tickers()
                
                # 采集订单簿数据（可选，避免频率过高）
                if int(time.time()) % (self.collection_interval * 2) == 0:
                    self.logger.info("开始采集订单簿数据...")
                    await self.collect_all_orderbooks()
                
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
        if data_type == 'ticker':
            if symbol:
                return self.market_data_cache.get(symbol)
            return self.market_data_cache
        elif data_type == 'orderbook':
            if symbol:
                return self.orderbook_cache.get(symbol)
            return self.orderbook_cache
        elif data_type == 'kline':
            if symbol:
                # 返回所有时间周期的K线
                return {k: v for k, v in self.kline_cache.items() if k.startswith(symbol)}
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
        print(f"订单簿深度: 买盘{len(orderbook['bids'])}档, 卖盘{len(orderbook['asks'])}档")
        print(f"买卖价差: {orderbook['spread']}")
    except Exception as e:
        print(f"采集失败: {e}")

