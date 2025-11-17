#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
策略计划执行器：根据策略模板调整交易决策
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Dict, Any

from ..core.logger import get_logger
from .strategy_router import StrategyPlan
from ..core.exception import StrategyException


@dataclass
class StrategyAdjustment:
    position_size: float
    stop_loss: Optional[float]
    take_profit: Optional[float]
    notes: Optional[str] = None


class StrategyExecutor:
    """根据策略计划对决策进行调整"""

    def __init__(self):
        self.logger = get_logger("strategy_executor")

    def apply(self, plan: Optional[StrategyPlan], decision, market_data: Dict[str, Any]):
        if not plan or not decision:
            return decision

        if self._should_suspend(plan):
            self.logger.info(
                f"[策略执行] {decision.symbol}: 策略 {plan.name} 要求暂停新单，保持观望"
            )
            return None

        indicators = (market_data or {}).get('indicators', {}) or {}
        price = decision.price or market_data.get('price') or 0
        atr_value = self._float(indicators.get('atr'), default=None)
        if atr_value is None and price:
            atr_pct = self._float(indicators.get('atr_pct'), default=None)
            if atr_pct:
                atr_value = price * atr_pct / 100.0

        # 仓位限制
        max_pct = plan.risk.get('max_position_pct')
        if max_pct is not None and decision.position_size > max_pct:
            self.logger.info(
                f"[策略执行] {decision.symbol}: 仓位由 {decision.position_size:.2%} 限制为 {max_pct:.2%}"
            )
            decision.position_size = max_pct

        # 止损调整
        stop_mode = plan.risk.get('stop_loss')
        decision.stop_loss = self._apply_stop_loss(stop_mode, decision, price, atr_value)

        # 止盈调整
        take_mode = plan.risk.get('take_profit')
        decision.take_profit = self._apply_take_profit(take_mode, decision, price, atr_value)

        # 分层入场（层不为空，并且当前决策是开仓时才处理）
        if plan.entries and decision.action in ['long', 'short']:
            adjusted_size = 0.0
            final_entries = []
            for layer in plan.entries:
                if layer.get('type') != 'layer':
                    continue
                ratio = self._float(layer.get('size_ratio'), default=0.0)
                if ratio <= 0:
                    continue
                offset = float(layer.get('price_offset', 0))
                entry_price = price * (1 + offset) if price else None
                entry = {
                    'order_type': layer.get('order_type', 'market'),
                    'size_ratio': ratio,
                    'price': entry_price
                }
                final_entries.append(entry)
                adjusted_size += ratio
            if final_entries and adjusted_size > 0:
                decision._layered_entries = final_entries
                decision.position_size = min(decision.position_size, adjusted_size)

        # 事件场景仅允许减仓
        if plan.scene_type == 'event' and decision.action in ['long', 'short']:
            raise StrategyException("事件场景禁止开仓")

        decision.reasoning = f"{decision.reasoning} | 策略:{plan.name}"
        return decision

    def _apply_stop_loss(self, mode: Optional[str], decision, price, atr_value):
        if mode is None or decision.action in ['close_long', 'close_short']:
            return decision.stop_loss

        try:
            if mode == 'trail_atr' and atr_value and price:
                factor = 1.2
                if decision.position_side == 'long':
                    return price - atr_value * factor
                else:
                    return price + atr_value * factor
            elif mode == 'tight_percent' and price:
                pct = 0.005
                delta = price * pct
                if decision.position_side == 'long':
                    return price - delta
                else:
                    return price + delta
            elif mode == 'reduce_only':
                # 保持原止损，但在执行层会以reduceOnly处理
                return decision.stop_loss
        except Exception as err:
            self.logger.debug(f"[策略执行] 止损调整失败: {err}")
        return decision.stop_loss

    def _apply_take_profit(self, mode: Optional[str], decision, price, atr_value):
        if mode is None or decision.action in ['close_long', 'close_short']:
            return decision.take_profit

        try:
            if mode == 'partial_scale_out' and atr_value and price:
                factor = 2.0
                if decision.position_side == 'long':
                    return price + atr_value * factor
                else:
                    return price - atr_value * factor
            elif mode == 'fixed_rr' and decision.stop_loss and price:
                rr = 1.5
                if decision.position_side == 'long':
                    risk = price - decision.stop_loss
                    return price + max(risk * rr, price * 0.002)
                else:
                    risk = decision.stop_loss - price
                    return price - max(risk * rr, price * 0.002)
        except Exception as err:
            self.logger.debug(f"[策略执行] 止盈调整失败: {err}")
        return decision.take_profit

    @staticmethod
    def _should_suspend(plan: StrategyPlan) -> bool:
        if not plan.entries:
            return False
        return any(entry.get('type') == 'suspend_new_orders' for entry in plan.entries)

    @staticmethod
    def _float(value, default=None):
        try:
            if value is None:
                return default
            return float(value)
        except (TypeError, ValueError):
            return default
