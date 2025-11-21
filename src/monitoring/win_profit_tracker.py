#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
胜率与盈利统计模块
从交易结果记录中提取最近 N 笔交易，计算胜率、收益等核心指标
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Any

from ..core.logger import get_logger
from ..learning.trade_result_recorder import TradeResultRecorder


@dataclass
class WinProfitSummary:
    """胜率与盈利统计结果"""
    sample_size: int
    winning_trades: int
    losing_trades: int
    breakeven_trades: int
    win_rate: float
    total_profit_pct: float
    avg_profit_pct: float
    avg_profit_win_pct: float
    avg_loss_pct: float
    group_by_symbol: Optional[Dict[str, Any]] = None
    recent_trades: Optional[List[Dict[str, Any]]] = None


class WinProfitTracker:
    """
    胜率与盈利追踪器
    依赖 TradeResultRecorder 的历史记录进行统计
    """

    def __init__(self, recorder: Optional[TradeResultRecorder] = None, lookback: int = 100):
        self.logger = get_logger("win_profit_tracker")
        self.recorder = recorder or TradeResultRecorder()
        self.lookback = max(1, lookback)

    def compute_summary(self, limit: Optional[int] = None, group_by_symbol: bool = False) -> WinProfitSummary:
        """计算最近 N 笔交易的胜率与盈利"""
        limit = limit or self.lookback
        records = self.recorder.get_recent_results(limit=limit)

        if not records:
            return WinProfitSummary(
                sample_size=0,
                winning_trades=0,
                losing_trades=0,
                breakeven_trades=0,
                win_rate=0.0,
                total_profit_pct=0.0,
                avg_profit_pct=0.0,
                avg_profit_win_pct=0.0,
                avg_loss_pct=0.0,
                group_by_symbol={} if group_by_symbol else None,
                recent_trades=[]
            )

        profits = []
        for record in records:
            result = record.get('result', {}) or {}
            profit_pct = result.get('profit_pct', 0.0)
            try:
                profits.append(float(profit_pct))
            except (TypeError, ValueError):
                profits.append(0.0)

        winning_trades = len([p for p in profits if p > 0])
        losing_trades = len([p for p in profits if p < 0])
        breakeven_trades = len([p for p in profits if p == 0])

        total_profit_pct = sum(profits)
        total = len(records)
        win_rate = winning_trades / total if total > 0 else 0.0
        avg_profit_pct = total_profit_pct / total if total > 0 else 0.0

        avg_profit_win_pct = (
            sum(p for p in profits if p > 0) / winning_trades if winning_trades > 0 else 0.0
        )
        avg_loss_pct = (
            sum(p for p in profits if p < 0) / losing_trades if losing_trades > 0 else 0.0
        )

        symbol_stats: Optional[Dict[str, Any]] = None
        if group_by_symbol:
            symbol_stats = {}
            for record, profit in zip(records, profits):
                symbol = record.get('symbol', 'UNKNOWN')
                stats = symbol_stats.setdefault(symbol, {
                    'total_trades': 0,
                    'winning_trades': 0,
                    'losing_trades': 0,
                    'breakeven_trades': 0,
                    'total_profit_pct': 0.0,
                })
                stats['total_trades'] += 1
                stats['total_profit_pct'] += profit
                if profit > 0:
                    stats['winning_trades'] += 1
                elif profit < 0:
                    stats['losing_trades'] += 1
                else:
                    stats['breakeven_trades'] += 1
            # 计算每个 symbol 的胜率
            for stats in symbol_stats.values():
                total_sym = stats['total_trades']
                stats['win_rate'] = (
                    stats['winning_trades'] / total_sym if total_sym > 0 else 0.0
                )

        summary = WinProfitSummary(
            sample_size=total,
            winning_trades=winning_trades,
            losing_trades=losing_trades,
            breakeven_trades=breakeven_trades,
            win_rate=win_rate,
            total_profit_pct=total_profit_pct,
            avg_profit_pct=avg_profit_pct,
            avg_profit_win_pct=avg_profit_win_pct,
            avg_loss_pct=avg_loss_pct,
            group_by_symbol=symbol_stats,
            recent_trades=records[:5]
        )
        return summary

    def log_summary(self, summary: WinProfitSummary, tag: str = "", level: str = "info"):
        """将统计结果写入日志"""
        logger_method = getattr(self.logger, level, self.logger.info)
        if summary.sample_size == 0:
            logger_method("暂无已平仓交易，无法计算胜率")
            return

        tag_str = f"[{tag}] " if tag else ""
        logger_method(
            f"{tag_str}最近{summary.sample_size}笔交易 | 胜率={summary.win_rate:.2%} | "
            f"总收益={summary.total_profit_pct:.2f}% | 平均收益={summary.avg_profit_pct:.2f}% | "
            f"平均盈利={summary.avg_profit_win_pct:.2f}% | 平均亏损={summary.avg_loss_pct:.2f}%"
        )

    def emit_summary(self, limit: Optional[int] = None, group_by_symbol: bool = False, tag: str = "") -> WinProfitSummary:
        """计算并立即输出统计"""
        summary = self.compute_summary(limit=limit, group_by_symbol=group_by_symbol)
        self.log_summary(summary, tag=tag)
        return summary
