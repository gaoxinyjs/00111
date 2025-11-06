#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
信号生成器
整合多维度信号，信号强度评分，信号过滤和验证
"""

from typing import Dict, List, Optional, Any
from datetime import datetime
from ..core.config_manager import get_config_manager
from ..core.logger import get_logger
from ..data.data_processor import DataProcessor
from ..analysis.deepseek_client import DeepSeekClient
from ..analysis.forward_analyzer import ForwardAnalyzer
from ..core.exception import StrategyException


class Signal:
    """交易信号"""
    
    def __init__(self, symbol: str, signal_type: str, strength: float, 
                 source: str, data: Dict[str, Any], timestamp: Optional[datetime] = None):
        """
        初始化信号
        
        Args:
            symbol: 交易对符号
            signal_type: 信号类型（buy, sell, hold）
            strength: 信号强度（0.0-1.0）
            source: 信号来源（technical, funding, chain, sentiment, ai）
            data: 信号数据
            timestamp: 信号生成时间
        """
        self.symbol = symbol
        self.type = signal_type
        self.strength = strength
        self.source = source
        self.data = data
        self.timestamp = timestamp or datetime.now()
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            'symbol': self.symbol,
            'type': self.type,
            'strength': self.strength,
            'source': self.source,
            'data': self.data,
            'timestamp': self.timestamp.isoformat()
        }


class SignalGenerator:
    """信号生成器"""
    
    def __init__(self):
        """初始化信号生成器"""
        self.config_mgr = get_config_manager()
        self.logger = get_logger("signal_generator")
        self.data_processor = DataProcessor()
        self.deepseek_client = DeepSeekClient()
        self.forward_analyzer = ForwardAnalyzer()  # 前瞻性分析器
        
        # 获取配置
        self.signal_config = self.config_mgr.get_config('trading', 'signal_generation')
        self.scoring_config = self.config_mgr.get_config('trading', 'signal_scoring')
        
        # 信号历史
        self.signal_history: List[Signal] = []
    
    def generate_technical_signal(self, symbol: str, kline_data: List[Dict[str, Any]]) -> Optional[Signal]:
        """
        生成技术面信号
        
        Args:
            symbol: 交易对符号
            kline_data: K线数据
            
        Returns:
            技术面信号
        """
        if not self.signal_config.get('technical', {}).get('enabled', True):
            return None
        
        try:
            # 计算技术指标
            df = self.data_processor.calculate_indicators(kline_data, ['MACD', 'RSI', 'BB'])
            
            if df.empty or len(df) < 2:
                return None
            
            latest = df.iloc[-1]
            prev = df.iloc[-2]
            
            # MACD信号
            macd_bullish = latest['macd'] > latest['macd_signal'] and prev['macd'] <= prev['macd_signal']
            macd_bearish = latest['macd'] < latest['macd_signal'] and prev['macd'] >= prev['macd_signal']
            
            # RSI信号
            rsi_overbought = latest['rsi'] > 70
            rsi_oversold = latest['rsi'] < 30
            rsi_neutral = 30 <= latest['rsi'] <= 70
            
            # 布林带信号
            bb_upper_touch = latest['close'] >= latest['bb_upper']
            bb_lower_touch = latest['close'] <= latest['bb_lower']
            
            # 综合判断
            buy_signals = 0
            sell_signals = 0
            
            if macd_bullish:
                buy_signals += 1
            elif macd_bearish:
                sell_signals += 1
            
            if rsi_oversold:
                buy_signals += 1
            elif rsi_overbought:
                sell_signals += 1
            
            if bb_lower_touch:
                buy_signals += 1
            elif bb_upper_touch:
                sell_signals += 1
            
            # 判断信号类型和强度（优化：更容易生成信号）
            # 计算综合强度（不仅看信号数量，还看指标强度）
            macd_hist = float(latest.get('macd_hist', 0))
            macd_strength = abs(macd_hist) / max(abs(float(latest.get('macd', 1))), 0.1) if latest.get('macd', 0) != 0 else 0
            rsi = float(latest['rsi'])
            rsi_strength = abs(rsi - 50) / 50.0  # RSI偏离中位的强度
            bb_position = float((latest['close'] - latest['bb_lower']) / max(latest['bb_upper'] - latest['bb_lower'], 1))
            bb_strength = abs(bb_position - 0.5) * 2  # 布林带位置强度
            
            # 计算综合倾向
            buy_tendency = 0.0
            sell_tendency = 0.0
            
            # MACD倾向（优化：更容易生成做空信号）
            if macd_bullish:
                buy_tendency += 0.3 + min(macd_strength * 0.2, 0.2)
            elif macd_bearish:
                sell_tendency += 0.3 + min(macd_strength * 0.2, 0.2)
            else:
                # MACD_Hist为负数时，增加做空倾向
                if macd_hist > 0:
                    buy_tendency += min(macd_strength * 0.2, 0.2)  # 提高做多权重
                else:
                    # MACD_Hist为负，看空倾向更强
                    sell_tendency += min(abs(macd_hist) / max(abs(float(latest.get('macd', 1))), 0.1) * 0.25, 0.25)
            
            # RSI倾向（优化：提高做空信号的识别）
            if rsi_oversold:
                buy_tendency += 0.3 + min(rsi_strength * 0.2, 0.2)
            elif rsi_overbought:
                sell_tendency += 0.3 + min(rsi_strength * 0.2, 0.2)
            else:
                # RSI在45-55之间是中性，但偏向做空的门槛可以降低
                if rsi < 45:
                    buy_tendency += (45 - rsi) / 45 * 0.2  # RSI越低，做多倾向越强
                elif rsi > 55:
                    sell_tendency += (rsi - 55) / 45 * 0.2  # RSI越高，做空倾向越强（降低门槛）
                else:
                    # RSI在45-55之间，根据MACD倾向决定
                    if macd_hist < -10:  # MACD明显看空
                        sell_tendency += 0.1
                    elif macd_hist > 10:  # MACD明显看多
                        buy_tendency += 0.1
            
            # 布林带倾向
            if bb_lower_touch:
                buy_tendency += 0.2 + min(bb_strength * 0.1, 0.1)
            elif bb_upper_touch:
                sell_tendency += 0.2 + min(bb_strength * 0.1, 0.1)
            else:
                if bb_position < 0.5:
                    buy_tendency += (0.5 - bb_position) * 0.1
                else:
                    sell_tendency += (bb_position - 0.5) * 0.1
            
            # 判断最终信号（像狼一样：平衡机会和质量，抓住更多机会）
            # 降低最低强度阈值，抓住更多机会
            min_strength = 0.20  # 降低最低强度阈值，抓住更多机会
            
            # 要求至少1-2个指标确认（降低要求以抓住更多机会）
            confirm_count = 0
            if macd_bullish or (macd_hist > 5):
                confirm_count += 1
            if rsi_oversold or (rsi < 45):
                confirm_count += 1
            if bb_lower_touch or (bb_position < 0.3):
                confirm_count += 1
            
            # 计算倾向差异
            tendency_diff = abs(buy_tendency - sell_tendency)
            
            # 要求至少1个指标确认，或倾向差异明显（降低要求以抓住更多机会）
            requires_confirmation = confirm_count >= 1 or tendency_diff > 0.12
            
            if buy_tendency > sell_tendency:
                # 做多：降低要求以抓住更多机会（但仍保持质量）
                if buy_tendency > min_strength and requires_confirmation:
                    # 做多倾向明显且有确认
                    signal_type = 'buy'
                    strength = min(1.0, buy_tendency * 1.2)  # 增强确认的信号强度
                elif buy_tendency > 0.25 and tendency_diff > 0.12:
                    # 即使不是最强，但有明显的倾向（降低要求）
                    signal_type = 'buy'
                    strength = min(0.7, buy_tendency)
                elif buy_tendency > 0.20 and tendency_diff > 0.08:
                    # 进一步降低要求，抓住更多机会
                    signal_type = 'buy'
                    strength = min(0.6, buy_tendency)
                elif buy_tendency > 0.15 and tendency_diff > 0.05:
                    # 大幅降低要求，抓住任何可能的机会
                    signal_type = 'buy'
                    strength = min(0.55, buy_tendency)
                else:
                    signal_type = 'hold'
                    strength = 0.0
            elif sell_tendency > buy_tendency:
                # 做空：降低要求以抓住更多机会（但仍保持质量）
                if sell_tendency > min_strength and requires_confirmation:
                    # 做空倾向明显且有确认
                    signal_type = 'sell'
                    strength = min(1.0, sell_tendency * 1.2)  # 增强确认的信号强度
                elif sell_tendency > 0.25 and tendency_diff > 0.12:
                    # 即使不是最强，但有明显的倾向（降低要求）
                    signal_type = 'sell'
                    strength = min(0.7, sell_tendency)
                elif sell_tendency > 0.20 and tendency_diff > 0.08:
                    # 进一步降低要求，抓住更多机会
                    signal_type = 'sell'
                    strength = min(0.6, sell_tendency)
                elif sell_tendency > 0.15 and tendency_diff > 0.05:
                    # 大幅降低要求，抓住任何可能的机会
                    signal_type = 'sell'
                    strength = min(0.55, sell_tendency)
                else:
                    signal_type = 'hold'
                    strength = 0.0
            else:
                # 倾向相等或接近，不生成信号（避免假信号）
                signal_type = 'hold'
                strength = 0.0
            
            if strength > 0:
                return Signal(
                    symbol=symbol,
                    signal_type=signal_type,
                    strength=strength,
                    source='technical',
                    data={
                        'macd': float(latest['macd']),
                        'macd_signal': float(latest['macd_signal']),
                        'macd_hist': float(latest['macd_hist']),
                        'rsi': float(latest['rsi']),
                        'bb_position': bb_position,
                        'buy_tendency': buy_tendency,
                        'sell_tendency': sell_tendency,
                        'buy_signals': buy_signals,
                        'sell_signals': sell_signals
                    }
                )
        
        except Exception as e:
            self.logger.error(f"生成技术面信号失败 {symbol}: {e}")
        
        return None
    
    def generate_funding_signal(self, symbol: str, funding_data: Dict[str, Any]) -> Optional[Signal]:
        """
        生成资金面信号
        
        Args:
            symbol: 交易对符号
            funding_data: 资金面数据
            
        Returns:
            资金面信号
        """
        if not self.signal_config.get('funding', {}).get('enabled', True):
            return None
        
        try:
            large_order_threshold = self.signal_config.get('funding', {}).get('large_order_threshold', 100000)
            
            # 分析资金流向
            large_order_flow = funding_data.get('large_order_flow', 'neutral')
            funding_rate = funding_data.get('funding_rate', 0)
            exchange_balance_change = funding_data.get('exchange_balance_change', 0)
            
            buy_signals = 0
            sell_signals = 0
            
            # 大单流向
            if large_order_flow == 'inflow':
                buy_signals += 1
            elif large_order_flow == 'outflow':
                sell_signals += 1
            
            # 资金费率（极端负费率看多，极端正费率看空）
            if funding_rate < -0.1:
                buy_signals += 1
            elif funding_rate > 0.1:
                sell_signals += 1
            
            # 交易所余额变化（余额减少看多，余额增加看空）
            if exchange_balance_change < -0.02:  # 减少2%
                buy_signals += 1
            elif exchange_balance_change > 0.02:  # 增加2%
                sell_signals += 1
            
            # 判断信号
            if buy_signals > sell_signals:
                signal_type = 'buy'
                strength = min(1.0, buy_signals / 3.0)
            elif sell_signals > buy_signals:
                signal_type = 'sell'
                strength = min(1.0, sell_signals / 3.0)
            else:
                signal_type = 'hold'
                strength = 0.0
            
            if strength > 0:
                return Signal(
                    symbol=symbol,
                    signal_type=signal_type,
                    strength=strength,
                    source='funding',
                    data={
                        'large_order_flow': large_order_flow,
                        'funding_rate': funding_rate,
                        'exchange_balance_change': exchange_balance_change,
                        'buy_signals': buy_signals,
                        'sell_signals': sell_signals
                    }
                )
        
        except Exception as e:
            self.logger.error(f"生成资金面信号失败 {symbol}: {e}")
        
        return None
    
    def generate_ai_signal(self, symbol: str, market_data: Dict[str, Any]) -> Optional[Signal]:
        """
        生成AI分析信号
        
        Args:
            symbol: 交易对符号
            market_data: 市场数据
            
        Returns:
            AI分析信号
        """
        if not self.signal_config.get('ai_analysis', {}).get('enabled', True):
            return None
        
        try:
            # 确保market_data中包含symbol字段
            market_data_with_symbol = market_data.copy()
            market_data_with_symbol['symbol'] = symbol
            
            # 如果market_data中有价格信息，确保传递
            if 'price' not in market_data_with_symbol and 'kline' in market_data_with_symbol:
                kline_data = market_data_with_symbol.get('kline', [])
                if kline_data and len(kline_data) > 0:
                    # 尝试从K线数据中获取最新价格
                    if isinstance(kline_data, list) and len(kline_data) > 0:
                        latest_kline = kline_data[-1]
                        if isinstance(latest_kline, dict):
                            market_data_with_symbol['price'] = latest_kline.get('close', 'N/A')
            
            ai_result = self.deepseek_client.generate_signal(market_data_with_symbol)
            
            # 保存完整的AI分析结果到信号中（用于自学习）
            ai_analysis = ai_result.get('analysis', {}) if ai_result else {}
            
            # 如果AI返回非hold信号，直接使用
            if ai_result and ai_result.get('type') != 'hold':
                signal_data = ai_result.copy()
                signal_data['metadata'] = {'analysis': ai_analysis}  # 保存完整分析结果
                return Signal(
                    symbol=symbol,
                    signal_type=ai_result.get('type', 'hold'),
                    strength=ai_result.get('strength', 0.0),
                    source='ai',
                    data=signal_data
                )
            
            # 如果AI返回hold，但市场有明显趋势，根据技术指标生成信号
            if ai_result and ai_result.get('type') == 'hold':
                # 获取技术指标数据
                indicators = market_data_with_symbol.get('indicators', {})
                # 从analysis中获取trend（DeepSeek返回的完整分析结果）
                analysis = ai_result.get('analysis', {})
                trend_raw = analysis.get('trend', '') if analysis else ''
                
                # 确保trend是字符串类型，避免类型错误
                if isinstance(trend_raw, dict):
                    trend = str(trend_raw.get('value', trend_raw)) if isinstance(trend_raw.get('value', None), str) else ''
                elif not isinstance(trend_raw, str):
                    trend = str(trend_raw) if trend_raw is not None else ''
                else:
                    trend = trend_raw
                
                self.logger.info(f"[AI信号优化] {symbol}: AI返回hold，趋势={trend}，尝试自动生成信号")
                
                # 根据趋势和技术指标生成信号
                if trend in ['上涨', '上升']:
                    # AI判断为上涨趋势，但建议观望，生成买入信号
                    self.logger.info(f"[AI信号优化] {symbol}: 上涨趋势，自动生成买入信号")
                    return Signal(
                        symbol=symbol,
                        signal_type='buy',
                        strength=min(0.6, ai_result.get('confidence', 0.4) * 1.2),
                        source='ai_analysis',
                        data={**ai_result, 'auto_generated': True, 'reason': 'AI判断上涨趋势但建议观望，自动生成买入信号'}
                    )
                elif trend in ['下跌', '下降', '下降趋势']:
                    # AI判断为下跌趋势，但建议观望，生成卖出信号（做空机会）
                    self.logger.info(f"[AI信号优化] {symbol}: 下跌趋势，自动生成卖出信号（做空机会）")
                    sell_strength = min(0.7, ai_result.get('confidence', 0.4) * 1.5)  # 提高做空信号强度
                    return Signal(
                        symbol=symbol,
                        signal_type='sell',
                        strength=sell_strength,
                        source='ai_analysis',
                        data={**ai_result, 'auto_generated': True, 'reason': 'AI判断下跌趋势但建议观望，自动生成卖出信号（做空机会）'}
                    )
                elif trend in ['震荡', '横盘', '震荡行情']:
                    # 震荡行情，检查技术指标（优化：更容易识别做空机会）
                    rsi = indicators.get('rsi', 50)
                    macd_hist = indicators.get('macd_hist', 0)
                    macd = indicators.get('macd', 0)
                    self.logger.info(f"[AI信号优化] {symbol}: 震荡行情，RSI={rsi:.2f}, MACD_Hist={macd_hist:.2f}, MACD={macd:.2f}")
                    
                    # 做多条件：RSI偏低且MACD为正
                    if rsi < 40 and macd_hist > 0:
                        self.logger.info(f"[AI信号优化] {symbol}: 震荡行情但技术指标偏多，生成买入信号")
                        return Signal(
                            symbol=symbol,
                            signal_type='buy',
                            strength=0.4,
                            source='ai_analysis',
                            data={**ai_result, 'auto_generated': True, 'reason': '震荡行情但技术指标偏多'}
                        )
                    # 做空条件：RSI偏高且MACD为负（降低门槛）
                    elif rsi > 58 and macd_hist < 0:
                        self.logger.info(f"[AI信号优化] {symbol}: 震荡行情但技术指标偏空，生成卖出信号（做空机会）")
                        return Signal(
                            symbol=symbol,
                            signal_type='sell',
                            strength=0.45,  # 提高做空信号强度
                            source='ai_analysis',
                            data={**ai_result, 'auto_generated': True, 'reason': '震荡行情但技术指标偏空'}
                        )
                    # 做空条件2：MACD_Hist明显为负（即使RSI不是很高）
                    elif macd_hist < -10 and rsi > 50:
                        self.logger.info(f"[AI信号优化] {symbol}: MACD明显看空(MACD_Hist={macd_hist:.2f})，生成卖出信号（做空机会）")
                        return Signal(
                            symbol=symbol,
                            signal_type='sell',
                            strength=0.4,
                            source='ai_analysis',
                            data={**ai_result, 'auto_generated': True, 'reason': f'MACD明显看空(MACD_Hist={macd_hist:.2f})'}
                        )
                    # 做空条件3：RSI偏高（降低门槛）
                    elif rsi > 55:
                        self.logger.info(f"[AI信号优化] {symbol}: RSI偏高({rsi:.2f})，生成卖出信号（做空机会）")
                        return Signal(
                            symbol=symbol,
                            signal_type='sell',
                            strength=0.35,
                            source='ai_analysis',
                            data={**ai_result, 'auto_generated': True, 'reason': f'震荡行情但RSI偏高({rsi:.2f})'}
                        )
                    # 做多条件：RSI偏低
                    elif rsi < 45:
                        self.logger.info(f"[AI信号优化] {symbol}: RSI偏低({rsi:.2f})，生成买入信号")
                        return Signal(
                            symbol=symbol,
                            signal_type='buy',
                            strength=0.35,
                            source='ai_analysis',
                            data={**ai_result, 'auto_generated': True, 'reason': f'震荡行情但RSI偏低({rsi:.2f})'}
                        )
        
        except Exception as e:
            self.logger.error(f"生成AI信号失败 {symbol}: {e}")
        
        return None
    
    def combine_signals(self, signals: List[Signal]) -> Optional[Signal]:
        """
        融合多个信号
        
        Args:
            signals: 信号列表
            
        Returns:
            融合后的信号
        """
        if not signals:
            return None
        
        # 过滤无效信号
        valid_signals = [s for s in signals if s.type != 'hold' and s.strength > 0]
        
        if not valid_signals:
            return None
        
        # 获取权重配置
        weights = self.scoring_config.get('weights', {})
        
        # 按来源分类信号
        signal_by_source = {}
        for signal in valid_signals:
            if signal.source not in signal_by_source:
                signal_by_source[signal.source] = []
            signal_by_source[signal.source].append(signal)
        
        # 计算加权评分
        buy_score = 0.0
        sell_score = 0.0
        total_weight = 0.0
        
        for source, source_signals in signal_by_source.items():
            # 取该来源最强信号
            best_signal = max(source_signals, key=lambda x: x.strength)
            
            weight = weights.get(source, 0.1)
            score = best_signal.strength * weight
            
            if best_signal.type == 'buy':
                buy_score += score
            elif best_signal.type == 'sell':
                sell_score += score
            
            total_weight += weight
        
        # 像狼一样：敏锐观察，抓住更多机会（进一步优化）
        # 要求至少2个来源的信号确认（多重确认机制）
        source_count = len(signal_by_source)
        signal_count = len(valid_signals)
        
        # 像狼一样：大幅降低基础阈值，抓住更多机会
        base_threshold = 0.25  # 大幅降低基础阈值到0.25（抓住更多机会）
        # 如果只有一个来源的信号，阈值适中
        if source_count == 1:
            threshold = 0.40  # 单一来源进一步降低要求
        elif source_count == 2:
            threshold = 0.30  # 两个来源进一步降低要求
        else:
            threshold = base_threshold  # 多个来源可以使用较低阈值
        
        # 像狼一样：要求信号得分明显高于对手（但大幅降低差异要求）
        score_diff_threshold = 0.10  # 大幅降低得分差异阈值到0.10（抓住更多机会）
        
        if buy_score > sell_score:
            score_diff = buy_score - sell_score
            if buy_score > threshold and score_diff > score_diff_threshold:
                # 做多得分高且差异明显
                final_type = 'buy'
                final_strength = min(1.0, buy_score / max(total_weight, 0.1))
                # 多重确认时增强信号强度
                if source_count >= 2:
                    final_strength = min(1.0, final_strength * 1.1)
            elif buy_score > 0.30 and score_diff > 0.15 and source_count >= 2:
                # 即使不是最强，但有多重确认且差异明显（进一步降低要求）
                final_type = 'buy'
                final_strength = min(0.7, buy_score / max(total_weight, 0.1))
            elif buy_score > 0.25 and score_diff > 0.10:
                # 进一步降低要求，抓住更多机会（但仍有一定差异）
                final_type = 'buy'
                final_strength = min(0.6, buy_score / max(total_weight, 0.1))
            elif buy_score > 0.20 and score_diff > 0.08 and source_count >= 1:
                # 再次降低要求，抓住更多小机会（但仍保持基本质量）
                final_type = 'buy'
                final_strength = min(0.55, buy_score / max(total_weight, 0.1))
            elif buy_score > 0.15 and score_diff > 0.05:
                # 进一步降低要求，抓住任何可能的机会
                final_type = 'buy'
                final_strength = min(0.50, buy_score / max(total_weight, 0.1))
            else:
                final_type = 'hold'
                final_strength = 0.0
        elif sell_score > buy_score:
            score_diff = sell_score - buy_score
            if sell_score > threshold and score_diff > score_diff_threshold:
                # 做空得分高且差异明显
                final_type = 'sell'
                final_strength = min(1.0, sell_score / max(total_weight, 0.1))
                # 多重确认时增强信号强度
                if source_count >= 2:
                    final_strength = min(1.0, final_strength * 1.1)
            elif sell_score > 0.30 and score_diff > 0.15 and source_count >= 2:
                # 即使不是最强，但有多重确认且差异明显（进一步降低要求）
                final_type = 'sell'
                final_strength = min(0.7, sell_score / max(total_weight, 0.1))
            elif sell_score > 0.25 and score_diff > 0.10:
                # 进一步降低要求，抓住更多机会（但仍有一定差异）
                final_type = 'sell'
                final_strength = min(0.6, sell_score / max(total_weight, 0.1))
            elif sell_score > 0.20 and score_diff > 0.08 and source_count >= 1:
                # 再次降低要求，抓住更多小机会（但仍保持基本质量）
                final_type = 'sell'
                final_strength = min(0.55, sell_score / max(total_weight, 0.1))
            elif sell_score > 0.15 and score_diff > 0.05:
                # 进一步降低要求，抓住任何可能的机会
                final_type = 'sell'
                final_strength = min(0.50, sell_score / max(total_weight, 0.1))
            else:
                final_type = 'hold'
                final_strength = 0.0
        else:
            # 得分接近，不生成信号（避免假信号）
            final_type = 'hold'
            final_strength = 0.0
        
        # 创建融合信号
        if final_strength > 0:
            symbol = valid_signals[0].symbol
            return Signal(
                symbol=symbol,
                signal_type=final_type,
                strength=final_strength,
                source='combined',
                data={
                    'buy_score': buy_score,
                    'sell_score': sell_score,
                    'source_signals': [s.to_dict() for s in valid_signals],
                    'combined_at': datetime.now().isoformat()
                }
            )
        
        return None
    
    def generate_forward_signal(self, symbol: str, market_data: Dict[str, Any]) -> Optional[Signal]:
        """
        生成前瞻性信号（基于订单簿、订单流等实时数据）
        
        这些指标比MACD、RSI等滞后指标更前瞻，能更早捕捉价格变化
        
        Args:
            symbol: 交易对符号
            market_data: 市场数据（包含orderbook, recent_trades, kline等）
            
        Returns:
            前瞻性信号
        """
        try:
            # 综合前瞻性分析
            forward_result = self.forward_analyzer.comprehensive_forward_analysis(market_data)
            
            prediction = forward_result.get('prediction', 'neutral')
            confidence = forward_result.get('confidence', 0.0)
            
            if prediction == 'neutral' or confidence < 0.3:
                return None
            
            # 计算信号强度（基于置信度）
            strength = min(1.0, confidence * 1.2)
            
            # 转换为信号类型
            signal_type = 'buy' if prediction == 'buy' else 'sell'
            
            return Signal(
                symbol=symbol,
                signal_type=signal_type,
                strength=strength,
                source='forward_analysis',  # 前瞻性分析
                data={
                    'forward_analysis': forward_result,
                    'signals': forward_result.get('signals', {}),
                    'note': '基于订单簿、订单流等实时数据的前瞻性预测，比技术指标更早捕捉价格变化'
                }
            )
        
        except Exception as e:
            self.logger.error(f"生成前瞻性信号失败 {symbol}: {e}")
            return None
    
    def generate_signals(self, symbol: str, market_data: Dict[str, Any]) -> List[Signal]:
        """
        生成所有维度的信号
        
        Args:
            symbol: 交易对符号
            market_data: 市场数据（包含kline, funding, chain, sentiment等）
            
        Returns:
            信号列表
        """
        signals = []
        
        # 1. 前瞻性信号（优先级最高，因为更实时）
        forward_signal = self.generate_forward_signal(symbol, market_data)
        if forward_signal:
            signals.append(forward_signal)
        
        # 2. 技术面信号（滞后指标，作为确认）
        kline_data = market_data.get('kline', [])
        if kline_data:
            technical_signal = self.generate_technical_signal(symbol, kline_data)
            if technical_signal:
                signals.append(technical_signal)
        
        # 3. 资金面信号
        funding_data = market_data.get('funding', {})
        if funding_data:
            funding_signal = self.generate_funding_signal(symbol, funding_data)
            if funding_signal:
                signals.append(funding_signal)
        
        # 4. AI分析信号
        ai_signal = self.generate_ai_signal(symbol, market_data)
        if ai_signal:
            signals.append(ai_signal)
        
        # 记录信号历史
        self.signal_history.extend(signals)
        
        # 保留最近1000条信号
        if len(self.signal_history) > 1000:
            self.signal_history = self.signal_history[-1000:]
        
        return signals


if __name__ == "__main__":
    # 测试信号生成器
    generator = SignalGenerator()
    
    # 模拟市场数据
    market_data = {
        'kline': [
            {'timestamp': i * 3600000, 'open': 50000 + i * 10, 'high': 50100 + i * 10,
             'low': 49900 + i * 10, 'close': 50050 + i * 10, 'volume': 1000 + i * 100}
            for i in range(100)
        ],
        'funding': {
            'large_order_flow': 'inflow',
            'funding_rate': -0.05,
            'exchange_balance_change': -0.03
        }
    }
    
    print("生成信号...")
    signals = generator.generate_signals("BTC-USDT", market_data)
    
    for signal in signals:
        print(f"{signal.source}信号: {signal.type} (强度: {signal.strength:.2f})")
    
    # 融合信号
    combined = generator.combine_signals(signals)
    if combined:
        print(f"\n融合信号: {combined.type} (强度: {combined.strength:.2f})")

