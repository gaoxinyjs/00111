#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
回撤控制器
最大回撤监控，回撤限制检查，回撤恢复机制
"""

from typing import Dict, Optional, Any
from datetime import datetime
from ..core.config_manager import get_config_manager
from ..core.logger import get_logger


class DrawdownController:
    """回撤控制器"""
    
    def __init__(self):
        """初始化回撤控制器"""
        self.config_mgr = get_config_manager()
        self.logger = get_logger("drawdown_controller")
        
        # 获取配置
        drawdown_config = self.config_mgr.get_config('risk', 'position_management.drawdown_control')
        self.enabled = drawdown_config.get('enabled', True)
        self.max_drawdown = drawdown_config.get('max_drawdown', 0.20)
        self.drawdown_levels = drawdown_config.get('drawdown_levels', [])
        
        # 账户净值历史
        self.equity_history: List[Dict[str, Any]] = []
        self.peak_equity: float = 0.0
        self.current_equity: float = 0.0
        self.max_drawdown_seen: float = 0.0
    
    def update_equity(self, equity: float):
        """
        更新账户净值
        
        Args:
            equity: 当前净值
        """
        self.current_equity = equity
        
        # 更新峰值
        if equity > self.peak_equity:
            self.peak_equity = equity
        
        # 计算回撤
        if self.peak_equity > 0:
            drawdown = (self.peak_equity - equity) / self.peak_equity
            
            # 更新最大回撤
            if drawdown > self.max_drawdown_seen:
                self.max_drawdown_seen = drawdown
            
            # 记录历史
            self.equity_history.append({
                'timestamp': datetime.now(),
                'equity': equity,
                'peak_equity': self.peak_equity,
                'drawdown': drawdown
            })
            
            # 保留最近1000条记录
            if len(self.equity_history) > 1000:
                self.equity_history = self.equity_history[-1000:]
    
    def get_current_drawdown(self) -> float:
        """
        获取当前回撤
        
        Returns:
            当前回撤（比例）
        """
        if self.peak_equity <= 0:
            return 0.0
        
        return (self.peak_equity - self.current_equity) / self.peak_equity
    
    def check_drawdown_limit(self) -> bool:
        """
        检查回撤限制
        
        Returns:
            是否通过回撤限制检查
        """
        if not self.enabled:
            self.logger.debug("[回撤检查] 回撤控制已禁用，自动通过")
            return True
        
        # 如果峰值净值为0，说明还没有初始化，自动通过
        if self.peak_equity <= 0:
            self.logger.debug(f"[回撤检查] 峰值净值未初始化({self.peak_equity:.2f})，自动通过")
            return True
        
        current_drawdown = self.get_current_drawdown()
        
        if current_drawdown >= self.max_drawdown:
            self.logger.warning(
                f"[回撤检查] 回撤{current_drawdown:.2%}超过最大限制{self.max_drawdown:.2%}，"
                f"峰值净值={self.peak_equity:.2f}, 当前净值={self.current_equity:.2f}"
            )
            return False
        
        self.logger.debug(
            f"[回撤检查] 通过，当前回撤={current_drawdown:.2%}, 限制={self.max_drawdown:.2%}"
        )
        return True
    
    def get_position_coefficient(self) -> float:
        """
        根据回撤获取仓位系数
        
        Returns:
            仓位系数（0.0-1.0）
        """
        if not self.enabled:
            return 1.0
        
        current_drawdown = self.get_current_drawdown()
        
        # 根据回撤等级获取仓位系数
        for level_config in self.drawdown_levels:
            level = level_config.get('level', 0)
            coeff = level_config.get('position_coeff', 1.0)
            
            if current_drawdown >= level:
                return coeff
        
        return 1.0
    
    def reset(self):
        """重置回撤（账户恢复后调用）"""
        self.peak_equity = self.current_equity
        self.max_drawdown_seen = 0.0
        self.logger.info("回撤已重置")


if __name__ == "__main__":
    # 测试回撤控制器
    controller = DrawdownController()
    
    # 模拟净值变化
    controller.update_equity(10000)  # 初始净值
    controller.update_equity(9500)  # 回撤5%
    controller.update_equity(9000)  # 回撤10%
    
    print(f"当前回撤: {controller.get_current_drawdown():.2%}")
    print(f"仓位系数: {controller.get_position_coefficient():.2f}")
    print(f"通过检查: {controller.check_drawdown_limit()}")

