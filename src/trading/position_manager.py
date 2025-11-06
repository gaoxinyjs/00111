#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
持仓管理器
持仓实时跟踪，持仓盈亏计算，持仓风险监控，持仓历史记录
"""

from typing import Dict, List, Optional, Any
from datetime import datetime
from ..core.config_manager import get_config_manager
from ..core.logger import get_logger
from ..trading.order_manager import Order
from ..risk.position_controller import PositionController


class PositionManager:
    """持仓管理器"""
    
    def __init__(self):
        """初始化持仓管理器"""
        self.config_mgr = get_config_manager()
        self.logger = get_logger("position_manager")
        self.position_controller = PositionController()
        
        # 持仓历史
        self.position_history: List[Dict[str, Any]] = []
    
    def update_position_from_order(self, order: Order):
        """
        从订单更新持仓
        
        Args:
            order: 订单对象
        """
        try:
            if order.status.value != 'filled':
                return
            
            symbol = order.symbol
            side = order.side
            filled_size = order.filled_size
            average_price = order.average_price or order.filled_price
            
            # 更新持仓
            self.position_controller.update_position(
                symbol, side, filled_size, average_price
            )
            
            # 更新持仓历史
            position = self.position_controller.get_position(symbol)
            if position:
                self.position_history.append({
                    'timestamp': datetime.now(),
                    'symbol': symbol,
                    'position': position.copy()
                })
                
                # 保留最近10000条历史
                if len(self.position_history) > 10000:
                    self.position_history = self.position_history[-10000:]
                
                self.logger.info(
                    f"持仓更新: {symbol}, {side} {filled_size} @ {average_price}"
                )
        
        except Exception as e:
            self.logger.error(f"更新持仓失败: {e}")
    
    def get_position(self, symbol: str) -> Optional[Dict[str, Any]]:
        """获取持仓"""
        return self.position_controller.get_position(symbol)
    
    def get_all_positions(self) -> Dict[str, Dict[str, Any]]:
        """获取所有持仓"""
        return self.position_controller.get_all_positions()
    
    def calculate_unrealized_pnl(self, symbol: str, current_price: float) -> float:
        """
        计算未实现盈亏
        
        Args:
            symbol: 交易对符号
            current_price: 当前价格
            
        Returns:
            未实现盈亏
        """
        position = self.get_position(symbol)
        if not position or position.get('size', 0) == 0:
            return 0.0
        
        return self.position_controller._calculate_unrealized_pnl(position)
    
    def get_position_summary(self) -> Dict[str, Any]:
        """获取持仓汇总"""
        return self.position_controller.get_position_summary()


if __name__ == "__main__":
    # 测试持仓管理器
    manager = PositionManager()
    
    # 模拟订单
    from ..trading.order_manager import Order, OrderStatus
    
    order = Order(
        order_id="test_001",
        symbol="BTC-USDT",
        side="buy",
        order_type="market",
        size=0.1,
        status=OrderStatus.FILLED,
        filled_size=0.1,
        filled_price=50000,
        average_price=50000,
        executed_at=datetime.now()
    )
    
    manager.update_position_from_order(order)
    position = manager.get_position("BTC-USDT")
    print(f"持仓: {position}")

