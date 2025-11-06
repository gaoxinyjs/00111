#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
信号过滤
信号过滤和验证，假信号识别，信号质量评估
"""

from typing import List, Optional, Any
from datetime import datetime, timedelta
from ..core.config_manager import get_config_manager
from ..core.logger import get_logger
from ..analysis.signal_generator import Signal


class SignalFilter:
    """信号过滤器"""
    
    def __init__(self):
        """初始化信号过滤器"""
        self.config_mgr = get_config_manager()
        self.logger = get_logger("signal_filter")
        
        # 信号历史（用于过滤假信号）
        self.signal_history: List[Signal] = []
        
        # 获取配置
        self.scoring_config = self.config_mgr.get_config('trading', 'signal_scoring')
        self.thresholds = self.scoring_config.get('thresholds', {})
    
    def filter_signals(self, signals: List[Signal]) -> List[Signal]:
        """
        过滤信号
        
        Args:
            signals: 信号列表
            
        Returns:
            过滤后的信号列表
        """
        filtered_signals = []
        
        for signal in signals:
            # 1. 基本过滤
            if signal.type == 'hold' or signal.strength <= 0:
                continue
            
            # 2. 强度过滤
            min_strength = self.thresholds.get('weak', 20) / 100.0
            if signal.strength < min_strength:
                continue
            
            # 3. 假信号检测
            if self._is_fake_signal(signal):
                self.logger.warning(f"检测到假信号: {signal.source} {signal.type}")
                continue
            
            # 4. 时间过滤（信号持续时间）
            if not self._check_signal_duration(signal):
                continue
            
            filtered_signals.append(signal)
        
        return filtered_signals
    
    def _is_fake_signal(self, signal: Signal) -> bool:
        """
        检测假信号
        
        Args:
            signal: 交易信号
            
        Returns:
            是否为假信号
        """
        # 1. 检查是否有足够的成交量支持
        # 2. 检查信号是否与趋势一致
        # 3. 检查是否有其他维度支持
        
        # 简化实现：检查信号历史
        recent_signals = [
            s for s in self.signal_history
            if (datetime.now() - s.timestamp).total_seconds() < 3600  # 最近1小时
        ]
        
        # 如果最近有相反信号，可能是假信号（但降低要求，避免过滤太多真实信号）
        opposite_signals = [
            s for s in recent_signals
            if s.symbol == signal.symbol and s.type != signal.type
        ]
        
        # 放宽要求：只有连续多次相反信号才认为是假信号
        # 要求相反信号超过70%（而不是50%），且至少有3个相反信号
        if len(opposite_signals) > max(3, len(recent_signals) * 0.7):
            return True
        
        return False
    
    def _check_signal_duration(self, signal: Signal) -> bool:
        """
        检查信号持续时间（信号需要持续一段时间才有效）
        
        Args:
            signal: 交易信号
            
        Returns:
            是否通过持续时间检查
        """
        # 检查是否有类似的历史信号
        similar_signals = [
            s for s in self.signal_history
            if s.symbol == signal.symbol
            and s.type == signal.type
            and s.source == signal.source
            and (datetime.now() - s.timestamp).total_seconds() < 7200  # 最近2小时
        ]
        
        # 如果有多个相似信号，说明信号持续（降低要求，允许单个信号）
        if len(similar_signals) >= 1:
            return True
        
        # 如果信号强度很高，可以放宽要求（降低阈值）
        if signal.strength >= 0.5:
            return True
        
        # 如果信号有多个来源支持，也可以放宽要求
        if hasattr(signal, 'source') and signal.source in ['ai', 'multi_timeframe']:
            return True
        
        return False
    
    def update_signal_history(self, signal: Signal):
        """更新信号历史"""
        self.signal_history.append(signal)
        
        # 保留最近1000条信号
        if len(self.signal_history) > 1000:
            self.signal_history = self.signal_history[-1000:]


if __name__ == "__main__":
    # 测试信号过滤器
    from datetime import datetime
    
    filter_obj = SignalFilter()
    
    # 创建测试信号
    signal = Signal(
        symbol="BTC-USDT",
        signal_type="buy",
        strength=0.6,
        source="technical",
        data={},
        timestamp=datetime.now()
    )
    
    filtered = filter_obj.filter_signals([signal])
    print(f"过滤后信号数量: {len(filtered)}")

