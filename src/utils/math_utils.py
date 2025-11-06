#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
数学工具
常用数学计算函数
"""

import math
from typing import List, Optional
import numpy as np


def round_to_precision(value: float, precision: int) -> float:
    """
    四舍五入到指定精度
    
    Args:
        value: 数值
        precision: 小数位数
        
    Returns:
        四舍五入后的值
    """
    return round(value, precision)


def calculate_percentage_change(old_value: float, new_value: float) -> float:
    """
    计算百分比变化
    
    Args:
        old_value: 旧值
        new_value: 新值
        
    Returns:
        百分比变化（如 5.5 表示 5.5%）
    """
    if old_value == 0:
        return 0.0
    
    return ((new_value - old_value) / old_value) * 100


def calculate_compound_annual_growth_rate(
    start_value: float,
    end_value: float,
    periods: int
) -> float:
    """
    计算复合年化增长率（CAGR）
    
    Args:
        start_value: 起始值
        end_value: 结束值
        periods: 期数（年）
        
    Returns:
        CAGR（比例，如 0.15 表示 15%）
    """
    if start_value <= 0 or periods <= 0:
        return 0.0
    
    return (end_value / start_value) ** (1 / periods) - 1


def calculate_sharpe_ratio(returns: List[float], risk_free_rate: float = 0.02) -> Optional[float]:
    """
    计算夏普比率
    
    Args:
        returns: 收益率列表
        risk_free_rate: 无风险利率（年化，默认2%）
        
    Returns:
        夏普比率
    """
    if not returns or len(returns) < 2:
        return None
    
    returns_array = np.array(returns)
    mean_return = np.mean(returns_array)
    std_return = np.std(returns_array)
    
    if std_return == 0:
        return None
    
    # 年化夏普比率（假设252个交易日）
    sharpe_ratio = (mean_return - risk_free_rate / 252) / std_return * math.sqrt(252)
    
    return float(sharpe_ratio)


def calculate_max_drawdown(equity_curve: List[float]) -> float:
    """
    计算最大回撤
    
    Args:
        equity_curve: 资金曲线列表
        
    Returns:
        最大回撤（比例，如 0.15 表示 15%）
    """
    if not equity_curve or len(equity_curve) < 2:
        return 0.0
    
    peak = equity_curve[0]
    max_drawdown = 0.0
    
    for value in equity_curve:
        if value > peak:
            peak = value
        
        drawdown = (peak - value) / peak if peak > 0 else 0
        if drawdown > max_drawdown:
            max_drawdown = drawdown
    
    return max_drawdown


def calculate_win_rate(profits: List[float]) -> float:
    """
    计算胜率
    
    Args:
        profits: 收益列表
        
    Returns:
        胜率（比例，如 0.6 表示 60%）
    """
    if not profits:
        return 0.0
    
    winning_trades = sum(1 for p in profits if p > 0)
    return winning_trades / len(profits)


def calculate_profit_factor(profits: List[float]) -> Optional[float]:
    """
    计算盈亏比
    
    Args:
        profits: 收益列表
        
    Returns:
        盈亏比（如 2.0 表示平均盈利是平均亏损的2倍）
    """
    if not profits:
        return None
    
    total_profit = sum(p for p in profits if p > 0)
    total_loss = sum(abs(p) for p in profits if p < 0)
    
    if total_loss == 0:
        return None
    
    return total_profit / total_loss


def calculate_average_win_loss(profits: List[float]) -> tuple:
    """
    计算平均盈利和平均亏损
    
    Args:
        profits: 收益列表
        
    Returns:
        (平均盈利, 平均亏损)
    """
    wins = [p for p in profits if p > 0]
    losses = [abs(p) for p in profits if p < 0]
    
    avg_win = sum(wins) / len(wins) if wins else 0.0
    avg_loss = sum(losses) / len(losses) if losses else 0.0
    
    return (avg_win, avg_loss)


def normalize_value(value: float, min_val: float, max_val: float) -> float:
    """
    归一化数值到[0, 1]范围
    
    Args:
        value: 原始值
        min_val: 最小值
        max_val: 最大值
        
    Returns:
        归一化后的值（0-1之间）
    """
    if max_val == min_val:
        return 0.0
    
    return (value - min_val) / (max_val - min_val)


def clamp(value: float, min_val: float, max_val: float) -> float:
    """
    限制数值在指定范围内
    
    Args:
        value: 原始值
        min_val: 最小值
        max_val: 最大值
        
    Returns:
        限制后的值
    """
    return max(min_val, min(max_val, value))


if __name__ == "__main__":
    # 测试数学工具
    profits = [100, -50, 200, -30, 150, -40, 80]
    
    print(f"胜率: {calculate_win_rate(profits):.2%}")
    print(f"盈亏比: {calculate_profit_factor(profits):.2f}")
    
    avg_win, avg_loss = calculate_average_win_loss(profits)
    print(f"平均盈利: {avg_win:.2f}, 平均亏损: {avg_loss:.2f}")
    
    equity_curve = [10000, 10500, 9800, 10200, 11000, 10800, 11200]
    max_dd = calculate_max_drawdown(equity_curve)
    print(f"最大回撤: {max_dd:.2%}")

