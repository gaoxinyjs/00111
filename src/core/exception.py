#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
自定义异常类
"""


class TradingSystemException(Exception):
    """交易系统基础异常"""
    pass


class ConfigException(TradingSystemException):
    """配置异常"""
    pass


class APIException(TradingSystemException):
    """API异常"""
    pass


class DataException(TradingSystemException):
    """数据异常"""
    pass


class TradingException(TradingSystemException):
    """交易异常"""
    pass


class RiskException(TradingSystemException):
    """风险异常"""
    pass


class OrderException(TradingException):
    """订单异常"""
    pass


class BalanceException(TradingException):
    """余额异常"""
    pass


class StrategyException(TradingSystemException):
    """策略异常"""
    pass


class PaymentRequiredException(APIException):
    """API需要付费异常（用于降级策略）"""
    pass