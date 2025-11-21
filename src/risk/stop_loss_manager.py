#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
止损管理器
止损规则管理，止损订单执行，移动止损，止损历史记录
"""

from typing import Dict, List, Optional, Any
from datetime import datetime
from ..core.config_manager import get_config_manager
from ..core.logger import get_logger
from ..trading.order_manager import OrderManager
from ..core.exception import RiskException
from .stop_loss_utils import get_symbol_price_stop_pct


class StopLossManager:
    """止损管理器"""
    
    def __init__(self):
        """初始化止损管理器"""
        self.config_mgr = get_config_manager()
        self.logger = get_logger("stop_loss_manager")
        self.order_manager = OrderManager()
        
        # 获取配置
        self.stop_loss_config = self.config_mgr.get_config('risk', 'stop_loss')
        self.default_stop_loss_pct = self.stop_loss_config.get('default_stop_loss_pct', 0.002)
        self.max_stop_loss_pct = self.stop_loss_config.get('max_stop_loss_pct', 0.01)
        
        # 止损订单
        self.stop_loss_orders: Dict[str, Dict] = {}  # key: position_id, value: stop_loss_info
    
    def set_stop_loss(self, symbol: str, position_id: str, entry_price: float,
                      side: str, stop_loss_price: Optional[float] = None) -> Dict[str, Any]:
        """
        设置止损
        
        Args:
            symbol: 交易对符号
            position_id: 持仓ID
            entry_price: 入场价格
            side: 方向（buy, sell）
            stop_loss_price: 止损价格，如果为None则自动计算
            
        Returns:
            止损信息
        """
        try:
            # 计算止损价格
            price_stop_pct = get_symbol_price_stop_pct(symbol, self.config_mgr)
            if price_stop_pct <= 0:
                price_stop_pct = self.default_stop_loss_pct

            if stop_loss_price is None:
                if side == 'buy':
                    stop_loss_price = entry_price * (1 - price_stop_pct)
                else:  # sell
                    stop_loss_price = entry_price * (1 + price_stop_pct)
            
            stop_loss_info = {
                'symbol': symbol,
                'position_id': position_id,
                'entry_price': entry_price,
                'stop_loss_price': stop_loss_price,
                'side': side,
                'stop_loss_pct': abs(stop_loss_price - entry_price) / entry_price,
                'created_at': datetime.now(),
                'triggered': False
            }
            
            # 检查止损距离是否合理
            if stop_loss_info['stop_loss_pct'] > self.max_stop_loss_pct:
                self.logger.warning(
                    f"止损距离{stop_loss_info['stop_loss_pct']:.2%}超过最大限制{self.max_stop_loss_pct:.2%}"
                )
            
            # 存储止损信息
            self.stop_loss_orders[position_id] = stop_loss_info
            
            self.logger.info(
                f"设置止损: {symbol} {position_id}, "
                f"入场={entry_price}, 止损={stop_loss_price}, "
                f"距离={stop_loss_info['stop_loss_pct']:.2%}"
            )
            
            return stop_loss_info
        
        except Exception as e:
            self.logger.error(f"设置止损失败: {e}")
            raise RiskException(f"设置止损失败: {e}")
    
    def update_trailing_stop(self, position_id: str, current_price: float):
        """
        更新移动止损
        
        Args:
            position_id: 持仓ID
            current_price: 当前价格
        """
        if position_id not in self.stop_loss_orders:
            return
        
        try:
            stop_loss_info = self.stop_loss_orders[position_id]
            
            # 检查是否激活移动止损
            trailing_config = self.stop_loss_config.get('trailing_stop', {})
            if not trailing_config.get('enabled', True):
                return
            
            activation_profit = trailing_config.get('activation_profit', 0.10)
            trailing_pct = trailing_config.get('trailing_pct', 0.03)
            
            entry_price = stop_loss_info['entry_price']
            side = stop_loss_info['side']
            
            # 计算当前盈亏
            if side == 'buy':
                profit_pct = (current_price - entry_price) / entry_price
                if profit_pct >= activation_profit:
                    # 激活移动止损
                    new_stop_loss = current_price * (1 - trailing_pct)
                    if new_stop_loss > stop_loss_info['stop_loss_price']:
                        stop_loss_info['stop_loss_price'] = new_stop_loss
                        stop_loss_info['updated_at'] = datetime.now()
                        self.logger.info(
                            f"更新移动止损: {position_id}, 新止损={new_stop_loss}"
                        )
            
            elif side == 'sell':
                profit_pct = (entry_price - current_price) / entry_price
                if profit_pct >= activation_profit:
                    # 激活移动止损
                    new_stop_loss = current_price * (1 + trailing_pct)
                    if new_stop_loss < stop_loss_info['stop_loss_price']:
                        stop_loss_info['stop_loss_price'] = new_stop_loss
                        stop_loss_info['updated_at'] = datetime.now()
                        self.logger.info(
                            f"更新移动止损: {position_id}, 新止损={new_stop_loss}"
                        )
        
        except Exception as e:
            self.logger.error(f"更新移动止损失败 {position_id}: {e}")
    
    def check_stop_loss(self, position_id: str, current_price: float) -> bool:
        """
        检查是否触发止损
        
        Args:
            position_id: 持仓ID
            current_price: 当前价格
            
        Returns:
            是否触发止损
        """
        if position_id not in self.stop_loss_orders:
            return False
        
        try:
            stop_loss_info = self.stop_loss_orders[position_id]
            
            if stop_loss_info.get('triggered', False):
                return False
            
            side = stop_loss_info['side']
            stop_loss_price = stop_loss_info['stop_loss_price']
            
            # 检查是否触发
            triggered = False
            if side == 'buy':
                triggered = current_price <= stop_loss_price
            else:  # sell
                triggered = current_price >= stop_loss_price
            
            if triggered:
                stop_loss_info['triggered'] = True
                stop_loss_info['triggered_at'] = datetime.now()
                stop_loss_info['trigger_price'] = current_price
                
                self.logger.warning(
                    f"止损触发: {position_id}, "
                    f"止损价={stop_loss_price}, 触发价={current_price}"
                )
                
                return True
        
        except Exception as e:
            self.logger.error(f"检查止损失败 {position_id}: {e}")
        
        return False
    
    def remove_stop_loss(self, position_id: str):
        """移除止损"""
        if position_id in self.stop_loss_orders:
            del self.stop_loss_orders[position_id]
            self.logger.info(f"移除止损: {position_id}")
    
    def get_stop_loss(self, position_id: str) -> Optional[Dict[str, Any]]:
        """获取止损信息"""
        return self.stop_loss_orders.get(position_id)


if __name__ == "__main__":
    # 测试止损管理器
    manager = StopLossManager()
    
    # 设置止损
    stop_loss = manager.set_stop_loss(
        "BTC-USDT",
        "pos_001",
        50000,
        "buy"
    )
    print(f"止损设置: {stop_loss}")
    
    # 检查止损
    triggered = manager.check_stop_loss("pos_001", 47000)
    print(f"止损触发: {triggered}")

