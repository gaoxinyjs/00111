#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
前瞻性分析器
基于订单簿、订单流、成交量分布等实时数据，预测未来价格走势
这些指标比MACD、RSI等滞后指标更前瞻，能更早捕捉价格变化

主要分析方法：
1. 订单簿不平衡分析（Order Book Imbalance）- 实时买卖盘压力
2. 订单流分析（Order Flow）- 实际成交方向分析
3. 成交量分布分析（Volume Profile）- 价格支撑阻力位
4. 价格动量预测（Momentum Prediction）- 价格变化速度
5. 市场微观结构分析（Market Microstructure）- 买卖盘深度分布
"""

from typing import Dict, List, Optional, Any, Tuple
import numpy as np
from datetime import datetime, timedelta
from ..core.logger import get_logger
from ..core.exception import StrategyException


class ForwardAnalyzer:
    """前瞻性分析器"""
    
    def __init__(self):
        """初始化前瞻性分析器"""
        self.logger = get_logger("forward_analyzer")
        
        # 历史数据缓存（用于趋势分析）
        self.orderbook_history: List[Dict[str, Any]] = []
        self.trade_history: List[Dict[str, Any]] = []
        self.max_history = 1000  # 最多保存1000条历史记录
    
    def analyze_orderbook_imbalance(self, orderbook_data: Dict[str, Any], 
                                     current_price: float) -> Dict[str, Any]:
        """
        分析订单簿不平衡（Order Book Imbalance）
        
        订单簿不平衡是预测短期价格走势的前瞻性指标：
        - 买盘压力 > 卖盘压力 → 价格上涨概率高
        - 卖盘压力 > 买盘压力 → 价格下跌概率高
        
        Args:
            orderbook_data: 订单簿数据
            current_price: 当前价格
            
        Returns:
            分析结果，包含：
            - imbalance_ratio: 不平衡比例 (-1到1，正数表示买盘强，负数表示卖盘强)
            - pressure_score: 压力得分 (0-1，越高表示压力越大)
            - prediction: 预测方向 ('buy', 'sell', 'neutral')
            - confidence: 置信度 (0-1)
        """
        try:
            if not orderbook_data or not current_price or current_price <= 0:
                return {
                    'imbalance_ratio': 0.0,
                    'pressure_score': 0.0,
                    'prediction': 'neutral',
                    'confidence': 0.0
                }
            
            bids = orderbook_data.get('bids', [])
            asks = orderbook_data.get('asks', [])
            
            if not bids or not asks:
                return {
                    'imbalance_ratio': 0.0,
                    'pressure_score': 0.0,
                    'prediction': 'neutral',
                    'confidence': 0.0
                }
            
            # 1. 计算价格区间内的买卖盘总量
            # 在价格上下1%范围内计算买卖盘压力
            price_range = current_price * 0.01  # 1%价格区间
            
            bid_volume = 0.0
            ask_volume = 0.0
            
            # 计算买盘总量（在价格下方1%范围内）
            for bid in bids:
                price, volume = float(bid[0]), float(bid[1])
                if price >= current_price - price_range:
                    bid_volume += volume
            
            # 计算卖盘总量（在价格上方1%范围内）
            for ask in asks:
                price, volume = float(ask[0]), float(ask[1])
                if price <= current_price + price_range:
                    ask_volume += volume
            
            # 2. 计算不平衡比例
            total_volume = bid_volume + ask_volume
            if total_volume > 0:
                imbalance_ratio = (bid_volume - ask_volume) / total_volume
            else:
                imbalance_ratio = 0.0
            
            # 3. 计算深度加权的不平衡（更接近当前价格的订单权重更高）
            weighted_bid_volume = 0.0
            weighted_ask_volume = 0.0
            
            for bid in bids:
                price, volume = float(bid[0]), float(bid[1])
                if price >= current_price - price_range:
                    # 距离当前价格越近，权重越高
                    distance = abs(current_price - price) / price_range
                    weight = max(0, 1 - distance)  # 线性衰减
                    weighted_bid_volume += volume * weight
            
            for ask in asks:
                price, volume = float(ask[0]), float(ask[1])
                if price <= current_price + price_range:
                    distance = abs(price - current_price) / price_range
                    weight = max(0, 1 - distance)
                    weighted_ask_volume += volume * weight
            
            weighted_total = weighted_bid_volume + weighted_ask_volume
            if weighted_total > 0:
                weighted_imbalance = (weighted_bid_volume - weighted_ask_volume) / weighted_total
            else:
                weighted_imbalance = 0.0
            
            # 4. 计算大单分布（大单更能反映真实意图）
            large_order_threshold = total_volume * 0.1  # 占总量的10%以上算大单
            
            large_bid_volume = sum(float(bid[1]) for bid in bids 
                                  if float(bid[1]) >= large_order_threshold and 
                                  float(bid[0]) >= current_price - price_range)
            
            large_ask_volume = sum(float(ask[1]) for ask in asks 
                                  if float(ask[1]) >= large_order_threshold and 
                                  float(ask[0]) <= current_price + price_range)
            
            large_total = large_bid_volume + large_ask_volume
            if large_total > 0:
                large_imbalance = (large_bid_volume - large_ask_volume) / large_total
            else:
                large_imbalance = 0.0
            
            # 5. 综合计算最终不平衡比例（加权平均）
            final_imbalance = (
                imbalance_ratio * 0.3 +  # 总量不平衡权重30%
                weighted_imbalance * 0.4 +  # 深度加权不平衡权重40%
                large_imbalance * 0.3  # 大单不平衡权重30%
            )
            
            # 6. 计算压力得分（绝对值越大，压力越大）
            pressure_score = abs(final_imbalance)
            
            # 7. 预测方向
            if final_imbalance > 0.15:  # 买盘压力明显
                prediction = 'buy'
                confidence = min(1.0, pressure_score * 1.5)
            elif final_imbalance < -0.15:  # 卖盘压力明显
                prediction = 'sell'
                confidence = min(1.0, pressure_score * 1.5)
            else:
                prediction = 'neutral'
                confidence = 0.0
            
            self.logger.debug(
                f"[订单簿不平衡] 不平衡比例={final_imbalance:.3f}, "
                f"压力得分={pressure_score:.3f}, 预测={prediction}, 置信度={confidence:.3f}"
            )
            
            return {
                'imbalance_ratio': final_imbalance,
                'pressure_score': pressure_score,
                'prediction': prediction,
                'confidence': confidence,
                'bid_volume': bid_volume,
                'ask_volume': ask_volume,
                'weighted_bid': weighted_bid_volume,
                'weighted_ask': weighted_ask_volume,
                'large_bid': large_bid_volume,
                'large_ask': large_ask_volume
            }
        
        except Exception as e:
            self.logger.error(f"分析订单簿不平衡失败: {e}")
            return {
                'imbalance_ratio': 0.0,
                'pressure_score': 0.0,
                'prediction': 'neutral',
                'confidence': 0.0
            }
    
    def analyze_order_flow(self, recent_trades: List[Dict[str, Any]], 
                          current_price: float) -> Dict[str, Any]:
        """
        分析订单流（Order Flow）
        
        订单流分析实际成交的方向和强度，比订单簿更实时：
        - 大买单多 → 价格上涨概率高
        - 大卖单多 → 价格下跌概率高
        
        Args:
            recent_trades: 最近成交记录 [{'price': float, 'size': float, 'side': 'buy'/'sell', 'timestamp': str}]
            current_price: 当前价格
            
        Returns:
            分析结果，包含：
            - buy_flow_ratio: 买单流比例 (0-1)
            - sell_flow_ratio: 卖单流比例 (0-1)
            - net_flow: 净流量 (-1到1)
            - prediction: 预测方向
            - confidence: 置信度
        """
        try:
            if not recent_trades or len(recent_trades) == 0:
                return {
                    'buy_flow_ratio': 0.5,
                    'sell_flow_ratio': 0.5,
                    'net_flow': 0.0,
                    'prediction': 'neutral',
                    'confidence': 0.0
                }
            
            # 只分析最近1分钟内的成交
            now = datetime.now()
            one_minute_ago = now - timedelta(minutes=1)
            
            recent_trades_filtered = []
            for trade in recent_trades:
                trade_time = datetime.fromisoformat(trade.get('timestamp', now.isoformat()))
                if trade_time >= one_minute_ago:
                    recent_trades_filtered.append(trade)
            
            if not recent_trades_filtered:
                return {
                    'buy_flow_ratio': 0.5,
                    'sell_flow_ratio': 0.5,
                    'net_flow': 0.0,
                    'prediction': 'neutral',
                    'confidence': 0.0
                }
            
            # 计算买卖单流
            buy_volume = 0.0
            sell_volume = 0.0
            buy_count = 0
            sell_count = 0
            
            # 价格加权（价格越接近当前价格，权重越高）
            price_weighted_buy = 0.0
            price_weighted_sell = 0.0
            
            for trade in recent_trades_filtered:
                price = float(trade.get('price', current_price))
                size = float(trade.get('size', 0))
                side = trade.get('side', '').lower()
                
                # 计算价格权重（距离当前价格越近，权重越高）
                price_diff = abs(price - current_price) / current_price
                weight = max(0, 1 - price_diff * 100)  # 1%以内权重高
                
                if side == 'buy' or trade.get('buy', False):
                    buy_volume += size
                    buy_count += 1
                    price_weighted_buy += size * weight
                elif side == 'sell' or trade.get('sell', False):
                    sell_volume += size
                    sell_count += 1
                    price_weighted_sell += size * weight
            
            total_volume = buy_volume + sell_volume
            if total_volume > 0:
                buy_flow_ratio = buy_volume / total_volume
                sell_flow_ratio = sell_volume / total_volume
                
                # 价格加权流量
                weighted_total = price_weighted_buy + price_weighted_sell
                if weighted_total > 0:
                    weighted_buy_ratio = price_weighted_buy / weighted_total
                    weighted_sell_ratio = price_weighted_sell / weighted_total
                else:
                    weighted_buy_ratio = 0.5
                    weighted_sell_ratio = 0.5
                
                # 综合计算净流量（结合总量和价格加权）
                net_flow = (buy_flow_ratio * 0.5 + weighted_buy_ratio * 0.5) - 0.5
                net_flow = net_flow * 2  # 归一化到-1到1
            else:
                buy_flow_ratio = 0.5
                sell_flow_ratio = 0.5
                net_flow = 0.0
            
            # 预测方向
            if net_flow > 0.2:  # 明显买盘流入
                prediction = 'buy'
                confidence = min(1.0, abs(net_flow) * 2)
            elif net_flow < -0.2:  # 明显卖盘流入
                prediction = 'sell'
                confidence = min(1.0, abs(net_flow) * 2)
            else:
                prediction = 'neutral'
                confidence = 0.0
            
            self.logger.debug(
                f"[订单流分析] 净流量={net_flow:.3f}, "
                f"买盘比例={buy_flow_ratio:.3f}, 卖盘比例={sell_flow_ratio:.3f}, "
                f"预测={prediction}, 置信度={confidence:.3f}"
            )
            
            return {
                'buy_flow_ratio': buy_flow_ratio,
                'sell_flow_ratio': sell_flow_ratio,
                'net_flow': net_flow,
                'prediction': prediction,
                'confidence': confidence,
                'buy_volume': buy_volume,
                'sell_volume': sell_volume,
                'buy_count': buy_count,
                'sell_count': sell_count
            }
        
        except Exception as e:
            self.logger.error(f"分析订单流失败: {e}")
            return {
                'buy_flow_ratio': 0.5,
                'sell_flow_ratio': 0.5,
                'net_flow': 0.0,
                'prediction': 'neutral',
                'confidence': 0.0
            }
    
    def analyze_volume_profile(self, kline_data: List[Dict[str, Any]], 
                              current_price: float) -> Dict[str, Any]:
        """
        分析成交量分布（Volume Profile）
        
        成交量分布分析哪些价格区域有大量成交，这些区域通常是支撑/阻力位：
        - 高成交量价格区域 → 强支撑/阻力
        - 价格突破高成交量区域 → 趋势延续
        
        Args:
            kline_data: K线数据
            current_price: 当前价格
            
        Returns:
            分析结果，包含：
            - support_levels: 支撑位列表
            - resistance_levels: 阻力位列表
            - price_vs_vpoc: 当前价格相对于价值点（VPOC）的位置
            - prediction: 预测方向
            - confidence: 置信度
        """
        try:
            if not kline_data or len(kline_data) < 20:
                return {
                    'support_levels': [],
                    'resistance_levels': [],
                    'price_vs_vpoc': 0.0,
                    'prediction': 'neutral',
                    'confidence': 0.0
                }
            
            # 分析最近20根K线的成交量分布
            recent_klines = kline_data[-20:] if len(kline_data) > 20 else kline_data
            
            # 计算价格区间和成交量分布
            prices = []
            volumes = []
            
            for kline in recent_klines:
                high = float(kline.get('high', 0))
                low = float(kline.get('low', 0))
                close = float(kline.get('close', 0))
                volume = float(kline.get('volume', 0))
                
                if high > 0 and low > 0:
                    # 使用收盘价和成交量
                    prices.append(close)
                    volumes.append(volume)
            
            if not prices or not volumes:
                return {
                    'support_levels': [],
                    'resistance_levels': [],
                    'price_vs_vpoc': 0.0,
                    'prediction': 'neutral',
                    'confidence': 0.0
                }
            
            # 计算价值点（VPOC - Volume Point of Control）
            # VPOC是成交量最大的价格点
            price_volume_dict = {}
            for price, volume in zip(prices, volumes):
                if price not in price_volume_dict:
                    price_volume_dict[price] = 0
                price_volume_dict[price] += volume
            
            if price_volume_dict:
                vpoc = max(price_volume_dict.items(), key=lambda x: x[1])[0]
            else:
                vpoc = current_price
            
            # 计算当前价格相对于VPOC的位置
            if vpoc > 0:
                price_vs_vpoc = (current_price - vpoc) / vpoc
            else:
                price_vs_vpoc = 0.0
            
            # 识别支撑位和阻力位
            # 支撑位：当前价格下方的成交量集中区域
            # 阻力位：当前价格上方的成交量集中区域
            support_levels = []
            resistance_levels = []
            
            # 按成交量排序，找出高成交量价格区域
            sorted_price_volume = sorted(price_volume_dict.items(), 
                                        key=lambda x: x[1], reverse=True)
            
            # 取前30%的高成交量价格作为关键位
            top_count = max(1, int(len(sorted_price_volume) * 0.3))
            
            for price, volume in sorted_price_volume[:top_count]:
                if price < current_price * 0.98:  # 价格低于当前价格2%以上算支撑
                    support_levels.append({'price': price, 'volume': volume})
                elif price > current_price * 1.02:  # 价格高于当前价格2%以上算阻力
                    resistance_levels.append({'price': price, 'volume': volume})
            
            # 预测方向
            # 如果当前价格在VPOC上方，且有阻力位，可能回调
            # 如果当前价格在VPOC下方，且有支撑位，可能反弹
            prediction = 'neutral'
            confidence = 0.0
            
            if price_vs_vpoc > 0.02:  # 价格在VPOC上方2%以上
                if resistance_levels:
                    prediction = 'sell'  # 可能遇到阻力回调
                    confidence = min(1.0, abs(price_vs_vpoc) * 10)
                else:
                    prediction = 'buy'  # 突破向上
                    confidence = 0.5
            elif price_vs_vpoc < -0.02:  # 价格在VPOC下方2%以上
                if support_levels:
                    prediction = 'buy'  # 可能遇到支撑反弹
                    confidence = min(1.0, abs(price_vs_vpoc) * 10)
                else:
                    prediction = 'sell'  # 跌破向下
                    confidence = 0.5
            
            self.logger.debug(
                f"[成交量分布] VPOC={vpoc:.5f}, 当前价格vsVPOC={price_vs_vpoc:.3f}, "
                f"支撑位数量={len(support_levels)}, 阻力位数量={len(resistance_levels)}, "
                f"预测={prediction}, 置信度={confidence:.3f}"
            )
            
            return {
                'support_levels': support_levels,
                'resistance_levels': resistance_levels,
                'vpoc': vpoc,
                'price_vs_vpoc': price_vs_vpoc,
                'prediction': prediction,
                'confidence': confidence
            }
        
        except Exception as e:
            self.logger.error(f"分析成交量分布失败: {e}")
            return {
                'support_levels': [],
                'resistance_levels': [],
                'price_vs_vpoc': 0.0,
                'prediction': 'neutral',
                'confidence': 0.0
            }
    
    def analyze_momentum(self, price_history: List[float], 
                        volume_history: List[float]) -> Dict[str, Any]:
        """
        分析价格动量（Momentum）
        
        价格动量分析价格变化的速度和加速度，预测短期趋势：
        - 价格加速上涨 → 继续上涨概率高
        - 价格加速下跌 → 继续下跌概率高
        - 动量衰减 → 可能反转
        
        Args:
            price_history: 价格历史 [最近的价格]
            volume_history: 成交量历史 [最近的成交量]
            
        Returns:
            分析结果，包含：
            - momentum: 动量值 (-1到1)
            - acceleration: 加速度 (-1到1)
            - prediction: 预测方向
            - confidence: 置信度
        """
        try:
            if not price_history or len(price_history) < 10:
                return {
                    'momentum': 0.0,
                    'acceleration': 0.0,
                    'prediction': 'neutral',
                    'confidence': 0.0
                }
            
            # 计算价格变化率（动量）
            recent_prices = price_history[-10:]  # 最近10个价格点
            
            # 计算价格变化率序列
            price_changes = []
            for i in range(1, len(recent_prices)):
                if recent_prices[i-1] > 0:
                    change = (recent_prices[i] - recent_prices[i-1]) / recent_prices[i-1]
                    price_changes.append(change)
            
            if not price_changes:
                return {
                    'momentum': 0.0,
                    'acceleration': 0.0,
                    'prediction': 'neutral',
                    'confidence': 0.0
                }
            
            # 计算动量（最近价格变化的加权平均）
            # 越近的变化权重越高
            momentum = 0.0
            total_weight = 0.0
            
            for i, change in enumerate(price_changes):
                weight = (i + 1) / len(price_changes)  # 越近权重越高
                momentum += change * weight
                total_weight += weight
            
            if total_weight > 0:
                momentum = momentum / total_weight
            
            # 计算加速度（动量的变化率）
            if len(price_changes) >= 3:
                # 计算最近3个动量值
                recent_momentum = []
                for i in range(1, len(price_changes)):
                    if i >= 2:
                        # 计算短期动量
                        short_momentum = (price_changes[i] + price_changes[i-1]) / 2
                        recent_momentum.append(short_momentum)
                
                if len(recent_momentum) >= 2:
                    acceleration = recent_momentum[-1] - recent_momentum[-2]
                else:
                    acceleration = 0.0
            else:
                acceleration = 0.0
            
            # 归一化到-1到1
            momentum = max(-1.0, min(1.0, momentum * 100))  # 假设变化率在1%以内
            acceleration = max(-1.0, min(1.0, acceleration * 100))
            
            # 预测方向
            # 动量 > 0 且加速度 > 0 → 加速上涨
            # 动量 < 0 且加速度 < 0 → 加速下跌
            # 动量 > 0 但加速度 < 0 → 上涨减缓，可能反转
            # 动量 < 0 但加速度 > 0 → 下跌减缓，可能反弹
            
            if momentum > 0.1 and acceleration > 0.05:
                prediction = 'buy'
                confidence = min(1.0, (momentum + acceleration) * 0.5)
            elif momentum < -0.1 and acceleration < -0.05:
                prediction = 'sell'
                confidence = min(1.0, (abs(momentum) + abs(acceleration)) * 0.5)
            elif momentum > 0.1 and acceleration < -0.05:
                # 上涨但减速，可能反转
                prediction = 'sell'
                confidence = min(0.6, abs(acceleration) * 2)
            elif momentum < -0.1 and acceleration > 0.05:
                # 下跌但减速，可能反弹
                prediction = 'buy'
                confidence = min(0.6, abs(acceleration) * 2)
            else:
                prediction = 'neutral'
                confidence = 0.0
            
            self.logger.debug(
                f"[价格动量] 动量={momentum:.3f}, 加速度={acceleration:.3f}, "
                f"预测={prediction}, 置信度={confidence:.3f}"
            )
            
            return {
                'momentum': momentum,
                'acceleration': acceleration,
                'prediction': prediction,
                'confidence': confidence
            }
        
        except Exception as e:
            self.logger.error(f"分析价格动量失败: {e}")
            return {
                'momentum': 0.0,
                'acceleration': 0.0,
                'prediction': 'neutral',
                'confidence': 0.0
            }
    
    def comprehensive_forward_analysis(self, market_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        综合前瞻性分析
        
        整合所有前瞻性指标，给出综合预测
        
        Args:
            market_data: 市场数据，包含：
                - orderbook: 订单簿数据
                - recent_trades: 最近成交记录
                - kline: K线数据
                - price: 当前价格
                - price_history: 价格历史
                - volume_history: 成交量历史
        
        Returns:
            综合分析结果
        """
        try:
            current_price = float(market_data.get('price', 0))
            if current_price <= 0:
                return {
                    'prediction': 'neutral',
                    'confidence': 0.0,
                    'signals': {}
                }
            
            # 1. 订单簿不平衡分析
            orderbook_data = market_data.get('orderbook', {})
            orderbook_result = self.analyze_orderbook_imbalance(orderbook_data, current_price)
            
            # 2. 订单流分析
            recent_trades = market_data.get('recent_trades', [])
            orderflow_result = self.analyze_order_flow(recent_trades, current_price)
            
            # 3. 成交量分布分析
            kline_data = market_data.get('kline', [])
            volume_profile_result = self.analyze_volume_profile(kline_data, current_price)
            
            # 4. 价格动量分析
            price_history = market_data.get('price_history', [])
            volume_history = market_data.get('volume_history', [])
            momentum_result = self.analyze_momentum(price_history, volume_history)
            
            # 5. 综合预测（加权平均）
            predictions = {
                'orderbook': (orderbook_result.get('prediction'), orderbook_result.get('confidence', 0)),
                'orderflow': (orderflow_result.get('prediction'), orderflow_result.get('confidence', 0)),
                'volume_profile': (volume_profile_result.get('prediction'), volume_profile_result.get('confidence', 0)),
                'momentum': (momentum_result.get('prediction'), momentum_result.get('confidence', 0))
            }
            
            # 计算加权得分
            buy_score = 0.0
            sell_score = 0.0
            total_weight = 0.0
            
            # 权重配置（订单簿和订单流更前瞻，权重更高）
            weights = {
                'orderbook': 0.35,
                'orderflow': 0.35,
                'volume_profile': 0.15,
                'momentum': 0.15
            }
            
            for source, (prediction, confidence) in predictions.items():
                weight = weights.get(source, 0.25) * confidence
                total_weight += weight
                
                if prediction == 'buy':
                    buy_score += weight
                elif prediction == 'sell':
                    sell_score += weight
            
            # 最终预测
            if total_weight > 0:
                buy_ratio = buy_score / total_weight
                sell_ratio = sell_score / total_weight
                
                if buy_ratio > 0.6:
                    final_prediction = 'buy'
                    final_confidence = min(1.0, buy_ratio * total_weight * 2)
                elif sell_ratio > 0.6:
                    final_prediction = 'sell'
                    final_confidence = min(1.0, sell_ratio * total_weight * 2)
                else:
                    final_prediction = 'neutral'
                    final_confidence = 0.0
            else:
                final_prediction = 'neutral'
                final_confidence = 0.0
            
            self.logger.info(
                f"[综合前瞻分析] 预测={final_prediction}, 置信度={final_confidence:.3f}, "
                f"订单簿={orderbook_result.get('prediction')}({orderbook_result.get('confidence', 0):.2f}), "
                f"订单流={orderflow_result.get('prediction')}({orderflow_result.get('confidence', 0):.2f}), "
                f"成交量分布={volume_profile_result.get('prediction')}({volume_profile_result.get('confidence', 0):.2f}), "
                f"动量={momentum_result.get('prediction')}({momentum_result.get('confidence', 0):.2f})"
            )
            
            return {
                'prediction': final_prediction,
                'confidence': final_confidence,
                'signals': {
                    'orderbook': orderbook_result,
                    'orderflow': orderflow_result,
                    'volume_profile': volume_profile_result,
                    'momentum': momentum_result
                },
                'buy_score': buy_score,
                'sell_score': sell_score,
                'total_weight': total_weight
            }
        
        except Exception as e:
            self.logger.error(f"综合前瞻性分析失败: {e}")
            return {
                'prediction': 'neutral',
                'confidence': 0.0,
                'signals': {}
            }


if __name__ == "__main__":
    # 测试前瞻性分析器
    analyzer = ForwardAnalyzer()
    
    # 模拟订单簿数据
    orderbook_data = {
        'bids': [[100.0, 1000], [99.9, 500], [99.8, 300]],
        'asks': [[100.1, 200], [100.2, 400], [100.3, 800]]
    }
    
    result = analyzer.analyze_orderbook_imbalance(orderbook_data, 100.0)
    print(f"订单簿不平衡: {result}")
    
    # 模拟订单流数据
    recent_trades = [
        {'price': 100.0, 'size': 100, 'side': 'buy', 'timestamp': datetime.now().isoformat()},
        {'price': 100.1, 'size': 50, 'side': 'buy', 'timestamp': datetime.now().isoformat()},
        {'price': 99.9, 'size': 30, 'side': 'sell', 'timestamp': datetime.now().isoformat()}
    ]
    
    result = analyzer.analyze_order_flow(recent_trades, 100.0)
    print(f"订单流: {result}")

