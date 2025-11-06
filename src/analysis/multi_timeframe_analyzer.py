#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
多时间周期分析器
分析1小时、4小时、24小时的价格趋势和量价关系，判断入场时机
"""

from typing import Dict, List, Optional, Any
from datetime import datetime
from ..core.config_manager import get_config_manager
from ..core.logger import get_logger
from ..data.data_processor import DataProcessor


class MultiTimeframeAnalyzer:
    """多时间周期分析器"""
    
    def __init__(self):
        """初始化多时间周期分析器"""
        self.config_mgr = get_config_manager()
        self.logger = get_logger("multi_timeframe_analyzer")
        self.data_processor = DataProcessor()
        
        # 时间周期配置（改为15分钟周期）
        self.timeframes = ['15m', '1H', '4H']  # 分析周期：15分钟、1小时、4小时
        
    def analyze_trends(self, market_data: Dict[str, Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
        """
        分析多时间周期趋势
        
        Args:
            market_data: 市场数据，包含各个周期的K线数据
                {
                    'symbol': {
                        'kline_15m': [...],
                        'kline_1H': [...],
                        'kline_4H': [...],
                        ...
                    }
                }
        
        Returns:
            多时间周期分析结果
        """
        results = {}
        
        for symbol, data in market_data.items():
            try:
                result = self._analyze_symbol(symbol, data)
                results[symbol] = result
            except Exception as e:
                self.logger.error(f"分析{symbol}多时间周期趋势失败: {e}")
                results[symbol] = {
                    'trend': 'unknown',
                    'strength': 0.0,
                    'entry_timing': 'hold'
                }
        
        return results
    
    def _analyze_symbol(self, symbol: str, data: Dict[str, Any]) -> Dict[str, Any]:
        """
        分析单个交易对的多时间周期趋势
        
        Args:
            symbol: 交易对符号
            data: 市场数据
        
        Returns:
            分析结果
        """
        analysis_result = {
            'trend_15m': None,
            'trend_1H': None,
            'trend_4H': None,
            'volume_analysis': {},
            'price_volume_correlation': {},
            'overall_trend': 'neutral',
            'trend_strength': 0.0,
            'entry_timing': 'hold',
            'entry_direction': 'neutral',
            'confidence': 0.0
        }
        
        # 分析各个时间周期
        timeframe_results = {}
        for timeframe in self.timeframes:
            kline_key = f'kline_{timeframe}'
            if kline_key in data and data[kline_key]:
                timeframe_result = self._analyze_timeframe(
                    symbol, timeframe, data[kline_key]
                )
                timeframe_results[timeframe] = timeframe_result
                analysis_result[f'trend_{timeframe}'] = timeframe_result.get('trend')
        
        # 综合分析趋势
        if len(timeframe_results) > 0:
            analysis_result.update(
                self._synthesize_trends(symbol, timeframe_results, data)
            )
        
        return analysis_result
    
    def _analyze_timeframe(self, symbol: str, timeframe: str, 
                          kline_data: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        分析单个时间周期的趋势
        
        Args:
            symbol: 交易对符号
            timeframe: 时间周期（15m, 1H, 4H）
            kline_data: K线数据
        
        Returns:
            时间周期分析结果
        """
        if not kline_data or len(kline_data) < 10:
            return {
                'trend': 'unknown',
                'strength': 0.0,
                'direction': 'neutral'
            }
        
        # 计算技术指标
        df = self.data_processor.calculate_indicators(
            kline_data, ['MACD', 'RSI', 'MA']
        )
        
        if df.empty:
            return {
                'trend': 'unknown',
                'strength': 0.0,
                'direction': 'neutral'
            }
        
        latest = df.iloc[-1]
        
        # 计算趋势方向
        # 使用价格变化、MACD、RSI等指标
        price_change = (latest['close'] - df.iloc[-10]['close']) / df.iloc[-10]['close']
        macd_hist = latest.get('macd_hist', 0)
        rsi = latest.get('rsi', 50)
        ma_trend = self._calculate_ma_trend(df)
        
        # 判断趋势方向
        bullish_signals = 0
        bearish_signals = 0
        
        if price_change > 0.02:  # 上涨2%以上
            bullish_signals += 2
        elif price_change < -0.02:  # 下跌2%以上
            bearish_signals += 2
        
        if macd_hist > 0:
            bullish_signals += 1
        elif macd_hist < 0:
            bearish_signals += 1
        
        if rsi > 55:
            bearish_signals += 1
        elif rsi < 45:
            bullish_signals += 1
        
        if ma_trend > 0:
            bullish_signals += 1
        elif ma_trend < 0:
            bearish_signals += 1
        
        # 判断趋势
        if bullish_signals > bearish_signals:
            trend = 'bullish'
            strength = min(1.0, bullish_signals / 5.0)
            direction = 'up'
        elif bearish_signals > bullish_signals:
            trend = 'bearish'
            strength = min(1.0, bearish_signals / 5.0)
            direction = 'down'
        else:
            trend = 'neutral'
            strength = 0.5
            direction = 'neutral'
        
        return {
            'trend': trend,
            'strength': strength,
            'direction': direction,
            'price_change': price_change,
            'macd_hist': macd_hist,
            'rsi': rsi,
            'ma_trend': ma_trend
        }
    
    def _calculate_ma_trend(self, df) -> float:
        """计算均线趋势"""
        if 'ma_5' not in df.columns or 'ma_20' not in df.columns:
            return 0.0
        
        latest = df.iloc[-1]
        ma5 = latest.get('ma_5', 0)
        ma20 = latest.get('ma_20', 0)
        
        if ma5 > ma20:
            return 1.0  # 上涨趋势
        elif ma5 < ma20:
            return -1.0  # 下跌趋势
        else:
            return 0.0  # 横盘
    
    def _synthesize_trends(self, symbol: str, timeframe_results: Dict[str, Dict[str, Any]],
                          data: Dict[str, Any]) -> Dict[str, Any]:
        """
        综合多时间周期趋势
        
        Args:
            symbol: 交易对符号
            timeframe_results: 各时间周期分析结果
            data: 原始市场数据
        
        Returns:
            综合分析结果
        """
        # 量价分析
        volume_analysis = self._analyze_volume_price(symbol, data)
        
        # 多周期趋势综合
        trends = {}
        strengths = {}
        directions = {}
        
        for timeframe, result in timeframe_results.items():
            trends[timeframe] = result.get('trend')
            strengths[timeframe] = result.get('strength', 0.0)
            directions[timeframe] = result.get('direction', 'neutral')
        
        # 计算综合趋势（15m权重最高，4H次之，1H最低）
        weights = {'15m': 0.5, '4H': 0.3, '1H': 0.2}
        weighted_trend = 0.0
        total_weight = 0.0
        
        for timeframe, weight in weights.items():
            if timeframe in trends:
                direction = directions[timeframe]
                strength = strengths[timeframe]
                
                if direction == 'up':
                    weighted_trend += weight * strength
                elif direction == 'down':
                    weighted_trend -= weight * strength
                
                total_weight += weight
        
        # 判断整体趋势
        if weighted_trend > 0.3:
            overall_trend = 'bullish'
            trend_strength = min(1.0, weighted_trend / total_weight if total_weight > 0 else 0.0)
            entry_direction = 'long'
        elif weighted_trend < -0.3:
            overall_trend = 'bearish'
            trend_strength = min(1.0, abs(weighted_trend) / total_weight if total_weight > 0 else 0.0)
            entry_direction = 'short'
        else:
            overall_trend = 'neutral'
            trend_strength = 0.0
            entry_direction = 'neutral'
        
        # 入场时机判断
        entry_timing, confidence = self._determine_entry_timing(
            trends, strengths, directions, volume_analysis
        )
        
        return {
            'volume_analysis': volume_analysis,
            'overall_trend': overall_trend,
            'trend_strength': trend_strength,
            'entry_timing': entry_timing,
            'entry_direction': entry_direction,
            'confidence': confidence,
            'timeframe_trends': trends,
            'timeframe_strengths': strengths
        }
    
    def _analyze_volume_price(self, symbol: str, data: Dict[str, Any]) -> Dict[str, Any]:
        """
        量价分析
        
        Args:
            symbol: 交易对符号
            data: 市场数据
        
        Returns:
            量价分析结果
        """
        volume_analysis = {
            'volume_trend': 'neutral',
            'price_volume_correlation': 0.0,
            'volume_surge': False,
            'divergence': False
        }
        
        # 分析各个时间周期的量价关系
        for timeframe in self.timeframes:
            kline_key = f'kline_{timeframe}'
            if kline_key in data and data[kline_key] and len(data[kline_key]) >= 20:
                kline_data = data[kline_key]
                
                # 计算最近20根K线的量和价的变化
                recent_volumes = [float(k.get('volume', 0)) for k in kline_data[-20:]]
                recent_prices = [float(k.get('close', 0)) for k in kline_data[-20:]]
                
                if len(recent_volumes) >= 2 and len(recent_prices) >= 2:
                    # 计算量的变化趋势
                    volume_trend = (sum(recent_volumes[-5:]) / sum(recent_volumes[:5]) - 1) if sum(recent_volumes[:5]) > 0 else 0
                    
                    # 计算价的变化趋势
                    price_trend = (recent_prices[-1] / recent_prices[0] - 1) if recent_prices[0] > 0 else 0
                    
                    # 量价相关性（简化计算）
                    if volume_trend > 0.2 and price_trend > 0:
                        # 放量上涨，看多
                        volume_analysis['volume_trend'] = 'bullish'
                        volume_analysis['price_volume_correlation'] = 0.8
                    elif volume_trend > 0.2 and price_trend < 0:
                        # 放量下跌，看空
                        volume_analysis['volume_trend'] = 'bearish'
                        volume_analysis['price_volume_correlation'] = -0.8
                    elif volume_trend > 0.3:
                        # 成交量激增
                        volume_analysis['volume_surge'] = True
                    
                    break  # 优先使用1H数据
        
        return volume_analysis
    
    def _determine_entry_timing(self, trends: Dict[str, str], 
                               strengths: Dict[str, float],
                               directions: Dict[str, str],
                               volume_analysis: Dict[str, Any]) -> tuple:
        """
        判断入场时机
        
        Args:
            trends: 各时间周期趋势
            strengths: 各时间周期强度
            directions: 各时间周期方向
            volume_analysis: 量价分析结果
        
        Returns:
            (入场时机, 信心度)
        """
        # 入场时机判断逻辑
        # 1. 多周期趋势一致时，入场信号更强
        # 2. 量价配合时，信号更可靠
        # 3. 大周期趋势确定方向，小周期找入场点
        
        # 检查多周期一致性
        all_trends = [t for t in trends.values() if t]
        if not all_trends:
            return ('hold', 0.0)
        
        # 趋势一致性
        bullish_count = sum(1 for t in all_trends if t == 'bullish')
        bearish_count = sum(1 for t in all_trends if t == 'bearish')
        
        # 平均强度
        avg_strength = sum(strengths.values()) / len(strengths) if strengths else 0.0
        
        # 15m趋势权重最高
        trend_15m = trends.get('15m', 'neutral')
        strength_15m = strengths.get('15m', 0.0)
        
        # 入场时机判断
        if trend_15m == 'bullish' and bullish_count >= 2 and avg_strength > 0.5:
            # 多周期看多，趋势一致
            if volume_analysis.get('volume_trend') == 'bullish':
                return ('enter', 0.8)  # 量价配合，高信心
            else:
                return ('enter', 0.6)  # 趋势明确，中等信心
        elif trend_15m == 'bearish' and bearish_count >= 2 and avg_strength > 0.5:
            # 多周期看空，趋势一致
            if volume_analysis.get('volume_trend') == 'bearish':
                return ('enter', 0.8)  # 量价配合，高信心
            else:
                return ('enter', 0.6)  # 趋势明确，中等信心
        elif trend_15m in ['bullish', 'bearish'] and avg_strength > 0.4:
            # 大周期趋势明确，但多周期不完全一致
            return ('watch', 0.4)  # 观察，等待更好时机
        else:
            return ('hold', 0.0)  # 观望

