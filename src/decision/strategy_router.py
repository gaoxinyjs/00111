#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
策略模板路由器：根据行情情景选择交易模板并生成计划
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Any, Optional, List
from datetime import datetime

from ..core.config_manager import get_config_manager
from .scene_detector import SceneContext


@dataclass
class StrategyPlan:
    """策略计划，供决策引擎参考"""
    name: str
    scene_type: str
    bias: str
    confidence: float
    entries: List[Dict[str, Any]] = field(default_factory=list)
    risk: Dict[str, Any] = field(default_factory=dict)
    notes: List[str] = field(default_factory=list)
    timestamp: datetime = field(default_factory=datetime.utcnow)

    def to_dict(self) -> Dict[str, Any]:
        return {
            'name': self.name,
            'scene_type': self.scene_type,
            'bias': self.bias,
            'confidence': round(self.confidence, 4),
            'entries': self.entries,
            'risk': self.risk,
            'notes': self.notes,
            'timestamp': self.timestamp.isoformat()
        }


class StrategyRouter:
    """将情景映射到策略模板"""

    def __init__(self):
        self.config_mgr = get_config_manager()
        templates_cfg = self.config_mgr.get_config('trading', 'strategy_templates', {}) or {}
        self.templates = templates_cfg or self._default_templates()

    def build_plan(self, scene: SceneContext, market_data: Dict[str, Any],
                   current_position: Optional[Dict[str, Any]] = None) -> StrategyPlan:
        scene_type = scene.scene_type if scene else 'neutral'
        symbol = market_data.get('symbol')
        template = self._resolve_template(symbol, scene_type)
        plan = StrategyPlan(
            name=template.get('name', 'default'),
            scene_type=scene_type,
            bias=template.get('bias', 'neutral'),
            confidence=scene.confidence if scene else 0.5,
            entries=template.get('entries', []),
            risk=self._merge_risk(template.get('risk', {}), current_position),
            notes=template.get('notes', [])
        )
        return plan

    def _merge_risk(self, risk_cfg: Dict[str, Any], current_position: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        risk = dict(risk_cfg)
        if current_position and current_position.get('size', 0) > 0:
            risk.setdefault('manage_existing', True)
        return risk

    def _resolve_template(self, symbol: Optional[str], scene_type: str) -> Dict[str, Any]:
        symbol_templates = self.templates.get('symbols', {}) if isinstance(self.templates, dict) else {}
        scene_templates = self.templates.get('scenes', {}) if isinstance(self.templates, dict) else {}
        if symbol and symbol in symbol_templates:
            return symbol_templates[symbol].get(scene_type, symbol_templates[symbol].get('default', self._default_templates()[scene_type]))
        default_templates = self._default_templates()
        return (
            scene_templates.get(scene_type)
            or self.templates.get(scene_type)
            or default_templates.get(scene_type)
            or default_templates.get('neutral')
        )

    def _default_templates(self) -> Dict[str, Dict[str, Any]]:
        return self.config_mgr.get_config('trading', 'strategy_templates_defaults', {
            'trend_up': {
                'name': 'trend_follow_long',
                'bias': 'long',
                'entries': [
                    {'type': 'layer', 'price_offset': -0.003, 'size_ratio': 0.6, 'order_type': 'limit'},
                    {'type': 'layer', 'price_offset': 0.0, 'size_ratio': 0.4, 'order_type': 'market'},
                ],
                'risk': {
                    'stop_loss': 'trail_atr',
                    'take_profit': 'partial_scale_out',
                    'max_position_pct': 0.25
                },
                'notes': ['保持顺势，逐步抬升止损']
            },
            'trend_down': {
                'name': 'trend_follow_short',
                'bias': 'short',
                'entries': [
                    {'type': 'layer', 'price_offset': 0.003, 'size_ratio': 0.6, 'order_type': 'limit'},
                    {'type': 'layer', 'price_offset': 0.0, 'size_ratio': 0.4, 'order_type': 'market'},
                ],
                'risk': {
                    'stop_loss': 'trail_atr',
                    'take_profit': 'partial_scale_out',
                    'max_position_pct': 0.25
                },
                'notes': ['关注主动卖盘和持仓成本']
            },
            'range': {
                'name': 'range_play',
                'bias': 'neutral',
                'entries': [
                    {'type': 'layer', 'price_offset': -0.004, 'size_ratio': 0.5, 'order_type': 'limit'},
                    {'type': 'layer', 'price_offset': 0.004, 'size_ratio': 0.5, 'order_type': 'limit'},
                ],
                'risk': {
                    'stop_loss': 'tight_percent',
                    'take_profit': 'fixed_rr',
                    'max_position_pct': 0.15
                },
                'notes': ['快速止盈止损，避免突破行情']
            },
            'event': {
                'name': 'event_defense',
                'bias': 'neutral',
                'entries': [
                    {'type': 'suspend_new_orders'}
                ],
                'risk': {
                    'stop_loss': 'reduce_only',
                    'take_profit': 'n/a',
                    'max_position_pct': 0.1,
                    'circuit_breaker': {
                        'enabled': True,
                        'cooldown_seconds': 900
                    }
                },
                'notes': ['事件期以风险控制为主，可触发熔断']
            },
            'neutral': {
                'name': 'observation',
                'bias': 'neutral',
                'entries': [],
                'risk': {'stop_loss': 'standard', 'max_position_pct': 0.1},
                'notes': ['数据不足，保持观望']
            }
        })
