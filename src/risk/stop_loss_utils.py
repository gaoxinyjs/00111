#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
止损工具方法

统一计算不同交易对的杠杆、价格止损距离及账户级别风险，
避免在多个模块里重复手写换算逻辑。
"""

from __future__ import annotations

from typing import Optional

from ..core.config_manager import get_config_manager


def _get_stop_loss_config(config_mgr=None) -> dict:
    mgr = config_mgr or get_config_manager()
    return mgr.get_config('risk', 'stop_loss')


def get_symbol_leverage(symbol: str, config_mgr=None, default: Optional[float] = None) -> float:
    """
    获取交易对配置的杠杆，若未配置则返回stop_loss.default_leverage或指定默认值
    """
    mgr = config_mgr or get_config_manager()
    stop_loss_cfg = _get_stop_loss_config(mgr)
    fallback = default if default is not None else stop_loss_cfg.get('default_leverage', 1)
    try:
        trading_pairs = mgr.get_config('trading', 'trading_pairs', [])
        for pair in trading_pairs or []:
            if pair.get('symbol') == symbol:
                leverage = float(pair.get('leverage', fallback) or fallback)
                return max(leverage, 1.0)
    except Exception:
        pass
    return float(fallback) if fallback else 1.0


def clamp_price_pct(price_pct: float, stop_loss_cfg: dict) -> float:
    """根据配置限制价格层面的止损百分比"""
    min_pct = stop_loss_cfg.get('min_price_stop_loss_pct')
    max_pct = stop_loss_cfg.get('max_price_stop_loss_pct')
    if min_pct is not None:
        price_pct = max(price_pct, float(min_pct))
    if max_pct is not None:
        price_pct = min(price_pct, float(max_pct))
    return max(price_pct, 0.0001)


def account_pct_to_price_pct(account_pct: float, leverage: float,
                             stop_loss_cfg: Optional[dict] = None, clamp: bool = True) -> float:
    """将账户维度的亏损比例换算为价格层面的止损距离"""
    if leverage <= 0:
        leverage = 1.0
    price_pct = account_pct / leverage
    if stop_loss_cfg is None:
        stop_loss_cfg = _get_stop_loss_config()
    if clamp:
        return clamp_price_pct(price_pct, stop_loss_cfg)
    return max(price_pct, 0.0)


def get_symbol_price_stop_pct(symbol: str, config_mgr=None) -> float:
    """
    计算指定交易对的基础价格止损距离
    1. 优先依据 account_stop_loss_pct / leverage
    2. 若未配置，则回落到 default_stop_loss_pct
    """
    mgr = config_mgr or get_config_manager()
    stop_loss_cfg = _get_stop_loss_config(mgr)
    default_price_pct = stop_loss_cfg.get('default_stop_loss_pct', 0.01)
    account_stop_pct = stop_loss_cfg.get('account_stop_loss_pct')
    leverage = get_symbol_leverage(symbol, mgr)
    if account_stop_pct:
        price_pct = account_pct_to_price_pct(float(account_stop_pct), leverage, stop_loss_cfg)
    else:
        price_pct = float(default_price_pct)
    return clamp_price_pct(price_pct, stop_loss_cfg)


def get_symbol_account_loss_pct(symbol: str, config_mgr=None) -> float:
    """
    返回在基础止损触发时，账户层面预计的亏损比例（价格止损 * 杠杆）
    """
    mgr = config_mgr or get_config_manager()
    stop_loss_cfg = _get_stop_loss_config(mgr)
    account_stop_pct = stop_loss_cfg.get('account_stop_loss_pct')
    if account_stop_pct:
        return float(account_stop_pct)
    price_pct = get_symbol_price_stop_pct(symbol, mgr)
    leverage = get_symbol_leverage(symbol, mgr)
    return price_pct * leverage
