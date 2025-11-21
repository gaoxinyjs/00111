#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
入场时机评估器
评估入场时机，避免追高追低，确保在最佳时机入场
参考ds-main的入场时机评估逻辑
"""

from typing import Dict, Optional, Any, Tuple
from datetime import datetime
import pandas as pd
from ..core.config_manager import get_config_manager
from ..core.logger import get_logger
from ..analysis.signal_generator import Signal
from ..core.exception import StrategyException


class EntryTimingEvaluator:
    """入场时机评估器"""
    
    def __init__(self):
        """初始化入场时机评估器"""
        self.config_mgr = get_config_manager()
        self.logger = get_logger("entry_timing_evaluator")
        
        # 获取配置
        self.trading_config = self.config_mgr.get_config('trading', 'trading_optimization', {})
        self.min_entry_score = self.trading_config.get('min_entry_score', 70)  # 最小入场评分（0-100）
    
    def evaluate_entry_timing(self, signal: Signal, market_data: Dict[str, Any]) -> Tuple[bool, str, Dict[str, Any]]:
        """
        评估入场时机 - 判断当前是否是好的入场点
        
        Args:
            signal: 交易信号
            market_data: 市场数据
            
        Returns:
            (是否入场, 评估说明, 详细评估结果)
        """
        try:
            if signal.type == 'hold':
                return True, "HOLD信号无需入场时机评估", {}
            
            current_price = market_data.get('price', 0)
            if current_price <= 0:
                return False, "价格数据无效", {}
            
            reasons = []
            score = 0  # 入场时机评分（0-100，>=70才入场）
            evaluation_details = {
                'rsi_score': 0,
                'price_position_score': 0,
                'volume_score': 0,
                'kline_score': 0,
                'total_score': 0
            }
            
            # 1. RSI位置评估（避免极端区域入场）
            rsi_score, rsi_reasons = self._evaluate_rsi_position(signal, market_data)
            score += rsi_score
            reasons.extend(rsi_reasons)
            evaluation_details['rsi_score'] = rsi_score
            
            # 2. 价格位置评估（获取最近高点/低点）
            price_score, price_reasons = self._evaluate_price_position(signal, market_data)
            score += price_score
            reasons.extend(price_reasons)
            evaluation_details['price_position_score'] = price_score
            
            # 3. 成交量确认
            volume_score, volume_reasons = self._evaluate_volume_confirmation(signal, market_data)
            score += volume_score
            reasons.extend(volume_reasons)
            evaluation_details['volume_score'] = volume_score
            
            # 4. K线形态确认
            kline_score, kline_reasons = self._evaluate_kline_pattern(signal, market_data)
            score += kline_score
            reasons.extend(kline_reasons)
            evaluation_details['kline_score'] = kline_score
            
            # 确保评分在合理范围内
            score = max(0, min(100, score))
            evaluation_details['total_score'] = score
            
            # 判断是否入场
            should_enter = score >= self.min_entry_score
            
            evaluation_summary = "; ".join(reasons) if reasons else "无特殊评估"
            
            if should_enter:
                self.logger.info(
                    f"✅ [入场时机评估] {signal.symbol}: 评分={score}/100 >= {self.min_entry_score}, "
                    f"建议入场 | {evaluation_summary}"
                )
            else:
                self.logger.info(
                    f"⚠️ [入场时机评估] {signal.symbol}: 评分={score}/100 < {self.min_entry_score}, "
                    f"保持观望 | {evaluation_summary}"
                )
            
            return should_enter, evaluation_summary, evaluation_details
        
        except Exception as e:
            self.logger.error(f"入场时机评估失败 {signal.symbol}: {e}")
            # 评估失败时，如果信号强度高，允许入场（保守策略）
            if signal.strength >= 0.7:
                return True, f"评估失败但信号强度高({signal.strength:.2f})，允许入场", {}
            return False, f"入场时机评估失败: {e}", {}
    
    def _evaluate_rsi_position(self, signal: Signal, market_data: Dict[str, Any]) -> Tuple[int, list]:
        """
        评估RSI位置（避免极端区域入场）
        
        Args:
            signal: 交易信号
            market_data: 市场数据
            
        Returns:
            (评分, 原因列表)
        """
        score = 0
        reasons = []
        
        indicators = market_data.get('indicators', {})
        rsi_raw = indicators.get('rsi', 50)
        
        # 确保RSI是数字类型
        try:
            rsi = float(rsi_raw) if rsi_raw is not None else 50.0
        except (ValueError, TypeError):
            rsi = 50.0
        
        # 预先格式化RSI值，避免在f-string中使用格式说明符
        rsi_str = f"{rsi:.1f}"
        
        if signal.type == 'buy':
            if rsi > 80:
                reasons.append(f"RSI过高({rsi_str})，等待回调")
                score -= 20
            elif rsi > 70:
                reasons.append(f"RSI偏高({rsi_str})，可等待小幅回调")
                score -= 10
            elif 30 <= rsi <= 60:
                reasons.append(f"RSI处于健康区间({rsi_str})")
                score += 15
            elif rsi < 30:
                reasons.append(f"RSI超卖({rsi_str})，可考虑入场")
                score += 20
        elif signal.type == 'sell':
            if rsi < 20:
                reasons.append(f"RSI过低({rsi_str})，等待反弹")
                score -= 20
            elif rsi < 30:
                reasons.append(f"RSI偏低({rsi_str})，可等待小幅反弹")
                score -= 10
            elif 40 <= rsi <= 70:
                reasons.append(f"RSI处于健康区间({rsi_str})")
                score += 15
            elif rsi > 70:
                reasons.append(f"RSI超买({rsi_str})，可考虑入场")
                score += 20
        
        return score, reasons
    
    def _evaluate_price_position(self, signal: Signal, market_data: Dict[str, Any]) -> Tuple[int, list]:
        """
        评估价格位置（避免追高追低）
        
        Args:
            signal: 交易信号
            market_data: 市场数据
            
        Returns:
            (评分, 原因列表)
        """
        score = 0
        reasons = []
        
        try:
            current_price = market_data.get('price', 0)
            kline_data = market_data.get('kline', [])
            
            if not kline_data or len(kline_data) < 20:
                return score, reasons
            
            # 获取最近20根K线
            recent_period = 20
            recent_highs = []
            recent_lows = []
            
            for kline in kline_data[-recent_period:]:
                if isinstance(kline, dict):
                    high = float(kline.get('high', 0))
                    low = float(kline.get('low', 0))
                    if high > 0:
                        recent_highs.append(high)
                    if low > 0:
                        recent_lows.append(low)
            
            if not recent_highs or not recent_lows:
                return score, reasons
            
            recent_high = max(recent_highs)
            recent_low = min(recent_lows)
            
            if signal.type == 'buy':
                high_distance_pct = ((recent_high - current_price) / recent_high) * 100
                low_distance_pct = ((current_price - recent_low) / current_price) * 100
                
                if high_distance_pct > 2.0:
                    reasons.append(f"价格回调中（距高点{high_distance_pct:.2f}%），较好的入场时机")
                    score += 20
                elif high_distance_pct > 0.5:
                    reasons.append(f"价格小幅回调（距高点{high_distance_pct:.2f}%），时机尚可")
                    score += 10
                else:
                    reasons.append(f"价格接近高点（距高点{high_distance_pct:.2f}%），可能追高")
                    score -= 15
            elif signal.type == 'sell':
                high_distance_pct = ((recent_high - current_price) / recent_high) * 100
                low_distance_pct = ((current_price - recent_low) / current_price) * 100
                
                if low_distance_pct > 2.0:
                    reasons.append(f"价格反弹中（距低点{low_distance_pct:.2f}%），较好的入场时机")
                    score += 20
                elif low_distance_pct > 0.5:
                    reasons.append(f"价格小幅反弹（距低点{low_distance_pct:.2f}%），时机尚可")
                    score += 10
                else:
                    reasons.append(f"价格接近低点（距低点{low_distance_pct:.2f}%），可能追空")
                    score -= 15
        
        except Exception as e:
            self.logger.debug(f"价格位置评估失败: {e}")
        
        return score, reasons
    
    def _evaluate_volume_confirmation(self, signal: Signal, market_data: Dict[str, Any]) -> Tuple[int, list]:
        """
        评估成交量确认
        
        Args:
            signal: 交易信号
            market_data: 市场数据
            
        Returns:
            (评分, 原因列表)
        """
        score = 0
        reasons = []
        
        try:
            kline_data = market_data.get('kline', [])
            current_volume = market_data.get('volume_24h', 0)
            
            if not kline_data or len(kline_data) < 5:
                return score, reasons
            
            # 计算最近5根K线的平均成交量
            recent_volumes = []
            for kline in kline_data[-5:]:
                if isinstance(kline, dict):
                    volume = float(kline.get('volume', 0))
                    if volume > 0:
                        recent_volumes.append(volume)
            
            if not recent_volumes:
                return score, reasons
            
            recent_volume_avg = sum(recent_volumes) / len(recent_volumes)
            
            if recent_volume_avg > 0:
                volume_ratio = current_volume / recent_volume_avg if recent_volume_avg > 0 else 1.0
                
                if volume_ratio > 1.2:
                    reasons.append(f"成交量放大（{volume_ratio:.1f}倍），信号确认")
                    score += 15
                elif volume_ratio < 0.8:
                    reasons.append(f"成交量萎缩（{volume_ratio:.1f}倍），信号较弱")
                    score -= 10
        
        except Exception as e:
            self.logger.debug(f"成交量确认评估失败: {e}")
        
        return score, reasons
    
    def _evaluate_kline_pattern(self, signal: Signal, market_data: Dict[str, Any]) -> Tuple[int, list]:
        """
        评估K线形态确认
        
        Args:
            signal: 交易信号
            market_data: 市场数据
            
        Returns:
            (评分, 原因列表)
        """
        score = 0
        reasons = []
        
        try:
            kline_data = market_data.get('kline', [])
            
            if not kline_data or len(kline_data) < 1:
                return score, reasons
            
            # 获取最新一根K线
            last_kline = kline_data[-1]
            if isinstance(last_kline, dict):
                open_price = float(last_kline.get('open', 0))
                close_price = float(last_kline.get('close', 0))
                
                if open_price > 0 and close_price > 0:
                    if signal.type == 'buy':
                        if close_price > open_price:
                            reasons.append("当前K线为阳线，支持买入")
                            score += 10
                        elif (close_price - open_price) / open_price > -0.5:
                            reasons.append("当前K线为小阴线，可考虑等待阳线确认")
                            score += 5
                        else:
                            reasons.append("当前K线为大阴线，等待阳线反转")
                            score -= 15
                    elif signal.type == 'sell':
                        if close_price < open_price:
                            reasons.append("当前K线为阴线，支持卖出")
                            score += 10
                        elif (close_price - open_price) / open_price < 0.5:
                            reasons.append("当前K线为小阳线，可考虑等待阴线确认")
                            score += 5
                        else:
                            reasons.append("当前K线为大阳线，等待阴线反转")
                            score -= 15
        
        except Exception as e:
            self.logger.debug(f"K线形态评估失败: {e}")
        
        return score, reasons


if __name__ == "__main__":
    # 测试入场时机评估器
    evaluator = EntryTimingEvaluator()
    
    from datetime import datetime
    from ..analysis.signal_generator import Signal
    
    signal = Signal(
        symbol="BTC-USDT",
        signal_type="buy",
        strength=0.7,
        source="combined",
        data={},
        timestamp=datetime.now()
    )
    
    market_data = {
        'price': 50000,
        'indicators': {'rsi': 45},
        'kline': [
            {'open': 49000, 'close': 50000, 'high': 51000, 'low': 48000, 'volume': 1000}
            for _ in range(20)
        ],
        'volume_24h': 1200
    }
    
    should_enter, summary, details = evaluator.evaluate_entry_timing(signal, market_data)
    print(f"是否入场: {should_enter}")
    print(f"评估说明: {summary}")
    print(f"详细评估: {details}")

