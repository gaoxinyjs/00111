#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
风险管理器
统一风险管理，风险指标监控，风险限制执行，风险报告生成
"""

from typing import Dict, List, Optional, Any
from datetime import datetime, timedelta
from ..core.config_manager import get_config_manager
from ..core.logger import get_logger
from ..decision.risk_evaluator import RiskEvaluator
from ..risk.position_controller import PositionController
from ..risk.stop_loss_manager import StopLossManager
from ..risk.drawdown_controller import DrawdownController
from ..risk.alert_system import AlertSystem
from .stop_loss_utils import get_symbol_account_loss_pct
from ..core.exception import RiskException


class RiskManager:
    """风险管理器"""
    
    def __init__(self):
        """初始化风险管理器"""
        self.config_mgr = get_config_manager()
        self.logger = get_logger("risk_manager")
        
        # 初始化子模块
        self.risk_evaluator = RiskEvaluator()
        self.position_controller = PositionController()
        self.stop_loss_manager = StopLossManager()
        self.drawdown_controller = DrawdownController()
        self.alert_system = AlertSystem()
        
        # 风险指标
        self.current_risk_metrics: Dict[str, Any] = {}
        self.daily_loss: float = 0.0
        self.weekly_loss: float = 0.0
        self.last_reset_date: datetime = datetime.now().date()
    
    def check_risk_before_trade(self, symbol: str, position_size: float,
                               market_data: Dict[str, Any], 
                               is_closing: bool = False) -> bool:
        """
        交易前风险检查
        
        Args:
            symbol: 交易对符号
            position_size: 仓位大小
            market_data: 市场数据
            is_closing: 是否为平仓操作（平仓操作跳过风险检查）
            
        Returns:
            是否通过风险检查
        """
        try:
            # 平仓操作跳过风险检查（平仓是保护性操作，不会增加风险）
            if is_closing:
                self.logger.debug(f"{symbol}: 平仓操作，跳过风险检查")
                return True
            
            # 1. 检查单笔风险限制
            max_loss_per_trade = self.config_mgr.get_config('risk', 'risk_limits.max_loss_per_trade')
            account_loss_pct = get_symbol_account_loss_pct(symbol, self.config_mgr)
            if account_loss_pct <= 0:
                account_loss_pct = self.config_mgr.get_config('risk', 'stop_loss.account_stop_loss_pct', 0.015)
            estimated_loss = position_size * account_loss_pct
            
            if estimated_loss > max_loss_per_trade:
                self.logger.warning(
                    f"{symbol}: [风险检查] 单笔风险{estimated_loss:.2%}超过限制{max_loss_per_trade:.2%}，"
                    f"仓位={position_size:.2%}, 账户止损={account_loss_pct:.2%}"
                )
                self.alert_system.send_alert(
                    'risk_limit',
                    f"单笔风险超限: {symbol}, 风险={estimated_loss:.2%}, 限制={max_loss_per_trade:.2%}"
                )
                return False
            
            # 2. 检查单日风险限制
            if not self.risk_evaluator.check_daily_risk_limit(self.daily_loss):
                self.logger.warning(
                    f"{symbol}: [风险检查] 单日风险{self.daily_loss:.2%}超过限制"
                )
                self.alert_system.send_alert(
                    'daily_risk_limit',
                    f"单日风险超限: 当前损失={self.daily_loss:.2%}"
                )
                return False
            
            # 3. 检查仓位限制
            if not self.position_controller.check_position_limit(symbol, position_size):
                self.logger.warning(
                    f"{symbol}: [风险检查] 仓位限制检查失败，仓位={position_size:.2%}"
                )
                return False
            
            # 4. 检查回撤限制
            if not self.drawdown_controller.check_drawdown_limit():
                self.logger.warning(f"{symbol}: [风险检查] 回撤限制检查失败")
                self.alert_system.send_alert(
                    'drawdown_limit',
                    "回撤超过限制，暂停交易"
                )
                return False
            
            self.logger.debug(f"{symbol}: [风险检查] 所有检查通过，允许交易")
            return True
        
        except Exception as e:
            self.logger.error(f"交易前风险检查失败: {e}")
            return False
    
    def monitor_risk(self, positions: List[Dict[str, Any]], 
                    market_data: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
        """
        监控当前风险
        
        Args:
            positions: 持仓列表
            market_data: 市场数据（按交易对索引）
            
        Returns:
            风险指标
        """
        try:
            risk_metrics = {
                'total_var': 0.0,
                'total_exposure': 0.0,
                'max_position': 0.0,
                'correlation_risk': 'low',
                'liquidity_risk': 'low',
                'timestamp': datetime.now().isoformat()
            }
            
            # 计算总VaR
            total_var = 0.0
            for position in positions:
                symbol = position.get('symbol')
                size = position.get('size', 0)
                
                if symbol in market_data:
                    symbol_var = self.risk_evaluator._calculate_var(
                        symbol, size, market_data[symbol]
                    )
                    total_var += symbol_var
            
            risk_metrics['total_var'] = total_var
            risk_metrics['total_exposure'] = sum(p.get('size', 0) for p in positions)
            risk_metrics['max_position'] = max((p.get('size', 0) for p in positions), default=0.0)
            
            # 更新当前风险指标
            self.current_risk_metrics = risk_metrics
            
            return risk_metrics
        
        except Exception as e:
            self.logger.error(f"风险监控失败: {e}")
            return {}
    
    def update_loss(self, loss: float):
        """
        更新损失（用于每日/每周风险限制）
        
        Args:
            loss: 损失金额（比例）
        """
        self.daily_loss += loss
        self.weekly_loss += loss
        
        # 检查是否跨天，重置每日损失
        current_date = datetime.now().date()
        if current_date > self.last_reset_date:
            self.daily_loss = loss
            self.last_reset_date = current_date
        
        # 检查是否跨周，重置每周损失
        if current_date.weekday() == 0:  # 周一
            if (current_date - self.last_reset_date).days >= 7:
                self.weekly_loss = loss
    
    def reset_daily_loss(self):
        """重置每日损失（应在每天0点调用）"""
        self.daily_loss = 0.0
        self.logger.info("每日损失已重置")
    
    def reset_weekly_loss(self):
        """重置每周损失（应在每周一调用）"""
        self.weekly_loss = 0.0
        self.logger.info("每周损失已重置")
    
    def get_risk_report(self) -> Dict[str, Any]:
        """
        生成风险报告
        
        Returns:
            风险报告
        """
        return {
            'current_metrics': self.current_risk_metrics,
            'daily_loss': self.daily_loss,
            'weekly_loss': self.weekly_loss,
            'drawdown': self.drawdown_controller.get_current_drawdown(),
            'position_summary': self.position_controller.get_position_summary(),
            'alert_count': self.alert_system.get_alert_count(),
            'timestamp': datetime.now().isoformat()
        }


if __name__ == "__main__":
    # 测试风险管理器
    manager = RiskManager()
    
    print("风险检查...")
    passed = manager.check_risk_before_trade(
        "BTC-USDT",
        0.10,
        {'price': 50000, 'volatility': 0.25}
    )
    print(f"风险检查结果: {'通过' if passed else '未通过'}")

