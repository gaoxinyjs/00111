#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
AI仓位管理器
使用AI分析当前持仓和盈亏情况，智能调整仓位和平仓，实现收益最大化
"""

from typing import Dict, Optional, Any, Tuple
from datetime import datetime, timedelta
from ..core.config_manager import get_config_manager
from ..core.logger import get_logger
from ..analysis.deepseek_client import DeepSeekClient
from ..risk.stop_loss_utils import get_symbol_price_stop_pct


class AIPositionManager:
    """AI仓位管理器"""
    
    def __init__(self):
        """初始化AI仓位管理器"""
        self.config_mgr = get_config_manager()
        self.logger = get_logger("ai_position_manager")
        self.deepseek_client = DeepSeekClient()
        
        # 仓位管理配置
        self.position_config = self.config_mgr.get_config('risk', 'position_management', {})
        self.stop_loss_config = self.config_mgr.get_config('risk', 'stop_loss', {})
        self.risk_limits = self.config_mgr.get_config('risk', 'risk_limits', {})
        
    def analyze_position(self, symbol: str, position: Dict[str, Any], 
                        market_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        AI分析持仓情况
        
        Args:
            symbol: 交易对符号
            position: 当前持仓信息
            market_data: 市场数据
        
        Returns:
            持仓分析结果（包含调整建议）
        """
        try:
            position_size = position.get('size', 0)
            # 兼容不同的持仓方向格式：buy/sell 转换为 long/short
            position_side_raw = position.get('side', 'long')
            if position_side_raw == 'buy':
                position_side = 'long'
            elif position_side_raw == 'sell':
                position_side = 'short'
            else:
                position_side = position_side_raw  # long或short
            
            entry_price = position.get('avg_price', 0) or position.get('average_price', 0)
            current_price = market_data.get('price', 0)
            
            if position_size <= 0 or entry_price <= 0 or current_price <= 0:
                return {
                    'action': 'hold',
                    'reason': '持仓数据无效',
                    'confidence': 0.0
                }
            
            # 计算盈亏
            if position_side == 'long':
                profit_pct = ((current_price - entry_price) / entry_price) * 100
            else:  # short
                profit_pct = ((entry_price - current_price) / entry_price) * 100
            
            # 计算持仓时间
            entry_time = position.get('entry_time')
            if isinstance(entry_time, str):
                try:
                    entry_time = datetime.fromisoformat(entry_time)
                except:
                    entry_time = datetime.now()
            elif not isinstance(entry_time, datetime):
                entry_time = datetime.now()
            
            holding_duration = (datetime.now() - entry_time).total_seconds() / 3600  # 小时
            
            # 构建持仓分析数据
            position_analysis_data = {
                'symbol': symbol,
                'position': {
                    'size': position_size,
                    'side': position_side,
                    'entry_price': entry_price,
                    'current_price': current_price,
                    'profit_pct': profit_pct,
                    'holding_duration_hours': holding_duration
                },
                'market_data': market_data,
                'indicators': market_data.get('indicators', {}),
                'multi_timeframe': market_data.get('multi_timeframe', {})
            }
            
            # 使用DeepSeek分析持仓
            analysis_result = self.deepseek_client.analyze_position(
                position_analysis_data
            )
            
            # 解析AI分析结果
            recommendation = analysis_result.get('recommendation', 'hold')
            reasoning = analysis_result.get('reasoning', '')
            confidence = analysis_result.get('confidence', 0.5)
            
            # 生成仓位调整建议
            action = 'hold'
            adjust_size = 0.0
            reason = reasoning
            
            if recommendation in ['加仓', '增加仓位', '提高仓位']:
                action = 'add'
                # 根据信心度和盈利情况决定加仓比例
                if profit_pct > 0:
                    # 盈利时加仓，根据盈利幅度和信心度
                    adjust_size = min(0.2, confidence * 0.3 * (1 + profit_pct / 100))
                else:
                    # 亏损时谨慎加仓
                    adjust_size = min(0.1, confidence * 0.15)
                reason = f"AI建议加仓：{reasoning}"
            elif recommendation in ['减仓', '减少仓位', '降低仓位', '部分平仓']:
                action = 'reduce'
                # 根据情况决定减仓比例
                if profit_pct > 0:
                    # 盈利时部分止盈
                    adjust_size = min(0.5, confidence * 0.4)
                else:
                    # 亏损时减仓降低风险
                    adjust_size = min(0.3, confidence * 0.25)
                reason = f"AI建议减仓：{reasoning}"
            elif recommendation in ['平仓', '全部平仓', '止盈', '止损']:
                action = 'close'
                adjust_size = 1.0  # 全部平仓
                reason = f"AI建议平仓：{reasoning}"
            elif recommendation in ['持有', '保持', '观望']:
                action = 'hold'
                adjust_size = 0.0
                reason = f"AI建议持有：{reasoning}"
            
            return {
                'action': action,
                'adjust_size': adjust_size,
                'reason': reason,
                'confidence': confidence,
                'profit_pct': profit_pct,
                'holding_duration_hours': holding_duration,
                'analysis': analysis_result
            }
            
        except Exception as e:
            self.logger.error(f"AI分析持仓失败 {symbol}: {e}")
            return {
                'action': 'hold',
                'reason': f'分析失败: {e}',
                'confidence': 0.0
            }
    
    def calculate_dynamic_stop_loss(self, symbol: str, position: Dict[str, Any],
                                    market_data: Dict[str, Any]) -> Tuple[Optional[float], Optional[float]]:
        """
        计算动态止盈止损
        
        Args:
            symbol: 交易对符号
            position: 当前持仓
            market_data: 市场数据
        
        Returns:
            (止损价格, 止盈价格)
        """
        try:
            # 兼容不同的持仓方向格式
            position_side_raw = position.get('side', 'long')
            if position_side_raw == 'buy':
                position_side = 'long'
            elif position_side_raw == 'sell':
                position_side = 'short'
            else:
                position_side = position_side_raw
            
            entry_price = position.get('avg_price', 0) or position.get('average_price', 0)
            current_price = market_data.get('price', 0)
            
            if entry_price <= 0 or current_price <= 0:
                return None, None
            
            # 计算当前盈亏
            if position_side == 'long':
                profit_pct = ((current_price - entry_price) / entry_price) * 100
            else:  # short
                profit_pct = ((entry_price - current_price) / entry_price) * 100
            
            # 基础止损止盈
            base_stop_loss_pct = get_symbol_price_stop_pct(symbol, self.config_mgr)
            take_profit_pct = 0.15  # 目标止盈15%
            
            # 动态止损：盈利后移动止损
            if self.stop_loss_config.get('trailing_stop', {}).get('enabled', True):
                activation_profit = self.stop_loss_config.get('trailing_stop', {}).get('activation_profit', 0.10)
                trailing_pct = self.stop_loss_config.get('trailing_stop', {}).get('trailing_pct', 0.03)
                
                if profit_pct > activation_profit * 100:
                    # 盈利超过激活阈值，使用移动止损
                    if position_side == 'long':
                        stop_loss_price = current_price * (1 - trailing_pct)
                        # 止损不能低于成本价
                        if stop_loss_price < entry_price:
                            stop_loss_price = entry_price * (1 - base_stop_loss_pct)
                    else:  # short
                        stop_loss_price = current_price * (1 + trailing_pct)
                        # 止损不能高于成本价
                        if stop_loss_price > entry_price:
                            stop_loss_price = entry_price * (1 + base_stop_loss_pct)
                else:
                    # 未盈利，使用基础止损
                    if position_side == 'long':
                        stop_loss_price = entry_price * (1 - base_stop_loss_pct)
                    else:  # short
                        stop_loss_price = entry_price * (1 + base_stop_loss_pct)
            else:
                # 不使用移动止损，固定止损
                if position_side == 'long':
                    stop_loss_price = entry_price * (1 - base_stop_loss_pct)
                else:  # short
                    stop_loss_price = entry_price * (1 + base_stop_loss_pct)
            
            # 计算止盈价格
            if position_side == 'long':
                take_profit_price = entry_price * (1 + take_profit_pct)
            else:  # short
                take_profit_price = entry_price * (1 - take_profit_pct)
            
            return stop_loss_price, take_profit_price
            
        except Exception as e:
            self.logger.error(f"计算动态止损止盈失败 {symbol}: {e}")
            return None, None
    
    def should_adjust_position(self, symbol: str, position: Dict[str, Any],
                               market_data: Dict[str, Any],
                               enable_ai: bool = True) -> Optional[Dict[str, Any]]:
        """
        判断是否应该调整仓位
        
        Args:
            symbol: 交易对符号
            position: 当前持仓
            market_data: 市场数据
            enable_ai: 是否调用AI分析（设为False时仅执行风险检查）
        
        Returns:
            仓位调整建议（action: add/reduce/close/hold, adjust_size: 调整比例）
        """
        try:
            # 兼容不同的持仓方向格式
            position_side_raw = position.get('side', 'long')
            if position_side_raw == 'buy':
                position_side = 'long'
            elif position_side_raw == 'sell':
                position_side = 'short'
            else:
                position_side = position_side_raw
            
            entry_price = position.get('avg_price', 0) or position.get('average_price', 0)
            current_price = market_data.get('price', 0)
            position_size = float(position.get('size', 0) or position.get('position_size', 0))
            
            if position_size <= 0 or entry_price <= 0 or current_price <= 0:
                return None
            
            if position_side == 'long':
                profit_pct = ((current_price - entry_price) / entry_price) * 100
            else:  # short
                profit_pct = ((entry_price - current_price) / entry_price) * 100
            
            action = 'hold'
            adjust_size = 0.0
            confidence = 0.0
            reason = ''
            analysis_payload: Dict[str, Any] = {}
            
            if enable_ai:
                analysis = self.analyze_position(symbol, position, market_data)
                action = analysis.get('action', 'hold')
                adjust_size = analysis.get('adjust_size', 0.0)
                confidence = analysis.get('confidence', 0.0)
                reason = analysis.get('reason', '')
                analysis_payload = analysis.get('analysis', {})
                profit_pct = analysis.get('profit_pct', profit_pct)
            else:
                reason = 'AI分析已禁用'
            
            # 计算动态止损止盈
            stop_loss_price, take_profit_price = self.calculate_dynamic_stop_loss(
                symbol, position, market_data
            )
            
            # 检查是否触发止损止盈
            if stop_loss_price and current_price > 0:
                if position_side == 'long' and current_price <= stop_loss_price:
                    # 触发止损
                    return {
                        'action': 'close',
                        'reason': f'触发止损：当前价格{current_price} <= 止损价{stop_loss_price:.2f}',
                        'adjust_size': 1.0,
                        'stop_loss_triggered': True,
                        'confidence': max(confidence, 0.9),
                        'profit_pct': profit_pct,
                        'stop_loss_price': stop_loss_price,
                        'take_profit_price': take_profit_price,
                        'analysis': analysis_payload
                    }
                elif position_side == 'short' and current_price >= stop_loss_price:
                    # 触发止损
                    return {
                        'action': 'close',
                        'reason': f'触发止损：当前价格{current_price} >= 止损价{stop_loss_price:.2f}',
                        'adjust_size': 1.0,
                        'stop_loss_triggered': True,
                        'confidence': max(confidence, 0.9),
                        'profit_pct': profit_pct,
                        'stop_loss_price': stop_loss_price,
                        'take_profit_price': take_profit_price,
                        'analysis': analysis_payload
                    }
            
            if take_profit_price and current_price > 0:
                if position_side == 'long' and current_price >= take_profit_price:
                    # 触发止盈
                    return {
                        'action': 'close',
                        'reason': f'触发止盈：当前价格{current_price} >= 止盈价{take_profit_price:.2f}',
                        'adjust_size': 1.0,
                        'take_profit_triggered': True,
                        'confidence': max(confidence, 0.9),
                        'profit_pct': profit_pct,
                        'stop_loss_price': stop_loss_price,
                        'take_profit_price': take_profit_price,
                        'analysis': analysis_payload
                    }
                elif position_side == 'short' and current_price <= take_profit_price:
                    # 触发止盈
                    return {
                        'action': 'close',
                        'reason': f'触发止盈：当前价格{current_price} <= 止盈价{take_profit_price:.2f}',
                        'adjust_size': 1.0,
                        'take_profit_triggered': True,
                        'confidence': max(confidence, 0.9),
                        'profit_pct': profit_pct,
                        'stop_loss_price': stop_loss_price,
                        'take_profit_price': take_profit_price,
                        'analysis': analysis_payload
                    }
            
            # 像狼一样：获利就跑，亏损就撤（快速出击，快速撤退）
            # 检查是否达到快速止盈目标（盈利超过2%立即止盈，像狼抓到猎物就撤）
            if profit_pct > 2.0:
                return {
                    'action': 'close',
                    'reason': f'快速止盈：当前盈亏{profit_pct:.2f}%，像狼一样获利就跑',
                    'adjust_size': 1.0,
                    'confidence': 0.95,
                    'profit_pct': profit_pct,
                    'take_profit_triggered': True,
                    'wolf_strategy': True,  # 标记为狼式策略
                    'analysis': analysis_payload
                }
            
            # 检查是否达到快速止损条件（亏损超过2%立即止损，像狼一样保护自己）
            if profit_pct < -2.0:
                return {
                    'action': 'close',
                    'reason': f'快速止损：当前盈亏{profit_pct:.2f}%，像狼一样快速撤退',
                    'adjust_size': 1.0,
                    'confidence': 0.95,
                    'profit_pct': profit_pct,
                    'stop_loss_triggered': True,
                    'wolf_strategy': True,  # 标记为狼式策略
                    'analysis': analysis_payload
                }
            
            # ⚠️ 优先处理AI建议平仓（来自DeepSeek的分析）
            # 如果AI建议平仓，应该优先于快速止损止盈（除非是紧急止损）
            if enable_ai and action == 'close':
                # AI建议平仓优先级最高（除非是紧急止损）
                # 如果盈亏在-2%到2%之间，AI建议平仓应该执行
                if -2.0 <= profit_pct <= 2.0:
                    return {
                        'action': 'close',
                        'reason': reason,
                        'adjust_size': 1.0,
                        'confidence': confidence,
                        'profit_pct': profit_pct,
                        'analysis': analysis_payload,
                        'ai_recommended': True  # 标记为AI推荐
                    }
                # 如果盈亏超过±2%，快速止损止盈优先，但保留AI分析信息
                # 这种情况下快速止损止盈已经在上面的逻辑中处理了
            
            # 如果AI建议调整仓位且未触发止损止盈
            if enable_ai and action in ['add', 'reduce']:
                return {
                    'action': action,
                    'reason': reason,
                    'adjust_size': adjust_size,
                    'confidence': confidence,
                    'profit_pct': profit_pct,
                    'stop_loss_price': stop_loss_price,
                    'take_profit_price': take_profit_price,
                    'analysis': analysis_payload,
                    'ai_recommended': True  # 标记为AI推荐
                }
            elif enable_ai and action == 'close':
                # 如果AI建议平仓但盈亏超过±2%，快速止损止盈已处理，这里不再重复
                # 但如果快速止损止盈没有触发，返回AI建议
                return {
                    'action': 'close',
                    'reason': reason,
                    'adjust_size': 1.0,
                    'confidence': confidence,
                    'profit_pct': profit_pct,
                    'analysis': analysis_payload,
                    'ai_recommended': True  # 标记为AI推荐
                }
            
            return None
            
        except Exception as e:
            self.logger.error(f"判断仓位调整失败 {symbol}: {e}")
            return None

