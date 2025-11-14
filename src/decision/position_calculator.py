#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
仓位计算器
基于多因子计算仓位，动态仓位调整，仓位限制检查
"""

from typing import Dict, Optional, Any
from ..core.config_manager import get_config_manager
from ..core.logger import get_logger
from ..analysis.signal_generator import Signal
from ..core.exception import StrategyException


class PositionCalculator:
    """仓位计算器"""
    
    def __init__(self):
        """初始化仓位计算器"""
        self.config_mgr = get_config_manager()
        self.logger = get_logger("position_calculator")
        
        # 获取配置
        self.position_config = self.config_mgr.get_config('risk', 'position_management')
        self.trading_config = self.config_mgr.get_config('trading', 'trading_optimization', {})
        
        # 仓位模式（固定USDT/比例/混合）
        self.position_mode = self.position_config.get('mode', 'percentage')  # 默认比例模式
        
        # 固定USDT配置
        self.fixed_usdt_per_trade = self.position_config.get('fixed_usdt_per_trade', 1000)
        self.min_usdt_per_trade = self.position_config.get('min_usdt_per_trade', 500)
        self.max_usdt_per_trade = self.position_config.get('max_usdt_per_trade', 2000)
        
        # 比例模式配置（重新设计）
        self.base_position_size = self.position_config.get('base_position_size', 0.04)  # 基础仓位4%
        self.max_position_size = self.position_config.get('max_position_size', 0.08)  # 单笔最大仓位8%
        self.min_position_size = self.position_config.get('min_position_size', 0.01)  # 单笔最小仓位1%
        self.max_total_position = self.position_config.get('max_total_position', 0.50)  # 总仓位上限50%
        
        # 仓位分级（根据信心度）
        self.position_high_confidence = self.position_config.get('position_high_confidence', 0.06)  # 高信心度：5-8%
        self.position_medium_confidence = self.position_config.get('position_medium_confidence', 0.04)  # 中等信心度：3-5%
        self.position_low_confidence = self.position_config.get('position_low_confidence', 0.02)  # 低信心度：1-3%
        
        # 信心度倍数（参考ds-main）
        confidence_multipliers = self.position_config.get('confidence_multipliers', {})
        self.confidence_high = confidence_multipliers.get('high', 1.5)
        self.confidence_medium = confidence_multipliers.get('medium', 1.0)
        self.confidence_low = confidence_multipliers.get('low', 0.5)
        
        # 信号强度倍数
        signal_multipliers = self.position_config.get('signal_strength_multipliers', {})
        self.signal_strong = signal_multipliers.get('strong', 1.2)
        self.signal_medium = signal_multipliers.get('medium', 1.0)
        self.signal_normal = signal_multipliers.get('normal', 0.8)
        self.signal_weak = signal_multipliers.get('weak', 0.6)
        self.signal_very_weak = signal_multipliers.get('very_weak', 0.4)
        
        # 入场时机倍数
        entry_multipliers = self.position_config.get('entry_timing_multipliers', {})
        self.entry_excellent = entry_multipliers.get('excellent', 1.1)
        self.entry_good = entry_multipliers.get('good', 1.0)
        self.entry_normal = entry_multipliers.get('normal', 0.9)
        self.entry_poor = entry_multipliers.get('poor', 0.8)
        
        # 波动率倍数
        volatility_multipliers = self.position_config.get('volatility_multipliers', {})
        self.volatility_low = volatility_multipliers.get('low', 1.2)
        self.volatility_medium = volatility_multipliers.get('medium', 1.0)
        self.volatility_high = volatility_multipliers.get('high', 0.8)
        self.volatility_very_high = volatility_multipliers.get('very_high', 0.6)
        
        # 趋势强度倍数
        trend_multipliers = self.position_config.get('trend_strength_multipliers', {})
        self.trend_strong = trend_multipliers.get('strong', 1.2)
        self.trend_medium = trend_multipliers.get('medium', 1.0)
        self.trend_weak = trend_multipliers.get('weak', 0.8)
        
        # 回撤控制倍数
        drawdown_multipliers = self.position_config.get('drawdown_multipliers', {})
        self.drawdown_normal = drawdown_multipliers.get('normal', 1.0)
        self.drawdown_small = drawdown_multipliers.get('small', 0.8)
        self.drawdown_medium = drawdown_multipliers.get('medium', 0.6)
        self.drawdown_large = drawdown_multipliers.get('large', 0.4)
        self.drawdown_critical = drawdown_multipliers.get('critical', 0.2)
    
    def calculate_position(self, signal: Signal, market_data: Dict[str, Any],
                          current_position: Optional[Dict[str, Any]] = None) -> float:
        """
        计算仓位（支持固定USDT和比例两种模式）
        
        Args:
            signal: 交易信号
            market_data: 市场数据
            current_position: 当前持仓信息
            
        Returns:
            仓位大小：
            - 固定USDT模式：返回USDT金额
            - 比例模式：返回比例（0.0-1.0）
        """
        try:
            # 如果信号为hold，返回0
            if signal.type == 'hold' or signal.strength <= 0:
                return 0.0
            
            pair_cfg = (market_data or {}).get('pair_config', {}) or {}
            pair_position_cfg = pair_cfg.get('position', {}) or {}
            base_position_pct = pair_position_cfg.get(
                'base',
                pair_cfg.get('base_position_size', self.base_position_size)
            )
            max_position_pct = pair_position_cfg.get(
                'max',
                pair_cfg.get('max_position_size', self.max_position_size)
            )
            min_position_pct = pair_position_cfg.get(
                'min',
                pair_cfg.get('min_position_size', self.min_position_size)
            )
            max_total_position_pct = pair_position_cfg.get(
                'max_total',
                pair_cfg.get('max_total_position', self.max_total_position)
            )
            fixed_usdt_base = pair_cfg.get('fixed_usdt_per_trade', self.fixed_usdt_per_trade)
            min_usdt = pair_cfg.get('min_usdt_per_trade', self.min_usdt_per_trade)
            max_usdt = pair_cfg.get('max_usdt_per_trade', self.max_usdt_per_trade)
            
            # 计算所有调整因子
            confidence_coeff = self._calculate_confidence_coeff(signal, market_data)
            signal_strength_coeff = self._calculate_signal_strength_coeff(signal)
            entry_timing_coeff = self._calculate_entry_timing_coeff(signal, market_data)
            volatility_coeff = self._calculate_volatility_coeff(market_data)
            trend_coeff = self._calculate_trend_coeff(market_data)
            drawdown_coeff = self._calculate_drawdown_coeff(market_data)
            
            # 根据模式计算仓位
            if self.position_mode == 'fixed_usdt':
                # 固定USDT模式
                base_usdt = fixed_usdt_base
                final_usdt = (
                    base_usdt *
                    confidence_coeff *
                    signal_strength_coeff *
                    entry_timing_coeff *
                    volatility_coeff *
                    trend_coeff *
                    drawdown_coeff
                )
                
                # 应用限制
                final_usdt = max(min_usdt, min(final_usdt, max_usdt))
                
                self.logger.info(
                    f"💰 [仓位计算-固定USDT] {signal.symbol}: "
                    f"基础={base_usdt} USDT | "
                    f"信心度={confidence_coeff:.2f} | "
                    f"信号强度={signal_strength_coeff:.2f} | "
                    f"入场时机={entry_timing_coeff:.2f} | "
                    f"波动率={volatility_coeff:.2f} | "
                    f"趋势={trend_coeff:.2f} | "
                    f"回撤={drawdown_coeff:.2f} | "
                    f"最终={final_usdt:.2f} USDT"
                )
                
                # 返回USDT金额（需要转换为仓位比例）
                # 获取账户余额
                try:
                    from ..data.okx_client import OKXClient
                    okx_client = OKXClient()
                    balance_data = okx_client.get_balance('USDT')
                    
                    # OKX API返回格式：列表，每个元素包含币种余额信息
                    available_balance = 0
                    if balance_data and isinstance(balance_data, list) and len(balance_data) > 0:
                        # 获取第一个币种的余额（通常是USDT）
                        balance_info = balance_data[0]
                        if isinstance(balance_info, dict):
                            # 获取可用余额
                            details = balance_info.get('details', [])
                            if details and isinstance(details, list) and len(details) > 0:
                                usdt_detail = details[0]
                                available_balance = float(usdt_detail.get('availBal', 0) or usdt_detail.get('availEq', 0) or 0)
                            else:
                                # 如果没有details，尝试直接获取
                                available_balance = float(balance_info.get('availBal', 0) or balance_info.get('availEq', 0) or 0)
                    
                    if available_balance > 0:
                        # 转换为仓位比例
                        position_ratio = final_usdt / available_balance
                        # 应用比例限制
                        position_ratio = min(position_ratio, max_position_pct)
                        position_ratio = max(position_ratio, min_position_pct)
                        
                        self.logger.debug(
                            f"💰 [固定USDT转比例] {signal.symbol}: "
                            f"固定USDT={final_usdt:.2f} | "
                            f"账户余额={available_balance:.2f} | "
                            f"仓位比例={position_ratio:.2%}"
                        )
                        return position_ratio
                except Exception as e:
                    self.logger.debug(f"获取账户余额失败，使用固定USDT默认比例: {e}")
                
                # 如果无法获取余额，使用默认比例
                # 假设账户余额10000 USDT，计算比例
                default_balance = 10000
                position_ratio = final_usdt / default_balance
                position_ratio = min(position_ratio, max_position_pct)
                position_ratio = max(position_ratio, min_position_pct)
                
                self.logger.debug(
                    f"💰 [固定USDT转比例-默认] {signal.symbol}: "
                    f"固定USDT={final_usdt:.2f} | "
                    f"默认余额={default_balance:.2f} | "
                    f"仓位比例={position_ratio:.2%}"
                )
                return position_ratio
            
            else:
                # 比例模式
                base_position = base_position_pct
                final_position = (
                    base_position *
                    confidence_coeff *
                    signal_strength_coeff *
                    entry_timing_coeff *
                    volatility_coeff *
                    trend_coeff *
                    drawdown_coeff
                )
                
                # 应用限制
                final_position = min(final_position, max_position_pct)
                final_position = max(min_position_pct, final_position)
                
                self.logger.info(
                    f"💰 [仓位计算-比例模式] {signal.symbol}: "
                    f"基础={base_position:.2%} | "
                    f"信心度={confidence_coeff:.2f} | "
                    f"信号强度={signal_strength_coeff:.2f} | "
                    f"入场时机={entry_timing_coeff:.2f} | "
                    f"波动率={volatility_coeff:.2f} | "
                    f"趋势={trend_coeff:.2f} | "
                    f"回撤={drawdown_coeff:.2f} | "
                    f"最终={final_position:.2%}"
                )
                
                return final_position
        
        except Exception as e:
            self.logger.error(f"仓位计算失败: {e}")
            return 0.0
    
    def _calculate_confidence_coeff(self, signal: Signal, market_data: Dict[str, Any]) -> float:
        """
        计算信心度系数（基于DeepSeek信心度）
        
        Args:
            signal: 交易信号
            market_data: 市场数据
            
        Returns:
            信心度系数
        """
        try:
            # 从signal.data中获取DeepSeek的信心度
            confidence = None
            if signal.data:
                analysis = signal.data.get('analysis', {})
                if not analysis:
                    analysis = signal.data
                confidence = analysis.get('confidence', 0.0)
            
            # 如果没有从signal中获取到，使用signal.strength
            if confidence is None or confidence == 0:
                confidence = signal.strength
            
            # 转换为系数
            if confidence >= 0.8:
                return self.confidence_high  # HIGH
            elif confidence >= 0.6:
                return self.confidence_medium  # MEDIUM
            else:
                return self.confidence_low  # LOW
        
        except Exception as e:
            self.logger.debug(f"信心度系数计算失败，使用默认值1.0: {e}")
            return 1.0
    
    def _calculate_signal_strength_coeff(self, signal: Signal) -> float:
        """
        计算信号强度系数
        
        Args:
            signal: 交易信号
            
        Returns:
            信号强度系数
        """
        try:
            strength = signal.strength
            
            if strength >= 0.7:
                return self.signal_strong
            elif strength >= 0.6:
                return self.signal_medium
            elif strength >= 0.5:
                return self.signal_normal
            elif strength >= 0.4:
                return self.signal_weak
            else:
                return self.signal_very_weak
        
        except Exception as e:
            self.logger.debug(f"信号强度系数计算失败，使用默认值1.0: {e}")
            return 1.0
    
    def _calculate_entry_timing_coeff(self, signal: Signal, market_data: Dict[str, Any]) -> float:
        """
        计算入场时机系数（基于入场评分）
        
        Args:
            signal: 交易信号
            market_data: 市场数据
            
        Returns:
            入场时机系数
        """
        try:
            # 从market_data中获取入场评分（如果有的话）
            entry_timing_score = market_data.get('entry_timing_score', None)
            
            if entry_timing_score is None:
                # 如果没有评分，返回默认值
                return 1.0
            
            if entry_timing_score >= 70:
                return self.entry_excellent
            elif entry_timing_score >= 60:
                return self.entry_good
            elif entry_timing_score >= 50:
                return self.entry_normal
            else:
                return self.entry_poor
        
        except Exception as e:
            self.logger.debug(f"入场时机系数计算失败，使用默认值1.0: {e}")
            return 1.0
    
    def _calculate_volatility_coeff(self, market_data: Dict[str, Any]) -> float:
        """
        计算波动率系数（针对15分钟K线优化）
        
        Args:
            market_data: 市场数据
            
        Returns:
            波动率系数
        """
        try:
            # 获取当前波动率（百分比形式）
            volatility = market_data.get('volatility', 0)
            
            # 如果是小数形式（0.2），转换为百分比（20%）
            if volatility < 1.0:
                volatility = volatility * 100
            
            # 根据波动率范围返回系数
            if volatility < 2.0:
                return self.volatility_low  # 低波动
            elif volatility < 4.0:
                return self.volatility_medium  # 中波动
            elif volatility < 6.0:
                return self.volatility_high  # 高波动
            else:
                return self.volatility_very_high  # 极高波动
        
        except Exception as e:
            self.logger.debug(f"波动率系数计算失败，使用默认值1.0: {e}")
            return 1.0
    
    def _calculate_trend_coeff(self, market_data: Dict[str, Any]) -> float:
        """
        计算趋势强度系数
        
        Args:
            market_data: 市场数据
            
        Returns:
            趋势强度系数
        """
        try:
            trend_analysis = market_data.get('trend_analysis', {})
            overall_trend = trend_analysis.get('overall', '震荡整理')
            
            if overall_trend in ['强势上涨', '强势下跌']:
                return self.trend_strong
            elif overall_trend in ['温和上涨', '温和下跌']:
                return self.trend_medium
            else:
                return self.trend_weak
        
        except Exception as e:
            self.logger.debug(f"趋势强度系数计算失败，使用默认值1.0: {e}")
            return 1.0
    
    def _calculate_drawdown_coeff(self, market_data: Dict[str, Any]) -> float:
        """
        计算回撤控制系数
        
        Args:
            market_data: 市场数据
            
        Returns:
            回撤控制系数
        """
        try:
            # 从market_data中获取账户回撤（如果有的话）
            drawdown = market_data.get('drawdown', 0)
            
            # 如果是小数形式，转换为百分比
            if drawdown < 1.0:
                drawdown = drawdown * 100
            
            if drawdown < 5.0:
                return self.drawdown_normal
            elif drawdown < 10.0:
                return self.drawdown_small
            elif drawdown < 15.0:
                return self.drawdown_medium
            elif drawdown < 20.0:
                return self.drawdown_large
            else:
                return self.drawdown_critical
        
        except Exception as e:
            self.logger.debug(f"回撤控制系数计算失败，使用默认值1.0: {e}")
            return 1.0
    
    def _calculate_market_state_coeff(self, market_data: Dict[str, Any]) -> float:
        """
        计算市场状态系数
        
        Args:
            market_data: 市场数据
            
        Returns:
            市场状态系数（0.6-1.3）
        """
        try:
            # 简单的市场状态判断
            price_change_24h = market_data.get('change_24h', 0)
            volume_24h = market_data.get('volume_24h', 0)
            
            # 判断市场状态
            if price_change_24h > 5:
                # 强势上涨
                return 1.3
            elif price_change_24h > 0:
                # 温和上涨
                return 1.0
            elif price_change_24h > -5:
                # 横盘震荡
                return 0.8
            elif price_change_24h > -10:
                # 温和下跌
                return 0.7
            else:
                # 强势下跌
                return 0.6
        
        except Exception as e:
            self.logger.warning(f"市场状态系数计算失败，使用默认值1.0: {e}")
            return 1.0
    
    def _calculate_position_adjust_coeff(self, signal: Signal,
                                        current_position: Optional[Dict[str, Any]]) -> float:
        """
        计算当前持仓调整系数
        
        Args:
            signal: 交易信号
            current_position: 当前持仓信息
            
        Returns:
            调整系数
        """
        if not current_position:
            return 1.0
        
        try:
            current_size = current_position.get('size', 0)
            current_side = current_position.get('side', 'none')
            
            # 如果当前无持仓，不需要调整
            if current_size == 0 or current_side == 'none':
                return 1.0
            
            # 如果信号方向与当前持仓相反，需要先平仓
            if (signal.type == 'buy' and current_side == 'sell') or \
               (signal.type == 'sell' and current_side == 'buy'):
                # 先平仓，新仓位为0（实际应该先平仓，这里返回0表示需要先平仓）
                return 0.0
            
            # 如果信号方向与当前持仓相同，可以考虑加仓或减仓
            # 这里简化处理，返回1.0（实际应该根据盈亏情况决定）
            return 1.0
        
        except Exception as e:
            self.logger.warning(f"持仓调整系数计算失败，使用默认值1.0: {e}")
            return 1.0


if __name__ == "__main__":
    # 测试仓位计算器
    calculator = PositionCalculator()
    
    # 创建测试信号
    from datetime import datetime
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
        'change_24h': 2.5,
        'volume_24h': 1000000,
        'volatility': 0.25
    }
    
    position = calculator.calculate_position(signal, market_data)
    print(f"计算仓位: {position:.2%}")

