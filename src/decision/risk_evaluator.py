#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
风险评估器
实时风险评估，风险指标计算，风险预警，风险限制检查
"""

from typing import Dict, Optional, Any
import numpy as np
from ..core.config_manager import get_config_manager
from ..core.logger import get_logger
from ..analysis.signal_generator import Signal
from ..core.exception import RiskException
from ..risk.stop_loss_utils import (
    get_symbol_account_loss_pct,
    get_symbol_leverage,
    account_pct_to_price_pct,
)


class RiskEvaluator:
    """风险评估器"""
    
    def __init__(self):
        """初始化风险评估器"""
        self.config_mgr = get_config_manager()
        self.logger = get_logger("risk_evaluator")
        
        # 获取配置
        self.risk_config = self.config_mgr.get_config('risk', 'risk_limits')
        self.stop_loss_config = self.config_mgr.get_config('risk', 'stop_loss')
        self.var_config = self.config_mgr.get_config('risk', 'var')
        self.trading_config = self.config_mgr.get_config('trading', 'trading_optimization', {})
    
    def evaluate_risk(self, symbol: str, signal: Signal, position_size: float,
                      market_data: Dict[str, Any],
                      current_position: Optional[Dict[str, Any]] = None,
                      is_deepseek_decision: bool = False,
                      deepseek_confidence: float = 0.0) -> Dict[str, Any]:
        """
        评估交易风险
        
        Args:
            symbol: 交易对符号
            signal: 交易信号
            position_size: 仓位大小
            market_data: 市场数据
            current_position: 当前持仓信息
            is_deepseek_decision: 是否为DeepSeek决策（默认False）
            deepseek_confidence: DeepSeek信心度（默认0.0）
            
        Returns:
            风险评估结果
        """
        try:
            risk_result = {
                'symbol': symbol,
                'passed': False,
                'risk_level': 'unknown',
                'warnings': [],
                'var': 0.0,
                'stop_loss': None,
                'take_profit': None
            }
            
            # 1. 检查单笔风险限制
            max_loss_per_trade = self.risk_config.get('max_loss_per_trade', 0.02)
            account_loss_pct = get_symbol_account_loss_pct(symbol, self.config_mgr)
            if account_loss_pct <= 0:
                account_loss_pct = self.stop_loss_config.get('account_stop_loss_pct', 0.015)
            estimated_loss = position_size * account_loss_pct
            
            if estimated_loss > max_loss_per_trade:
                risk_result['warnings'].append(
                    f"单笔风险{estimated_loss:.2%}超过限制{max_loss_per_trade:.2%}"
                )
                self.logger.warning(
                    f"{symbol}: [风险评估] 单笔风险超限: "
                    f"仓位={position_size:.2%}, 账户止损={account_loss_pct:.2%}, "
                    f"估计损失={estimated_loss:.2%}, 限制={max_loss_per_trade:.2%}"
                )
                return risk_result
            
            # 2. 计算VaR
            var = self._calculate_var(symbol, position_size, market_data)
            risk_result['var'] = var
            
            target_var = self.var_config.get('target_var', 0.05)  # 默认提高到5%
            # 放宽VaR检查：只有在VaR明显超过目标时才拒绝（允许一定的超出）
            var_tolerance = target_var * 1.5  # 允许超出50%
            if var > var_tolerance:
                risk_result['warnings'].append(
                    f"VaR {var:.2%}超过容忍度{var_tolerance:.2%}"
                )
                self.logger.warning(
                    f"{symbol}: [风险评估] VaR超限: "
                    f"VaR={var:.2%}, 容忍度={var_tolerance:.2%}, 目标={target_var:.2%}, 仓位={position_size:.2%}"
                )
                return risk_result
            
            # 3. 计算止损止盈（账户盈亏1.5%止损，3%止盈，考虑杠杆倍数）
            # 注意：止盈止损应该基于开仓价格计算，而不是当前价格
            # 如果没有开仓价格，使用当前价格作为参考（但会在订单成交后基于实际成交价格重新计算）
            entry_price = market_data.get('entry_price') or market_data.get('price', 0)
            if entry_price > 0:
                leverage = get_symbol_leverage(symbol, self.config_mgr)
                
                # 根据市场波动率调整止损止盈
                atr_pct = market_data.get('indicators', {}).get('atr_pct', 1.0)
                if isinstance(atr_pct, str):
                    try:
                        atr_pct = float(atr_pct.replace('%', ''))
                    except:
                        atr_pct = 1.0
                
                # 根据波动率调整止损止盈
                base_account_stop = self.stop_loss_config.get('account_stop_loss_pct', 0.015)
                if atr_pct < 1.0:
                    account_stop_loss_pct = min(base_account_stop, 0.012)
                    account_take_profit_pct = 0.025
                elif atr_pct < 2.0:
                    account_stop_loss_pct = base_account_stop
                    account_take_profit_pct = 0.03
                else:
                    account_stop_loss_pct = max(base_account_stop, 0.02)
                    account_take_profit_pct = 0.04
                
                # 根据信号强度调整止盈（强烈信号可以提高止盈）
                signal_strength = signal.strength if hasattr(signal, 'strength') else 0.5
                if signal_strength > 0.75:
                    # 强烈信号：止盈3.5%
                    account_take_profit_pct = min(account_take_profit_pct * 1.17, 0.035)
                elif signal_strength < 0.4:
                    # 弱信号：止盈2.5%
                    account_take_profit_pct = max(account_take_profit_pct * 0.83, 0.025)
                
                stop_loss_price_change_pct = account_pct_to_price_pct(
                    account_stop_loss_pct, leverage, self.stop_loss_config
                )
                take_profit_price_change_pct = account_pct_to_price_pct(
                    account_take_profit_pct, leverage, self.stop_loss_config, clamp=False
                )
                if take_profit_price_change_pct < stop_loss_price_change_pct * 1.5:
                    take_profit_price_change_pct = stop_loss_price_change_pct * 1.5
                
                if signal.type == 'buy':
                    # 做多：止损价格 = 开仓价格 * (1 - 价格变动百分比)，止盈价格 = 开仓价格 * (1 + 价格变动百分比)
                    risk_result['stop_loss'] = entry_price * (1 - stop_loss_price_change_pct)
                    risk_result['take_profit'] = entry_price * (1 + take_profit_price_change_pct)
                elif signal.type == 'sell':
                    # 做空：止损价格 = 开仓价格 * (1 + 价格变动百分比)，止盈价格 = 开仓价格 * (1 - 价格变动百分比)
                    # 做空时，价格上涨触发止损，所以止损价格应该在开仓价格上方
                    risk_result['stop_loss'] = entry_price * (1 + stop_loss_price_change_pct)
                    # 做空时，价格下跌触发止盈，所以止盈价格应该在开仓价格下方
                    risk_result['take_profit'] = entry_price * (1 - take_profit_price_change_pct)
                    self.logger.debug(
                        f"{signal.symbol}: [止损止盈计算] 做空 | "
                        f"开仓价格={entry_price:.4f}, "
                        f"止损价格={risk_result['stop_loss']:.4f} (价格变动{stop_loss_price_change_pct*100:.3f}%, 账户盈亏{account_stop_loss_pct*100:.1f}%), "
                        f"止盈价格={risk_result['take_profit']:.4f} (价格变动{take_profit_price_change_pct*100:.3f}%, 账户盈亏{account_take_profit_pct*100:.1f}%)"
                    )
            
            # 4. 多重过滤机制（参考ds-main）
            # 4.1 市场波动率过滤（更严格：阈值降低到4%）
            volatility = market_data.get('volatility', 0)
            if volatility > 0:
                max_volatility_threshold = self.trading_config.get('max_volatility_threshold', 4.0)  # 4%波动率限制
                volatility_pct = volatility * 100
                if volatility_pct > max_volatility_threshold:
                    risk_result['warnings'].append(f"市场波动率过高({volatility_pct:.2f}% > {max_volatility_threshold}%)")
                    self.logger.warning(
                        f"{symbol}: [风险评估] 市场波动率过高: {volatility_pct:.2f}% > {max_volatility_threshold}%"
                    )
                    return risk_result
            
            # 4.2 趋势确认过滤（针对15分钟K线优化：放宽要求）
            # 如果配置中require_trend_confirmation为false，跳过趋势确认
            if self.trading_config.get('require_trend_confirmation', False):
                trend_analysis = market_data.get('trend_analysis', {})
                indicators = market_data.get('indicators', {})
                
                overall_trend = trend_analysis.get('overall', '震荡整理')
                macd_trend = trend_analysis.get('macd', '')
                rsi = indicators.get('rsi', 50)
                
                # 如果是震荡市场，建议观望（但只记录警告，不直接拒绝）
                if overall_trend == '震荡整理':
                    risk_result['warnings'].append("震荡市场，建议观望")
                    self.logger.debug(f"{symbol}: [风险评估] 震荡市场，建议观望（但不拒绝交易）")
                    # 不直接return，允许继续交易
                
                # 检查趋势强度（放宽要求，只记录警告）
                if signal.type == 'buy':
                    if overall_trend in ['强势下跌', '震荡整理']:
                        risk_result['warnings'].append(f"趋势不匹配（{overall_trend}）")
                        self.logger.debug(f"{symbol}: [风险评估] 趋势不匹配: {overall_trend}（但不拒绝交易）")
                        # 不直接return，允许继续交易
                    if rsi < 50 or macd_trend not in ['bullish', '']:
                        risk_result['warnings'].append(f"技术指标不支持（RSI={rsi:.1f}, MACD={macd_trend}）")
                        self.logger.debug(f"{symbol}: [风险评估] 技术指标不支持: RSI={rsi:.1f}, MACD={macd_trend}（但不拒绝交易）")
                        # 不直接return，允许继续交易
                elif signal.type == 'sell':
                    if overall_trend in ['强势上涨', '震荡整理']:
                        risk_result['warnings'].append(f"趋势不匹配（{overall_trend}）")
                        self.logger.debug(f"{symbol}: [风险评估] 趋势不匹配: {overall_trend}（但不拒绝交易）")
                        # 不直接return，允许继续交易
                    if rsi > 50 or macd_trend not in ['bearish', '']:
                        risk_result['warnings'].append(f"技术指标不支持（RSI={rsi:.1f}, MACD={macd_trend}）")
                        self.logger.debug(f"{symbol}: [风险评估] 技术指标不支持: RSI={rsi:.1f}, MACD={macd_trend}（但不拒绝交易）")
                        # 不直接return，允许继续交易
            
            # 5. 评估风险等级
            risk_level = self._assess_risk_level(var, estimated_loss)
            risk_result['risk_level'] = risk_level
            
            # 6. 综合判断（针对15分钟K线优化：放宽风险等级要求）
            if len(risk_result['warnings']) == 0:
                # 没有额外警告时仍需依据风险等级严格过滤
                if risk_level in ['low', 'medium']:
                    risk_result['passed'] = True
                elif risk_level == 'high':
                    # 对于high风险等级，根据情况决定是否放行
                    # 1. 如果仓位较小（<=2%），放行
                    # 2. 如果是DeepSeek高信心度决策（>=0.65），放宽到10%仓位
                    if position_size <= 0.02:
                        risk_result['passed'] = True
                        self.logger.info(
                            f"{symbol}: [风险评估] 风险等级为high，但仓位较小({position_size:.2%})，谨慎放行"
                        )
                    elif is_deepseek_decision and deepseek_confidence >= 0.65 and position_size <= 0.10:
                        # DeepSeek高信心度决策，允许更大的仓位（最多10%）
                        risk_result['passed'] = True
                        self.logger.info(
                            f"{symbol}: [风险评估] DeepSeek高信心度决策({deepseek_confidence:.2f})，"
                            f"风险等级high但放宽限制，允许仓位{position_size:.2%}"
                        )
                    else:
                        self.logger.warning(
                            f"{symbol}: [风险评估] 风险等级{risk_level}过高，拒绝交易（仓位={position_size:.2%}）"
                        )
                else:
                    # very_high风险等级，除非是DeepSeek极高信心度，否则拒绝
                    if is_deepseek_decision and deepseek_confidence >= 0.75 and position_size <= 0.08:
                        risk_result['passed'] = True
                        self.logger.info(
                            f"{symbol}: [风险评估] DeepSeek极高信心度决策({deepseek_confidence:.2f})，"
                            f"风险等级very_high但特殊放行，允许仓位{position_size:.2%}"
                        )
                    else:
                        self.logger.warning(
                            f"{symbol}: [风险评估] 风险等级{risk_level}过高，拒绝交易（仓位={position_size:.2%}）"
                        )
            
            return risk_result
        
        except Exception as e:
            self.logger.error(f"风险评估失败 {symbol}: {e}")
            raise RiskException(f"风险评估失败: {e}")
    
    def _calculate_var(self, symbol: str, position_size: float,
                      market_data: Dict[str, Any]) -> float:
        """
        计算风险价值（VaR）
        
        Args:
            symbol: 交易对符号
            position_size: 仓位大小
            market_data: 市场数据
            
        Returns:
            VaR值（比例）
        """
        try:
            # 简化的VaR计算（使用历史波动率）
            volatility = market_data.get('volatility', 0.20)  # 默认20%波动率
            confidence_level = self.var_config.get('confidence_level', 0.95)
            
            # 参数法计算VaR（假设正态分布）
            # Z分数：95%置信度对应1.645
            z_scores = {
                0.90: 1.282,
                0.95: 1.645,
                0.99: 2.326
            }
            z_score = z_scores.get(confidence_level, 1.645)
            
            # VaR = 仓位大小 × 波动率 × Z分数
            var = position_size * volatility * z_score
            
            return var
        
        except Exception as e:
            self.logger.warning(f"VaR计算失败，使用默认值: {e}")
            return position_size * 0.05  # 默认5%
    
    def _assess_risk_level(self, var: float, estimated_loss: float) -> str:
        """
        评估风险等级
        
        Args:
            var: 风险价值
            estimated_loss: 估计损失
            
        Returns:
            风险等级（low, medium, high, very_high）
        """
        max_risk = max(var, estimated_loss)
        
        if max_risk < 0.01:
            return 'low'
        elif max_risk < 0.02:
            return 'medium'
        elif max_risk < 0.05:
            return 'high'
        else:
            return 'very_high'
    
    def check_daily_risk_limit(self, daily_loss: float) -> bool:
        """
        检查单日风险限制
        
        Args:
            daily_loss: 当日累计损失（比例）
            
        Returns:
            是否超过限制
        """
        max_loss_per_day = self.risk_config.get('max_loss_per_day', 0.05)
        return daily_loss <= max_loss_per_day
    
    def check_weekly_risk_limit(self, weekly_loss: float) -> bool:
        """
        检查单周风险限制
        
        Args:
            weekly_loss: 当周累计损失（比例）
            
        Returns:
            是否超过限制
        """
        max_loss_per_week = self.risk_config.get('max_loss_per_week', 0.10)
        return weekly_loss <= max_loss_per_week


if __name__ == "__main__":
    # 测试风险评估器
    evaluator = RiskEvaluator()
    
    # 创建测试信号
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
        'volatility': 0.25
    }
    
    risk_result = evaluator.evaluate_risk("BTC-USDT", signal, 0.10, market_data)
    print(f"风险评估: 通过={risk_result['passed']}, 风险等级={risk_result['risk_level']}")
    print(f"VaR: {risk_result['var']:.2%}")
    if risk_result['warnings']:
        print(f"警告: {risk_result['warnings']}")

