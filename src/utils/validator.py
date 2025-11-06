#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
验证工具
数据验证、格式验证等
"""

from typing import Any, Optional
import re


def validate_email(email: str) -> bool:
    """
    验证邮箱格式
    
    Args:
        email: 邮箱地址
        
    Returns:
        是否有效
    """
    pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
    return bool(re.match(pattern, email))


def validate_symbol(symbol: str) -> bool:
    """
    验证交易对符号格式
    
    Args:
        symbol: 交易对符号（如 "BTC-USDT"）
        
    Returns:
        是否有效
    """
    pattern = r'^[A-Z0-9]+-[A-Z0-9]+$'
    return bool(re.match(pattern, symbol))


def validate_price(price: float, min_price: Optional[float] = None,
                   max_price: Optional[float] = None) -> bool:
    """
    验证价格
    
    Args:
        price: 价格
        min_price: 最小价格
        max_price: 最大价格
        
    Returns:
        是否有效
    """
    if price <= 0:
        return False
    
    if min_price is not None and price < min_price:
        return False
    
    if max_price is not None and price > max_price:
        return False
    
    return True


def validate_quantity(quantity: float, min_quantity: Optional[float] = None,
                      max_quantity: Optional[float] = None) -> bool:
    """
    验证数量
    
    Args:
        quantity: 数量
        min_quantity: 最小数量
        max_quantity: 最大数量
        
    Returns:
        是否有效
    """
    if quantity <= 0:
        return False
    
    if min_quantity is not None and quantity < min_quantity:
        return False
    
    if max_quantity is not None and quantity > max_quantity:
        return False
    
    return True


def validate_percentage(value: float, min_val: float = 0.0,
                       max_val: float = 100.0) -> bool:
    """
    验证百分比值
    
    Args:
        value: 百分比值（0-100）
        min_val: 最小值
        max_val: 最大值
        
    Returns:
        是否有效
    """
    return min_val <= value <= max_val


def validate_order_side(side: str) -> bool:
    """
    验证订单方向
    
    Args:
        side: 方向（buy 或 sell）
        
    Returns:
        是否有效
    """
    return side.lower() in ['buy', 'sell']


def validate_order_type(order_type: str) -> bool:
    """
    验证订单类型
    
    Args:
        order_type: 订单类型（market 或 limit）
        
    Returns:
        是否有效
    """
    return order_type.lower() in ['market', 'limit']


def validate_config(config: dict, required_keys: list) -> bool:
    """
    验证配置是否包含必需键
    
    Args:
        config: 配置字典
        required_keys: 必需键列表
        
    Returns:
        是否有效
    """
    return all(key in config for key in required_keys)


def sanitize_input(text: str, max_length: Optional[int] = None) -> str:
    """
    清理输入文本
    
    Args:
        text: 输入文本
        max_length: 最大长度
        
    Returns:
        清理后的文本
    """
    # 移除前后空格
    text = text.strip()
    
    # 限制长度
    if max_length is not None and len(text) > max_length:
        text = text[:max_length]
    
    return text


if __name__ == "__main__":
    # 测试验证工具
    print(f"邮箱验证: {validate_email('test@example.com')}")
    print(f"交易对验证: {validate_symbol('BTC-USDT')}")
    print(f"价格验证: {validate_price(50000, min_price=0, max_price=100000)}")
    print(f"订单方向验证: {validate_order_side('buy')}")
    print(f"订单类型验证: {validate_order_type('market')}")

