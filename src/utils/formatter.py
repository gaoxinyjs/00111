#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
格式化工具
数据格式化、显示格式化等
"""

from typing import Any, Optional
from decimal import Decimal, ROUND_HALF_UP


def format_price(price: float, precision: int = 2) -> str:
    """
    格式化价格
    
    Args:
        price: 价格
        precision: 小数位数
        
    Returns:
        格式化后的字符串
    """
    return f"{price:,.{precision}f}"


def format_percentage(value: float, precision: int = 2, show_sign: bool = True) -> str:
    """
    格式化百分比
    
    Args:
        value: 百分比值（如 0.15 表示 15%）
        precision: 小数位数
        show_sign: 是否显示符号
        
    Returns:
        格式化后的字符串
    """
    formatted = f"{value * 100:.{precision}f}%"
    
    if show_sign and value > 0:
        formatted = f"+{formatted}"
    
    return formatted


def format_currency(amount: float, currency: str = "USDT", precision: int = 2) -> str:
    """
    格式化货币金额
    
    Args:
        amount: 金额
        currency: 货币符号
        precision: 小数位数
        
    Returns:
        格式化后的字符串
    """
    return f"{currency} {format_price(amount, precision)}"


def format_quantity(quantity: float, symbol: str = "", precision: int = 8) -> str:
    """
    格式化数量
    
    Args:
        quantity: 数量
        symbol: 币种符号
        precision: 小数位数
        
    Returns:
        格式化后的字符串
    """
    formatted = f"{quantity:.{precision}f}".rstrip('0').rstrip('.')
    
    if symbol:
        return f"{formatted} {symbol}"
    
    return formatted


def format_number_scientific(value: float, precision: int = 2) -> str:
    """
    格式化科学计数法
    
    Args:
        value: 数值
        precision: 小数位数
        
    Returns:
        格式化后的字符串
    """
    if abs(value) >= 1e6:
        return f"{value / 1e6:.{precision}f}M"
    elif abs(value) >= 1e3:
        return f"{value / 1e3:.{precision}f}K"
    else:
        return f"{value:.{precision}f}"


def format_duration_short(seconds: float) -> str:
    """
    格式化时长（简短格式）
    
    Args:
        seconds: 秒数
        
    Returns:
        格式化后的字符串（如 "1h30m"）
    """
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    
    parts = []
    if hours > 0:
        parts.append(f"{hours}h")
    if minutes > 0:
        parts.append(f"{minutes}m")
    if secs > 0 or not parts:
        parts.append(f"{secs}s")
    
    return "".join(parts)


def format_dict_pretty(data: dict, indent: int = 2) -> str:
    """
    美化字典输出
    
    Args:
        data: 字典数据
        indent: 缩进空格数
        
    Returns:
        格式化后的字符串
    """
    lines = []
    
    def format_value(value: Any, current_indent: int):
        if isinstance(value, dict):
            lines.append(" " * current_indent + "{")
            for k, v in value.items():
                lines.append(" " * (current_indent + indent) + f"{k}: ", end="")
                format_value(v, current_indent + indent)
            lines.append(" " * current_indent + "}")
        elif isinstance(value, list):
            lines.append(" " * current_indent + "[")
            for item in value:
                format_value(item, current_indent + indent)
            lines.append(" " * current_indent + "]")
        else:
            lines[-1] += str(value)
    
    format_value(data, 0)
    return "\n".join(lines)


def format_table_row(values: list, widths: list, align: str = "left") -> str:
    """
    格式化表格行
    
    Args:
        values: 值列表
        widths: 宽度列表
        align: 对齐方式（left, right, center）
        
    Returns:
        格式化后的字符串
    """
    cells = []
    for i, value in enumerate(values):
        width = widths[i] if i < len(widths) else 10
        value_str = str(value)
        
        if align == "right":
            cell = value_str.rjust(width)
        elif align == "center":
            cell = value_str.center(width)
        else:
            cell = value_str.ljust(width)
        
        cells.append(cell)
    
    return " | ".join(cells)


def truncate_string(text: str, max_length: int, suffix: str = "...") -> str:
    """
    截断字符串
    
    Args:
        text: 原字符串
        max_length: 最大长度
        suffix: 后缀
        
    Returns:
        截断后的字符串
    """
    if len(text) <= max_length:
        return text
    
    return text[:max_length - len(suffix)] + suffix


def mask_sensitive_data(data: str, visible_chars: int = 4) -> str:
    """
    遮挡敏感数据
    
    Args:
        data: 原始数据
        visible_chars: 保留可见字符数
        
    Returns:
        遮挡后的字符串
    """
    if not data or len(data) <= visible_chars:
        return "*" * len(data) if data else ""
    
    visible = data[:visible_chars]
    masked = "*" * (len(data) - visible_chars)
    return visible + masked


if __name__ == "__main__":
    # 测试格式化工具
    print(f"格式化价格: {format_price(12345.678, 2)}")
    print(f"格式化百分比: {format_percentage(0.155, 2)}")
    print(f"格式化货币: {format_currency(1234.56)}")
    print(f"格式化数量: {format_quantity(0.123456789, 'BTC')}")
    print(f"科学计数法: {format_number_scientific(1234567.89)}")
    print(f"时长: {format_duration_short(3665)}")
    print(f"遮挡数据: {mask_sensitive_data('abc123456789', 4)}")

