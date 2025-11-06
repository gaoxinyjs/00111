#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
仓位控制器
仓位限制检查，仓位动态调整，仓位优化，仓位报告
"""

from typing import Dict, List, Optional, Any
from ..core.config_manager import get_config_manager
from ..core.logger import get_logger


class PositionController:
    """仓位控制器"""
    
    def __init__(self):
        """初始化仓位控制器"""
        self.config_mgr = get_config_manager()
        self.logger = get_logger("position_controller")
        
        # 获取配置
        self.position_config = self.config_mgr.get_config('risk', 'position_management')
        self.max_position_size = self.position_config.get('max_position_size', 0.30)
        self.max_total_position = self.position_config.get('max_total_position', 0.80)
        
        # 当前持仓
        self.current_positions: Dict[str, Dict] = {}
    
    def check_position_limit(self, symbol: str, new_position_size: float) -> bool:
        """
        检查仓位限制
        
        Args:
            symbol: 交易对符号
            new_position_size: 新仓位大小
            
        Returns:
            是否通过限制检查
        """
        try:
            # 1. 检查单币种仓位限制
            if new_position_size > self.max_position_size:
                self.logger.warning(
                    f"{symbol}: [仓位检查] 单币种仓位{new_position_size:.2%}超过限制{self.max_position_size:.2%}"
                )
                return False
            
            # 2. 检查总仓位限制
            total_position = sum(p.get('size', 0) for p in self.current_positions.values())
            total_position += new_position_size
            
            if total_position > self.max_total_position:
                self.logger.warning(
                    f"{symbol}: [仓位检查] 总仓位{total_position:.2%}超过限制{self.max_total_position:.2%}，"
                    f"当前持仓={sum(p.get('size', 0) for p in self.current_positions.values()):.2%}, "
                    f"新增仓位={new_position_size:.2%}"
                )
                return False
            
            self.logger.debug(
                f"{symbol}: [仓位检查] 通过，仓位={new_position_size:.2%}, "
                f"单币种限制={self.max_position_size:.2%}, 总仓位={total_position:.2%}, 总限制={self.max_total_position:.2%}"
            )
            return True
        
        except Exception as e:
            self.logger.error(f"仓位限制检查失败: {e}")
            return False
    
    def update_position(self, symbol: str, side: str, size: float, price: float):
        """
        更新持仓
        
        Args:
            symbol: 交易对符号
            side: 方向（buy, sell）
            size: 数量
            price: 价格
        """
        from datetime import datetime
        if symbol not in self.current_positions:
            self.current_positions[symbol] = {
                'side': 'none',
                'size': 0.0,
                'average_price': 0.0,
                'avg_price': 0.0,  # 别名，用于兼容
                'current_price': price,
                'unrealized_pnl': 0.0,
                'entry_time': datetime.now().isoformat()  # 开仓时间
            }
        
        position = self.current_positions[symbol]
        
        if side == 'buy':
            if position['side'] == 'sell':
                # 平空仓
                position['size'] = 0.0
                position['side'] = 'none'
            elif position['side'] == 'buy' or position['side'] == 'none':
                # 加多仓
                old_size = position['size']
                old_price = position['average_price']
                
                new_size = old_size + size
                new_avg_price = ((old_size * old_price) + (size * price)) / new_size if new_size > 0 else price
                
                position['size'] = new_size
                position['average_price'] = new_avg_price
                position['avg_price'] = new_avg_price  # 别名
                position['side'] = 'buy'
                # 如果是从无持仓到有持仓，记录开仓时间
                if old_size == 0:
                    position['entry_time'] = datetime.now().isoformat()
        
        elif side == 'sell':
            if position['side'] == 'buy':
                # 平多仓
                position['size'] = 0.0
                position['side'] = 'none'
            elif position['side'] == 'sell' or position['side'] == 'none':
                # 加空仓
                old_size = position['size']
                old_price = position['average_price']
                
                new_size = old_size + size
                new_avg_price = ((old_size * old_price) + (size * price)) / new_size if new_size > 0 else price
                
                position['size'] = new_size
                position['average_price'] = new_avg_price
                position['avg_price'] = new_avg_price  # 别名
                position['side'] = 'sell'
                # 如果是从无持仓到有持仓，记录开仓时间
                if old_size == 0:
                    position['entry_time'] = datetime.now().isoformat()
        
        position['current_price'] = price
        position['unrealized_pnl'] = self._calculate_unrealized_pnl(position)
    
    def _calculate_unrealized_pnl(self, position: Dict[str, Any]) -> float:
        """计算未实现盈亏"""
        size = position.get('size', 0)
        avg_price = position.get('average_price', 0)
        current_price = position.get('current_price', 0)
        side = position.get('side', 'none')
        
        if size == 0 or avg_price == 0 or current_price == 0:
            return 0.0
        
        if side == 'buy':
            return (current_price - avg_price) * size
        elif side == 'sell':
            return (avg_price - current_price) * size
        else:
            return 0.0
    
    def get_position(self, symbol: str) -> Optional[Dict[str, Any]]:
        """获取持仓"""
        return self.current_positions.get(symbol)
    
    def get_all_positions(self) -> Dict[str, Dict[str, Any]]:
        """获取所有持仓"""
        return self.current_positions.copy()
    
    def get_position_summary(self) -> Dict[str, Any]:
        """获取持仓汇总"""
        total_size = sum(p.get('size', 0) for p in self.current_positions.values())
        total_pnl = sum(p.get('unrealized_pnl', 0) for p in self.current_positions.values())
        
        return {
            'total_positions': len(self.current_positions),
            'total_size': total_size,
            'total_unrealized_pnl': total_pnl,
            'positions': list(self.current_positions.values())
        }


if __name__ == "__main__":
    # 测试仓位控制器
    controller = PositionController()
    
    # 测试仓位限制
    passed = controller.check_position_limit("BTC-USDT", 0.25)
    print(f"仓位限制检查: {'通过' if passed else '未通过'}")
    
    # 测试更新持仓
    controller.update_position("BTC-USDT", "buy", 0.1, 50000)
    position = controller.get_position("BTC-USDT")
    print(f"持仓: {position}")

