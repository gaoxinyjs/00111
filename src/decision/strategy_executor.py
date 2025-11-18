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

    def apply(self, plan: Optional[StrategyPlan], decision, market_data: Dict[str, Any],
              current_position: Optional[Dict[str, Any]] = None):
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

        manage_cfg = plan.risk.get('manage_existing')
        if manage_cfg and current_position and current_position.get('size', 0) > 0:
            self._apply_manage_existing(manage_cfg, decision, current_position)

        # 事件场景：记录熔断信息，并在执行层触发
        breaker_cfg = plan.risk.get('circuit_breaker', {}) or {}
        if plan.scene_type == 'event' and breaker_cfg.get('enabled', True):
            decision._circuit_breaker = {
                'reason': breaker_cfg.get('reason') or f"{plan.name} 触发事件熔断",
                'cooldown': int(breaker_cfg.get('cooldown_seconds', 900))
            }

        self._attach_hedge_decision(plan, decision, market_data, current_position)

        if plan.scene_type == 'event' and decision.action in ['long', 'short']:
            self.logger.info(f"[策略执行] {decision.symbol}: 事件场景禁止新开仓，忽略该决策")
            return None

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

    def _apply_manage_existing(self, cfg: Dict[str, Any], decision, current_position: Dict[str, Any]):
        mode = cfg.get('mode')
        ratio = self._float(cfg.get('ratio'), default=0.5)
        ratio = max(0.05, min(1.0, ratio))
        current_side = self._normalize_side(current_position.get('side'))
        if current_side == 'flat':
            return
        if mode == 'reduce':
            decision.action = 'close_long' if current_side == 'long' else 'close_short'
            decision.position_side = current_side
            decision.position_size = ratio
            decision.reasoning = f"{decision.reasoning} | 减仓{ratio:.2f}"
        elif mode == 'add':
            decision.action = 'long' if current_side == 'long' else 'short'
            decision.position_side = current_side
            decision.position_size = min(decision.position_size, ratio)
            decision.reasoning = f"{decision.reasoning} | 加仓{decision.position_size:.2f}"

    @staticmethod
    def _normalize_side(side: Optional[str]) -> str:
        if not side:
            return 'flat'
        side = str(side).lower()
        if side == 'buy':
            return 'long'
        if side == 'sell':
            return 'short'
        if side in ['long', 'short']:
            return side
        return 'flat'

    def _attach_hedge_decision(self, plan: StrategyPlan, decision, market_data: Dict[str, Any],
                               current_position: Optional[Dict[str, Any]]):
        hedge_decision = self._maybe_create_hedge_decision(plan, decision, market_data, current_position)
        if not hedge_decision:
            return
        chained = getattr(decision, '_chained_decisions', [])
        chained.append(hedge_decision)
        decision._chained_decisions = chained
        self.logger.info(
            f"[策略执行] {decision.symbol}: 触发{plan.name}对冲，附加{hedge_decision.action} {hedge_decision.symbol}"
        )

    def _maybe_create_hedge_decision(self, plan: StrategyPlan, decision, market_data: Dict[str, Any],
                                     current_position: Optional[Dict[str, Any]]):
        hedge_cfg = (plan.risk or {}).get('hedge') or {}
        if not hedge_cfg.get('enabled'):
            return None
        if not current_position or current_position.get('size', 0) <= 0:
            return None
        current_side = self._normalize_side(current_position.get('side'))
        if current_side == 'flat':
            return None
        size_ratio = self._float(hedge_cfg.get('size_ratio'), default=1.0)
        size_ratio = max(0.05, size_ratio)
        explicit_size = current_position.get('size', 0) * size_ratio
        if explicit_size <= 0:
            return None
        hedge_mode = str(hedge_cfg.get('mode', 'reverse')).lower()
        configured_side = self._normalize_side(hedge_cfg.get('side'))
        if configured_side in ['long', 'short']:
            hedge_action = 'long' if configured_side == 'long' else 'short'
        elif hedge_mode == 'same':
            hedge_action = 'long' if current_side == 'long' else 'short'
        else:  # reverse
            hedge_action = 'short' if current_side == 'long' else 'long'
        hedge_symbol = hedge_cfg.get('symbol') or decision.symbol
        order_type = str(hedge_cfg.get('order_type', 'market')).lower()
        ref_price = self._resolve_reference_price(decision, market_data, current_position)
        price = self._resolve_hedge_price(order_type, hedge_action, hedge_cfg, ref_price, market_data)
        stop_loss, take_profit = self._compute_hedge_targets(hedge_cfg, ref_price, hedge_action)
        position_pct = max(
            self._float(hedge_cfg.get('min_position_pct'), default=0.05) or 0.05,
            decision.position_size
        )
        position_pct = min(1.0, position_pct)
        confidence = hedge_cfg.get('confidence')
        if confidence is None:
            confidence = min(decision.confidence or 0.6, 0.7)

        from .decision_engine import TradingDecision  # 避免循环导入
        hedge_decision = TradingDecision(
            symbol=hedge_symbol,
            action=hedge_action,
            position_size=position_pct,
            position_side='long' if hedge_action == 'long' else 'short',
            price=price if order_type == 'limit' else None,
            stop_loss=stop_loss,
            take_profit=take_profit,
            confidence=confidence,
            reasoning=hedge_cfg.get('reason', f"{plan.name} 事件对冲"),
            signals=decision.signals,
            risk_assessment=decision.risk_assessment.copy() if decision.risk_assessment else {}
        )
        hedge_decision._explicit_size = explicit_size
        if hedge_cfg.get('bypass_risk', True):
            hedge_decision._skip_risk_check = True
        hedge_decision._is_hedge_order = True
        return hedge_decision

    @staticmethod
    def _resolve_reference_price(decision, market_data: Dict[str, Any],
                                 current_position: Optional[Dict[str, Any]]):
        for key in ('price',):
            val = getattr(decision, key, None)
            if val:
                return float(val)
        md_price = (market_data or {}).get('price')
        if md_price:
            return float(md_price)
        if current_position:
            for key in ('current_price', 'average_price', 'avg_price'):
                val = current_position.get(key)
                if val:
                    return float(val)
        return None

    def _resolve_hedge_price(self, order_type: str, action: str, hedge_cfg: Dict[str, Any],
                             ref_price: Optional[float], market_data: Dict[str, Any]):
        if order_type != 'limit' or not ref_price:
            return None
        offset_pct = self._float(hedge_cfg.get('price_offset_pct'), default=0.0) or 0.0
        if action == 'long':
            base = (market_data or {}).get('ask_price') or ref_price
            return base * (1 - offset_pct)
        base = (market_data or {}).get('bid_price') or ref_price
        return base * (1 + offset_pct)

    def _compute_hedge_targets(self, hedge_cfg: Dict[str, Any], ref_price: Optional[float], action: str):
        if not ref_price:
            return None, None
        stop_pct = self._float(hedge_cfg.get('stop_loss_pct'), default=None)
        take_pct = self._float(hedge_cfg.get('take_profit_pct'), default=None)
        stop_abs = self._float(hedge_cfg.get('stop_loss_abs'), default=None)
        take_abs = self._float(hedge_cfg.get('take_profit_abs'), default=None)
        stop_loss = None
        take_profit = None
        if stop_abs:
            stop_loss = ref_price - stop_abs if action == 'long' else ref_price + stop_abs
        elif stop_pct:
            stop_loss = ref_price * (1 - stop_pct) if action == 'long' else ref_price * (1 + stop_pct)
        if take_abs:
            take_profit = ref_price + take_abs if action == 'long' else ref_price - take_abs
        elif take_pct:
            take_profit = ref_price * (1 + take_pct) if action == 'long' else ref_price * (1 - take_pct)
        return stop_loss, take_profit
