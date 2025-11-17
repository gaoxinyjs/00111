#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
行情情景识别器：基于多周期趋势、波动率、事件信号和持仓状态输出标准化场景
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional, Dict, Any
from datetime import datetime

from ..core.config_manager import get_config_manager


@dataclass
class SceneContext:
    """行情情景上下文"""
    symbol: str
    scene_type: str
    confidence: float
    volatility: float
    trend: str
    timestamp: datetime = field(default_factory=datetime.utcnow)
    details: Dict[str, Any] = field(default_factory=dict)
    holding: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            'symbol': self.symbol,
            'type': self.scene_type,
            'confidence': round(self.confidence, 4),
            'volatility': self.volatility,
            'trend': self.trend,
            'timestamp': self.timestamp.isoformat(),
            'details': self.details,
            'holding': self.holding,
        }


class SceneDetector:
    """根据市场数据识别行情情景"""

    def __init__(self):
        self.config_mgr = get_config_manager()
        scene_cfg = self.config_mgr.get_config('trading', 'scene_detection', {}) or {}
        self.trend_adx_threshold = scene_cfg.get('trend_adx_threshold', 20)
        self.range_vol_threshold = scene_cfg.get('range_vol_threshold', 2.5)  # ATR%
        self.bb_width_threshold = scene_cfg.get('bb_width_threshold', 0.05)
        self.event_score_threshold = scene_cfg.get('event_score_threshold', 0.6)

    def detect(self, symbol: str, market_data: Dict[str, Any],
               current_position: Optional[Dict[str, Any]] = None) -> SceneContext:
        indicators = (market_data or {}).get('indicators', {}) or {}
        multi_tf = (market_data or {}).get('multi_timeframe', {}) or {}
        events = (market_data or {}).get('events', {}) or {}

        atr_pct = self._to_float(indicators.get('atr_pct'), default=0.0)
        bb_width = self._to_float(indicators.get('bb_width'), default=0.0)
        adx = self._to_float(indicators.get('adx'), default=None)
        volatility = self._to_float(indicators.get('volatility'), default=atr_pct / 100 if atr_pct else 0.0)
        overall_trend = (multi_tf.get('overall_trend') or '').lower()
        events_score = self._to_float(events.get('score'), default=0.0)
        events_label = events.get('label', '')

        scene_type = 'neutral'
        confidence = 0.45
        trend_desc = overall_trend or 'neutral'

        # 事件优先级最高
        if events_score >= self.event_score_threshold:
            scene_type = 'event'
            confidence = min(1.0, 0.7 + events_score / 2)
        else:
            trend_conf = self._evaluate_trend_confidence(adx, overall_trend)
            if trend_conf > 0.6:
                scene_type = 'trend_up' if 'bull' in overall_trend or 'up' in overall_trend else 'trend_down'
                confidence = trend_conf
            elif atr_pct <= self.range_vol_threshold and bb_width <= self.bb_width_threshold:
                scene_type = 'range'
                confidence = min(0.85, 0.5 + (self.range_vol_threshold - atr_pct) / max(self.range_vol_threshold, 1))

        holding_ctx = self._build_holding_context(current_position)

        details = {
            'atr_pct': atr_pct,
            'bb_width': bb_width,
            'adx': adx,
            'events': {'score': events_score, 'label': events_label},
            'multi_timeframe': {
                'overall_trend': overall_trend,
                'entry_direction': multi_tf.get('entry_direction'),
                'entry_timing': multi_tf.get('entry_timing'),
                'confidence': multi_tf.get('confidence'),
            }
        }

        return SceneContext(
            symbol=symbol,
            scene_type=scene_type,
            confidence=round(confidence, 4),
            volatility=round(volatility, 5),
            trend=trend_desc,
            details=details,
            holding=holding_ctx
        )

    def _evaluate_trend_confidence(self, adx: Optional[float], trend: str) -> float:
        if adx is None or adx <= 0:
            return 0.0
        base = min(1.0, adx / max(self.trend_adx_threshold, 1))
        if trend in ('bullish', 'bearish', 'up', 'down'):
            return min(0.95, 0.4 + base * 0.6)
        return base * 0.5

    def _build_holding_context(self, current_position: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        if not current_position or current_position.get('size', 0) <= 0:
            return {'status': 'flat'}
        size = self._to_float(current_position.get('size'), default=0.0)
        avg_price = self._to_float(current_position.get('avg_price') or current_position.get('average_price'), default=0.0)
        pnl = self._to_float(current_position.get('unrealized_pnl'), default=0.0)
        side = current_position.get('side', 'long')
        return {
            'status': 'holding',
            'side': side,
            'size': size,
            'avg_price': avg_price,
            'unrealized_pnl': pnl
        }

    @staticmethod
    def _to_float(value, default: float = 0.0) -> float:
        try:
            if value is None:
                return default
            if isinstance(value, str) and value.endswith('%'):
                return float(value.rstrip('%'))
            return float(value)
        except (TypeError, ValueError):
            return default
