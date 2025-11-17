#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
决策引擎
综合多维度信息，生成交易决策，决策风险评估，决策历史记录
"""

from typing import Dict, List, Optional, Any
from datetime import datetime
from dataclasses import dataclass
from ..core.config_manager import get_config_manager
from ..core.logger import get_logger
from ..analysis.signal_generator import SignalGenerator, Signal
from ..decision.position_calculator import PositionCalculator
from ..decision.risk_evaluator import RiskEvaluator
from ..decision.entry_timing_evaluator import EntryTimingEvaluator
from ..decision.scene_detector import SceneDetector
from ..decision.strategy_router import StrategyRouter
from ..core.exception import StrategyException
from datetime import timedelta


@dataclass
class TradingDecision:
    """交易决策"""
    symbol: str
    action: str  # long做多, short做空, close_long平多, close_short平空, hold观望
    position_size: float  # 仓位大小（比例）
    position_side: str = "long"  # 持仓方向：long做多, short做空
    price: Optional[float] = None  # 建议价格
    stop_loss: Optional[float] = None  # 止损价格
    take_profit: Optional[float] = None  # 止盈价格
    confidence: float = 0.0  # 信心度
    reasoning: str = ""  # 决策理由
    signals: List[Dict] = None  # 相关信号
    risk_assessment: Dict = None  # 风险评估结果
    timestamp: datetime = None
    
    def __post_init__(self):
        if self.signals is None:
            self.signals = []
        if self.risk_assessment is None:
            self.risk_assessment = {}
        if self.timestamp is None:
            self.timestamp = datetime.now()
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            'symbol': self.symbol,
            'action': self.action,
            'position_size': self.position_size,
            'position_side': self.position_side,
            'price': self.price,
            'stop_loss': self.stop_loss,
            'take_profit': self.take_profit,
            'confidence': self.confidence,
            'reasoning': self.reasoning,
            'signals': self.signals,
            'risk_assessment': self.risk_assessment,
            'timestamp': self.timestamp.isoformat()
        }


class DecisionEngine:
    """决策引擎"""
    
    def __init__(self):
        """初始化决策引擎"""
        self.config_mgr = get_config_manager()
        self.logger = get_logger("decision_engine")
        trading_pairs_cfg = self.config_mgr.get_config('trading', 'trading_pairs') or []
        self.pair_config_map = {
            pair.get('symbol'): pair
            for pair in trading_pairs_cfg
            if pair.get('symbol')
        }
        self.default_fallback_multipliers = {
            'ai_hold': 0.6,
            'ai_no_direction': 0.5,
            'ai_low_confidence': 0.4
        }
        self.signal_generator = SignalGenerator()
        self.position_calculator = PositionCalculator()
        self.risk_evaluator = RiskEvaluator()
        self.entry_timing_evaluator = EntryTimingEvaluator()
        self.dynamic_confidence_threshold: Optional[float] = None
        self.scene_detector = SceneDetector()
        self.strategy_router = StrategyRouter()
        trading_opt_cfg = self.config_mgr.get_config('trading', 'trading_optimization', {}) or {}
        self.allow_immediate_reentry = trading_opt_cfg.get('allow_immediate_reentry', False)
        
        # 决策历史
        self.decision_history: List[TradingDecision] = []
        
        # 交易统计（针对15分钟K线优化：提高交易频率）
        self.trade_stats = {
            'last_trade_time': None,  # 上次交易时间
            'min_trade_interval': 900,  # 最小交易间隔（秒）- 15分钟（针对15分钟K线优化）
            'recent_losses': 0,  # 最近连续亏损次数
            'max_loss_streak': 3,  # 最大连续亏损次数，超过后暂停交易（放宽到3次）
            'daily_profit': 0.0,  # 当日累计盈亏（比例）
            'last_reset_date': datetime.now().date(),  # 上次重置日期
        }
    
    def _get_leverage(self, symbol: str) -> int:
        """
        获取交易对的杠杆倍数
        
        Args:
            symbol: 交易对符号
            
        Returns:
            杠杆倍数（默认返回1）
        """
        try:
            trading_config = self.config_mgr.get_config('trading', 'trading_pairs')
            for pair in trading_config:
                if pair.get('symbol') == symbol:
                    leverage = pair.get('leverage', 1)
                    return int(leverage) if leverage else 1
            return 1  # 默认1倍杠杆
        except Exception as e:
            self.logger.warning(f"获取杠杆倍数失败 {symbol}: {e}，使用默认值1")
            return 1
    
    def _calculate_stop_loss_take_profit(self, entry_price: float, action: str, 
                                         account_pnl_pct: float = 0.015, 
                                         leverage: int = 1,
                                         market_data: Optional[Dict[str, Any]] = None,
                                         signal_strength: float = 0.5) -> tuple:
        """
        计算考虑杠杆倍数的止盈止损价格（根据市场波动率和信号强度动态调整）
        
        Args:
            entry_price: 开仓价格
            action: 操作方向（long做多, short做空）
            account_pnl_pct: 账户盈亏百分比（默认1.5%）
            leverage: 杠杆倍数（默认1倍）
            market_data: 市场数据（用于获取波动率）
            signal_strength: 信号强度（用于调整止盈）
            
        Returns:
            (stop_loss_price, take_profit_price) 元组
        """
        # 根据市场波动率动态调整止损止盈
        if market_data:
            atr_pct = market_data.get('indicators', {}).get('atr_pct', 1.0)
            if isinstance(atr_pct, str):
                try:
                    atr_pct = float(atr_pct.replace('%', ''))
                except:
                    atr_pct = 1.0
        else:
            atr_pct = 1.0
        
        # 根据波动率调整止损止盈
        if atr_pct < 1.0:
            # 低波动率：止损1.2%，止盈2.5%
            stop_loss_pct = 0.012
            take_profit_pct = 0.025
        elif atr_pct < 2.0:
            # 中等波动率：止损1.5%，止盈3%
            stop_loss_pct = 0.015
            take_profit_pct = 0.03
        else:
            # 高波动率：止损2%，止盈4%
            stop_loss_pct = 0.02
            take_profit_pct = 0.04
        
        # 根据信号强度调整止盈（强烈信号可以提高止盈）
        if signal_strength > 0.75:
            # 强烈信号：止盈3.5%
            take_profit_pct = min(take_profit_pct * 1.17, 0.035)
        elif signal_strength < 0.4:
            # 弱信号：止盈2.5%
            take_profit_pct = max(take_profit_pct * 0.83, 0.025)
        
        # 在杠杆交易中，账户盈亏 = 价格变动百分比 × 杠杆倍数
        # 所以：价格变动百分比 = 账户盈亏 / 杠杆倍数
        stop_loss_price_change_pct = stop_loss_pct / leverage
        take_profit_price_change_pct = take_profit_pct / leverage
        
        if action == 'long':
            # 做多：止损在下方，止盈在上方
            stop_loss_price = entry_price * (1 - stop_loss_price_change_pct)
            take_profit_price = entry_price * (1 + take_profit_price_change_pct)
        else:  # short
            # 做空：止损在上方，止盈在下方
            stop_loss_price = entry_price * (1 + stop_loss_price_change_pct)
            take_profit_price = entry_price * (1 - take_profit_price_change_pct)
        
        return stop_loss_price, take_profit_price
    
    def _get_pair_config(self, symbol: str) -> Dict[str, Any]:
        return self.pair_config_map.get(symbol, {})
    
    def _get_fallback_multiplier(self, symbol: str, reason: str) -> float:
        pair_cfg = self._get_pair_config(symbol)
        multipliers = pair_cfg.get('fallback_multipliers', {}) or {}
        fallback_multiplier = multipliers.get(reason, self.default_fallback_multipliers.get(reason, 0.5))
        return max(0.1, min(fallback_multiplier, 1.0))
    
    def make_decision(self, symbol: str, market_data: Dict[str, Any], 
                     current_position: Optional[Dict[str, Any]] = None) -> Optional[TradingDecision]:
        """
        生成交易决策
        
        Args:
            symbol: 交易对符号
            market_data: 市场数据
            current_position: 当前持仓信息
            
        Returns:
            交易决策
        """
        try:
            self.logger.info(f"开始生成交易决策: {symbol}")
            
        # 0. 检查交易频率限制（针对15分钟K线优化：每15分钟必须生成一次决策）
        # 从配置读取交易间隔（如果配置中有的话）
        trading_config = self.config_mgr.get_config('trading', 'trading_optimization', {})
        min_interval = trading_config.get('min_trade_interval', self.trade_stats['min_trade_interval'])
        self.trade_stats['min_trade_interval'] = min_interval
        allow_immediate_reentry = trading_config.get('allow_immediate_reentry', self.allow_immediate_reentry)
        
        # 计算当前是否存在持仓
        current_position_size = 0.0
        if current_position:
            try:
                current_position_size = float(current_position.get('size', 0) or 0.0)
            except (TypeError, ValueError):
                current_position_size = 0.0
        has_active_position = current_position_size > 0
        
        # 计算距离上次交易的时间
        time_since_last = 0
        if self.trade_stats['last_trade_time']:
            time_since_last = (datetime.now() - self.trade_stats['last_trade_time']).total_seconds()
        
        # 如果存在持仓，则执行冷却限制；否则允许立即重启下一次策略
        if has_active_position and time_since_last > 0 and time_since_last < min_interval:
            remaining_time = min_interval - time_since_last
            if remaining_time > 60:  # 如果剩余时间超过60秒，跳过
                self.logger.warning(
                    f"{symbol}: [交易频率限制] 距离上次交易仅{time_since_last:.0f}秒 < {min_interval}秒，"
                    f"剩余{remaining_time:.0f}秒，跳过"
                )
                return None
            else:
                # 接近15分钟了，允许生成决策（但标记为即将到期）
                self.logger.info(
                    f"{symbol}: [交易频率限制] 距离上次交易{time_since_last:.0f}秒，"
                    f"剩余{remaining_time:.0f}秒，允许生成决策（接近15分钟）"
                )
        elif not has_active_position and time_since_last > 0 and time_since_last < min_interval:
            self.logger.debug(
                f"{symbol}: 当前无持仓，忽略{min_interval}秒冷却限制（上次交易{time_since_last:.0f}秒前）"
            )
            
            # 0.1. 检查日亏损限制（参考ds-main）
            today = datetime.now().date()
            if self.trade_stats['last_reset_date'] != today:
                self.trade_stats['daily_profit'] = 0.0
                self.trade_stats['last_reset_date'] = today
            
            max_daily_loss_pct = trading_config.get('max_daily_loss_pct', 0.02)
            if self.trade_stats['daily_profit'] < -abs(max_daily_loss_pct):
                self.logger.warning(
                    f"{symbol}: [日亏损限制] 当日亏损{self.trade_stats['daily_profit']:.2%} > {max_daily_loss_pct:.2%}，停止交易"
                )
                return None
            
            # 0.2. 检查连续亏损次数（针对15分钟K线优化：放宽到3次）
            # 从配置读取最大连续亏损次数（如果配置中有的话）
            max_loss_streak = trading_config.get('max_loss_streak', self.trade_stats['max_loss_streak'])
            self.trade_stats['max_loss_streak'] = max_loss_streak
            
            if self.trade_stats['recent_losses'] >= max_loss_streak:
                self.logger.warning(
                    f"{symbol}: [连续亏损保护] 连续亏损{self.trade_stats['recent_losses']}次 >= {max_loss_streak}次，暂停交易"
                )
                return None
            
            # 1. 生成信号
            pair_cfg = self._get_pair_config(symbol)
            signals = self.signal_generator.generate_signals(symbol, market_data)
        multi_timeframe = (market_data.get('multi_timeframe') or {})
        entry_direction = multi_timeframe.get('entry_direction', 'neutral')
        entry_timing = multi_timeframe.get('entry_timing', 'hold')
        mtf_confidence = multi_timeframe.get('confidence', 0.0)
        overall_trend = multi_timeframe.get('overall_trend', 'neutral')

        scene_context = None
        strategy_plan = None
        try:
            scene_context = self.scene_detector.detect(symbol, market_data, current_position)
            if scene_context:
                market_data['scene'] = scene_context.to_dict()
                self.logger.info(
                    f"[情景识别] {symbol}: 类型={scene_context.scene_type}, "
                    f"置信度={scene_context.confidence:.2f}, 波动率={scene_context.volatility:.3f}"
                )
            strategy_plan = self.strategy_router.build_plan(scene_context, market_data, current_position)
            if strategy_plan:
                market_data['strategy_plan'] = strategy_plan.to_dict()
                self.logger.info(
                    f"[策略模板] {symbol}: {strategy_plan.name} | 偏向={strategy_plan.bias} | "
                    f"风险={strategy_plan.risk.get('stop_loss')}"
                )
                if entry_direction in (None, '', 'neutral') and strategy_plan.bias in ['long', 'short']:
                    entry_direction = strategy_plan.bias
        except Exception as scene_err:
            self.logger.debug(f"[情景识别] {symbol}: 处理失败 {scene_err}")
            
            # 1.1. 优先检查DeepSeek的结果（必须严格执行）
            ai_signal = None
            deepseek_direction = None
            deepseek_entry_price = None
            deepseek_exit_price = None
            deepseek_confidence = 0.0
            analysis: Dict[str, Any] = {}
            auto_trading_cfg = self.config_mgr.get_config('trading', 'auto_trading', {})
            pair_min_conf = pair_cfg.get('min_confidence')
            min_confidence_cfg = pair_min_conf if pair_min_conf is not None else auto_trading_cfg.get('min_confidence', 0.3)
            if self.dynamic_confidence_threshold is not None:
                try:
                    min_confidence_cfg = max(float(min_confidence_cfg), float(self.dynamic_confidence_threshold))
                except (TypeError, ValueError):
                    min_confidence_cfg = self.dynamic_confidence_threshold
            
            # 查找DeepSeek信号
            for signal in signals:
                if signal.source == 'ai' and signal.data:
                    ai_signal = signal
                    # 从signal.data中提取DeepSeek的分析结果
                    analysis = signal.data.get('analysis', {})
                    if not analysis:
                        analysis = signal.data
                    
                    # 提取direction字段（必须严格执行）
                    deepseek_direction = analysis.get('direction', '').lower()
                    deepseek_entry_price = analysis.get('entry_limit_price', 0)
                    deepseek_exit_price = analysis.get('exit_limit_price', 0)
                    deepseek_confidence = analysis.get('confidence', 0.0)
                    
                    if deepseek_direction in ['long', 'short', 'hold']:
                        # 预先格式化数值，避免在f-string中使用格式说明符
                        try:
                            entry_price_float = float(deepseek_entry_price) if deepseek_entry_price else 0.0
                            entry_price_str = f"{entry_price_float:.5f}" if entry_price_float > 0 else 'N/A'
                        except (ValueError, TypeError):
                            entry_price_str = 'N/A'
                        
                        try:
                            exit_price_float = float(deepseek_exit_price) if deepseek_exit_price else 0.0
                            exit_price_str = f"{exit_price_float:.5f}" if exit_price_float > 0 else 'N/A'
                        except (ValueError, TypeError):
                            exit_price_str = 'N/A'
                        
                        try:
                            confidence_float = float(deepseek_confidence) if deepseek_confidence is not None else 0.0
                            confidence_str = f"{confidence_float:.2f}"
                        except (ValueError, TypeError):
                            confidence_str = 'N/A'
                        
                        self.logger.info(
                            f"🎯 [DeepSeek决策] {symbol}: "
                            f"方向={deepseek_direction} | "
                            f"开仓限价={entry_price_str} | "
                            f"平仓限价={exit_price_str} | "
                            f"信心度={confidence_str}"
                        )
                        break
            
            # 统一处理DeepSeek信心度和方向过滤
            try:
                deepseek_confidence_value = float(deepseek_confidence or 0.0)
            except (ValueError, TypeError):
                deepseek_confidence_value = 0.0
            
            fallback_to_internal = False
            fallback_reason = ""
            if deepseek_direction == 'hold':
                if current_position and current_position.get('size', 0) > 0:
                    self.logger.info(f"{symbol}: DeepSeek建议观望，准备平仓当前持仓")
                    return self._build_close_decision(symbol, current_position, analysis, reason='AI建议观望')
                self.logger.info(f"{symbol}: DeepSeek建议观望，切换为多因子策略")
                fallback_to_internal = True
                fallback_reason = "ai_hold"
            
            if deepseek_direction not in ['long', 'short']:
                self.logger.info(f"{symbol}: DeepSeek未返回有效方向，切换为多因子策略")
                fallback_to_internal = True
                fallback_reason = fallback_reason or "ai_no_direction"
            
            if deepseek_confidence_value < 0.65:
                self.logger.info(
                    f"{symbol}: DeepSeek信心度{deepseek_confidence_value:.2f}低于阈值0.65，将尝试降级处理"
                )
                if current_position and current_position.get('size', 0) > 0:
                    self.logger.info(f"{symbol}: DeepSeek信心度过低，准备平仓当前持仓")
                    return self._build_close_decision(symbol, current_position, analysis, reason='AI信心度不足')
                fallback_to_internal = True
                fallback_reason = fallback_reason or "ai_low_confidence"
            
            if (not fallback_to_internal) and current_position and current_position.get('size', 0) > 0:
                current_side = current_position.get('side', '')
                if current_side == 'buy':
                    current_side = 'long'
                elif current_side == 'sell':
                    current_side = 'short'
                if deepseek_direction != current_side:
                    self.logger.info(
                        f"{symbol}: DeepSeek方向{deepseek_direction}与当前持仓{current_side}相反，准备平仓"
                    )
                    return self._build_close_decision(symbol, current_position, analysis, reason='AI方向反转')
                if deepseek_confidence_value < min_confidence_cfg:
                    self.logger.info(
                        f"{symbol}: DeepSeek信心度{deepseek_confidence_value:.2f}低于最小持仓阈值{min_confidence_cfg:.2f}，准备平仓"
                    )
                    return self._build_close_decision(symbol, current_position, analysis, reason='AI信心度低于最小阈值')
            
            # 如果DeepSeek返回了明确的direction，严格执行
            if not fallback_to_internal and deepseek_direction in ['long', 'short']:
                # DeepSeek明确要求做多或做空，必须严格执行
                self.logger.info(
                    f"✅ [严格执行DeepSeek] {symbol}: DeepSeek要求{'做多' if deepseek_direction == 'long' else '做空'}，"
                    f"将跳过其他信号融合，直接执行DeepSeek的决策"
                )
                
                # 直接使用DeepSeek的direction
                if deepseek_direction == 'long':
                    action = 'long'
                    position_side = 'long'
                else:  # short
                    action = 'short'
                    position_side = 'short'

                signal_score = self._calculate_signal_bias(symbol, signals)
                entry_threshold = auto_trading_cfg.get('entry_signal_threshold', 0.35)
                if (not current_position or current_position.get('size', 0) == 0):
                    if deepseek_direction == 'long' and signal_score < entry_threshold:
                        self.logger.info(
                            f"{symbol}: 多因子评分{signal_score:.2f} < 入场阈值{entry_threshold:.2f}，保持观望"
                        )
                        return None
                    if deepseek_direction == 'short' and signal_score > -entry_threshold:
                        self.logger.info(
                            f"{symbol}: 多因子评分{signal_score:.2f} > -{entry_threshold:.2f}，保持观望"
                        )
                        return None
                
                # 检查当前持仓
                contract_config = self.config_mgr.get_config('trading', 'contract_trading', {})
                is_contract_mode = contract_config.get('enabled', True)
                
                if is_contract_mode and current_position:
                    current_side = current_position.get('side', '')
                    current_size = current_position.get('size', 0)
                    
                    # 兼容持仓方向格式
                    if current_side == 'buy':
                        current_side = 'long'
                    elif current_side == 'sell':
                        current_side = 'short'
                    
                    # 如果已有持仓，且方向相反，需要先平仓
                    if current_size > 0:
                        if current_side == 'long' and action == 'short':
                            action = 'close_long'
                            self.logger.info(f"{symbol}: DeepSeek要求做空，但当前有多仓，先平多")
                        elif current_side == 'short' and action == 'long':
                            action = 'close_short'
                            self.logger.info(f"{symbol}: DeepSeek要求做多，但当前有空仓，先平空")
                        elif current_side == position_side:
                            if time_since_last >= min_interval:
                                self.logger.info(
                                    f"{symbol}: DeepSeek要求{action}，当前已有{current_side}仓，"
                                    f"但距离上次交易已{time_since_last:.0f}秒 >= {min_interval}秒，"
                                    f"允许重新评估（可能需要先平仓）"
                                )
                                if current_side == 'long':
                                    action = 'close_long'
                                    self.logger.info(f"{symbol}: 先平多仓，然后准备开新仓")
                                elif current_side == 'short':
                                    action = 'close_short'
                                    self.logger.info(f"{symbol}: 先平空仓，然后准备开新仓")
                            elif allow_immediate_reentry:
                                self.logger.info(
                                    f"{symbol}: DeepSeek要求{action}，当前已有{current_side}仓，"
                                    f"但距离上次交易仅{time_since_last:.0f}秒 < {min_interval}秒，"
                                    f"根据配置允许立即加仓/调整"
                                )
                                # 维持action为long/short以执行加仓
                            else:
                                self.logger.info(
                                    f"{symbol}: DeepSeek要求{action}，但当前已有{current_side}仓，"
                                    f"且距离上次交易仅{time_since_last:.0f}秒 < {min_interval}秒，"
                                    f"不重复开仓（避免过度加仓）"
                                )
                                return None
                
                # 计算仓位（使用DeepSeek的信心度作为信号强度）
                # 创建一个临时的Signal对象用于计算仓位
                from ..analysis.signal_generator import Signal
                temp_signal = Signal(
                    symbol=symbol,
                    signal_type='buy' if deepseek_direction == 'long' else 'sell',
                    strength=max(0.5, deepseek_confidence),  # 使用DeepSeek的信心度
                    source='ai',
                    data=analysis
                )
                
                position_size = self.position_calculator.calculate_position(
                    temp_signal, market_data, current_position
                )
                
                if position_size <= 0:
                    self.logger.warning(f"{symbol}: DeepSeek要求{action}，但计算仓位为0，跳过")
                    return None
                
                # 入场时机评估（参考ds-main）
                should_enter, entry_timing_summary, entry_timing_details = self.entry_timing_evaluator.evaluate_entry_timing(
                    temp_signal, market_data
                )
                
                # 将入场评分添加到market_data中，供仓位计算器使用
                entry_timing_score = entry_timing_details.get('total_score', 0)
                market_data['entry_timing_score'] = entry_timing_score
                
                if not should_enter:
                    # 针对15分钟K线优化：即使入场时机不佳也执行（但记录警告）
                    self.logger.debug(
                        f"{symbol}: [入场时机评估] 入场时机不佳，但允许交易（针对15分钟K线优化） | {entry_timing_summary}"
                    )
                    # 不return None，允许继续交易（针对15分钟K线优化）
                
                # 重新计算仓位（使用入场时机评分）
                position_size = self.position_calculator.calculate_position(
                    temp_signal, market_data, current_position
                )
                if fallback_to_internal and fallback_reason:
                    fallback_multiplier = self._get_fallback_multiplier(symbol, fallback_reason)
                    position_size *= fallback_multiplier
                    self.logger.info(
                        f"{symbol}: 降级模式({fallback_reason})，仓位按 {fallback_multiplier:.2f} 倍缩放 -> {position_size:.2%}"
                    )
                
                if position_size <= 0:
                    self.logger.warning(f"{symbol}: DeepSeek要求{action}，但计算仓位为0，跳过")
                    return None
                
                # 风险评估（放宽要求，但保留基本安全检查）
                risk_assessment = self.risk_evaluator.evaluate_risk(
                    symbol, temp_signal, position_size, market_data, current_position
                )
                
                # 如果风险评估未通过则拒绝执行
                if not risk_assessment.get('passed', False):
                    risk_level = risk_assessment.get('risk_level', 'unknown')
                    warnings = risk_assessment.get('warnings', [])
                    self.logger.warning(
                        f"{symbol}: [DeepSeek决策] 风险评估未通过，拒绝执行 | "
                        f"风险等级={risk_level}, 警告={'; '.join(warnings) if warnings else '无'}"
                    )
                    return None
                else:
                    self.logger.info(
                        f"{symbol}: [DeepSeek决策] 风险评估通过 | "
                        f"风险等级={risk_assessment.get('risk_level', 'unknown')}"
                    )
                
                # 使用DeepSeek返回的限价（必须严格执行）
                entry_limit_price = deepseek_entry_price if deepseek_entry_price and deepseek_entry_price > 0 else market_data.get('price', 0)
                exit_limit_price = deepseek_exit_price if deepseek_exit_price and deepseek_exit_price > 0 else None
                
                # 如果DeepSeek返回了exit_limit_price，使用它作为止盈目标
                take_profit_price = exit_limit_price or risk_assessment.get('take_profit')
                
                # 验证限价的合理性
                current_price = market_data.get('price', 0)
                try:
                    current_price_float = float(current_price) if current_price else 0.0
                except (ValueError, TypeError):
                    current_price_float = 0.0
                
                try:
                    entry_limit_price_float = float(entry_limit_price) if entry_limit_price else 0.0
                except (ValueError, TypeError):
                    entry_limit_price_float = 0.0
                
                try:
                    exit_limit_price_float = float(exit_limit_price) if exit_limit_price else 0.0
                except (ValueError, TypeError):
                    exit_limit_price_float = 0.0
                
                if action == 'long':
                    # 做多：开仓限价应该低于当前价格，止盈应该高于开仓价格
                    if entry_limit_price_float >= current_price_float * 1.001:  # 如果限价高于当前价格0.1%以上，可能不合理
                        entry_price_str = f"{entry_limit_price_float:.5f}" if entry_limit_price_float > 0 else 'N/A'
                        current_price_str = f"{current_price_float:.5f}" if current_price_float > 0 else 'N/A'
                        self.logger.warning(
                            f"{symbol}: DeepSeek的开仓限价{entry_price_str}高于当前价格{current_price_str}，"
                            f"调整为当前价格的99.9%（低于0.1%）"
                        )
                        entry_limit_price = current_price_float * 0.999
                        entry_limit_price_float = entry_limit_price
                    
                    if exit_limit_price_float > 0 and exit_limit_price_float <= entry_limit_price_float:
                        exit_price_str = f"{exit_limit_price_float:.5f}"
                        entry_price_str = f"{entry_limit_price_float:.5f}"
                        self.logger.warning(
                            f"{symbol}: DeepSeek的平仓限价{exit_price_str}低于开仓限价{entry_price_str}，"
                            f"调整为开仓价格的103%（止盈3%）"
                        )
                        exit_limit_price = entry_limit_price_float * 1.03
                        exit_limit_price_float = exit_limit_price
                        take_profit_price = exit_limit_price
                
                elif action == 'short':
                    # 做空：开仓限价应该高于当前价格，止盈应该低于开仓价格
                    if entry_limit_price_float <= current_price_float * 0.999:  # 如果限价低于当前价格0.1%以上，可能不合理
                        entry_price_str = f"{entry_limit_price_float:.5f}" if entry_limit_price_float > 0 else 'N/A'
                        current_price_str = f"{current_price_float:.5f}" if current_price_float > 0 else 'N/A'
                        self.logger.warning(
                            f"{symbol}: DeepSeek的开仓限价{entry_price_str}低于当前价格{current_price_str}，"
                            f"调整为当前价格的100.1%（高于0.1%）"
                        )
                        entry_limit_price = current_price_float * 1.001
                        entry_limit_price_float = entry_limit_price
                    
                    if exit_limit_price_float > 0 and exit_limit_price_float >= entry_limit_price_float:
                        exit_price_str = f"{exit_limit_price_float:.5f}"
                        entry_price_str = f"{entry_limit_price_float:.5f}"
                        self.logger.warning(
                            f"{symbol}: DeepSeek的平仓限价{exit_price_str}高于开仓限价{entry_price_str}，"
                            f"调整为开仓价格的97%（止盈3%）"
                        )
                        exit_limit_price = entry_limit_price_float * 0.97
                        exit_limit_price_float = exit_limit_price
                        take_profit_price = exit_limit_price
                
                # 计算止盈止损（基于开仓价格，而不是当前价格）
                # 使用DeepSeek的开仓限价作为开仓价格参考
                entry_price_for_sl_tp = entry_limit_price if entry_limit_price > 0 else market_data.get('price', 0)
                
                # 获取杠杆倍数
                leverage = self._get_leverage(symbol)
                
                # 如果risk_assessment中没有止盈止损，基于开仓价格计算（考虑杠杆倍数）
                calculated_stop_loss = risk_assessment.get('stop_loss')
                calculated_take_profit = take_profit_price
                
                if not calculated_stop_loss and entry_price_for_sl_tp > 0:
                    # 计算考虑杠杆倍数的止损（账户盈亏2%）
                    calculated_stop_loss, _ = self._calculate_stop_loss_take_profit(
                        entry_price_for_sl_tp, action, account_pnl_pct=0.02, leverage=leverage
                    )
                    # 只取止损价格
                
                if not calculated_take_profit and entry_price_for_sl_tp > 0:
                    # 计算考虑杠杆倍数的止盈（账户盈亏5%）
                    _, calculated_take_profit = self._calculate_stop_loss_take_profit(
                        entry_price_for_sl_tp, action, account_pnl_pct=0.05, leverage=leverage
                    )
                    # 只取止盈价格
                
                # 如果exit_limit_price存在，使用它作为止盈（但需要考虑杠杆倍数调整）
                if exit_limit_price and exit_limit_price > 0:
                    # 计算基于exit_limit_price的账户盈亏百分比
                    if action == 'long':
                        price_change_pct = (exit_limit_price - entry_price_for_sl_tp) / entry_price_for_sl_tp if entry_price_for_sl_tp > 0 else 0
                    else:
                        price_change_pct = (entry_price_for_sl_tp - exit_limit_price) / entry_price_for_sl_tp if entry_price_for_sl_tp > 0 else 0
                    
                    # 如果exit_limit_price对应的账户盈亏在合理范围内（2%-5%），使用它
                    account_pnl_from_exit = price_change_pct * leverage
                    if 0.02 <= account_pnl_from_exit <= 0.05:
                        calculated_take_profit = exit_limit_price
                        self.logger.info(
                            f"{symbol}: 使用DeepSeek的exit_limit_price作为止盈 | "
                            f"开仓价={entry_price_for_sl_tp:.5f}, 止盈价={exit_limit_price:.5f} | "
                            f"价格变动={price_change_pct*100:.2f}%, 账户盈亏={account_pnl_from_exit*100:.2f}% (杠杆{leverage}x)"
                        )
                
                # 生成决策（严格执行DeepSeek的结果）
                decision = TradingDecision(
                    symbol=symbol,
                    action=action,
                    position_size=position_size,
                    position_side=position_side,
                    price=entry_limit_price,  # 使用DeepSeek的开仓限价
                    stop_loss=calculated_stop_loss,  # 基于开仓价格计算的止损（账户盈亏2%，考虑杠杆倍数）
                    take_profit=calculated_take_profit,  # 基于开仓价格计算的止盈（账户盈亏5%，考虑杠杆倍数）
                    confidence=max(0.7, deepseek_confidence),  # 使用DeepSeek的信心度，但最低0.7
                    reasoning=f"严格执行DeepSeek的决策：{analysis.get('reasoning', 'DeepSeek分析结果')}",
                    signals=[signal.to_dict() for signal in signals if signal.source == 'ai'],
                    risk_assessment=risk_assessment
                )
                if strategy_plan:
                    decision._strategy_plan = strategy_plan.to_dict()
                
                # 标记为DeepSeek决策（用于执行引擎识别，必须严格执行）
                decision._is_deepseek_decision = True
                decision._deepseek_direction = deepseek_direction
                decision._deepseek_entry_price = entry_limit_price
                decision._deepseek_exit_price = exit_limit_price
                decision._fallback = {
                    'used': False,
                    'reason': fallback_reason if fallback_reason else None
                }
                
                # 记录决策
                self.decision_history.append(decision)
                if len(self.decision_history) > 1000:
                    self.decision_history = self.decision_history[-1000:]
                
                action_desc = {
                    'long': '做多',
                    'short': '做空',
                    'close_long': '平多',
                    'close_short': '平空'
                }.get(action, action)
                
                # 确保所有数值都是数字类型，避免格式说明符错误
                try:
                    position_size_float = float(decision.position_size) if decision.position_size is not None else 0.0
                except (ValueError, TypeError):
                    position_size_float = 0.0
                
                try:
                    confidence_float = float(decision.confidence) if decision.confidence is not None else 0.0
                except (ValueError, TypeError):
                    confidence_float = 0.0
                
                try:
                    entry_limit_price_float = float(entry_limit_price) if entry_limit_price is not None else 0.0
                except (ValueError, TypeError):
                    entry_limit_price_float = 0.0
                
                try:
                    exit_limit_price_float = float(exit_limit_price) if exit_limit_price is not None else 0.0
                except (ValueError, TypeError):
                    exit_limit_price_float = 0.0
                
                # 格式化数值，避免在f-string中使用格式说明符
                position_size_str = f"{position_size_float:.2%}"
                confidence_str = f"{confidence_float:.2f}"
                entry_limit_price_str = f"{entry_limit_price_float:.5f}"
                exit_limit_price_str = f"{exit_limit_price_float:.5f}" if exit_limit_price else 'N/A'
                
                self.logger.info(
                    f"🎯 [严格执行DeepSeek决策] {symbol}: {action_desc}({position_side}) | "
                    f"仓位: {position_size_str} | "
                    f"信心度: {confidence_str} | "
                    f"开仓限价: {entry_limit_price_str} | "
                    f"平仓限价: {exit_limit_price_str} | "
                    f"止损: {decision.stop_loss if decision.stop_loss else 'N/A'} | "
                    f"止盈: {decision.take_profit if decision.take_profit else 'N/A'}"
                )
                
                return decision
            elif fallback_to_internal:
                self.logger.info(
                    f"{symbol}: DeepSeek决策降级({fallback_reason})，启用多因子与趋势策略继续评估"
                )
            
            # 像狼一样：敏锐观察，抓住更多机会（进一步降低阈值）
            # 如果多时间周期分析建议观望，且信心度很低，强制选择方向而不是hold
            if entry_timing == 'hold' and mtf_confidence < 0.35:
                self.logger.warning(
                    f"{symbol}: 多时间周期分析建议观望且信心度很低(={mtf_confidence:.2f})，"
                    f"但系统不允许hold，将根据趋势强制选择方向"
                )
                # 根据整体趋势选择方向（继续执行，不返回None）
            
            # 如果多时间周期分析只是watch，且信心度很低，强制选择方向而不是hold
            if entry_timing == 'watch' and mtf_confidence < 0.40:
                self.logger.warning(
                    f"{symbol}: 多时间周期分析建议观察但信心度不足(当前={mtf_confidence:.2f}，要求>=0.45)，"
                    f"但系统不允许hold，将根据趋势强制选择方向"
                )
                # 根据整体趋势选择方向（继续执行，不返回None）
            
            # 2. 融合信号
            combined_signal = self.signal_generator.combine_signals(signals)
            if not combined_signal or (combined_signal and combined_signal.type == 'hold'):
                # 像狼一样：抓住更多机会（进一步降低要求）
                if entry_timing == 'enter' and mtf_confidence >= 0.40 and overall_trend in ['bullish', 'bearish']:
                    self.logger.info(
                        f"{symbol}: 🐺像狼一样发现机会！多时间周期建议入场"
                        f"(方向={entry_direction}, 信心度={mtf_confidence:.2f}, 趋势={overall_trend})"
                    )
                    # 如果combined_signal是None，创建一个新的Signal对象
                    if not combined_signal:
                        from ..analysis.signal_generator import Signal
                        combined_signal = Signal(
                            symbol=symbol,
                            signal_type='hold',  # 临时值，下面会修改
                            strength=0.0,
                            source='multi_timeframe',
                            data={}
                        )
                    # 根据多时间周期分析的方向生成信号（像狼一样快速出击）
                    if entry_direction == 'long':
                        combined_signal.type = 'buy'
                        combined_signal.strength = min(0.7, mtf_confidence * 0.9)  # 根据信心度调整强度
                    elif entry_direction == 'short':
                        combined_signal.type = 'sell'
                        combined_signal.strength = min(0.7, mtf_confidence * 0.9)  # 根据信心度调整强度
                elif entry_timing == 'watch' and mtf_confidence >= 0.35:
                    # 即使只是watch，但如果信心度足够，也可以尝试（抓住更多机会）
                    self.logger.info(
                        f"{symbol}: 🐺像狼一样尝试机会！多时间周期观察模式但信心度足够"
                        f"(方向={entry_direction}, 信心度={mtf_confidence:.2f}, 趋势={overall_trend})"
                    )
                    # 如果combined_signal是None，创建一个新的Signal对象
                    if not combined_signal:
                        from ..analysis.signal_generator import Signal
                        combined_signal = Signal(
                            symbol=symbol,
                            signal_type='hold',  # 临时值，下面会修改
                            strength=0.0,
                            source='multi_timeframe',
                            data={}
                        )
                    if entry_direction == 'long':
                        combined_signal.type = 'buy'
                        combined_signal.strength = min(0.6, mtf_confidence * 0.85)  # 稍低的强度
                    elif entry_direction == 'short':
                        combined_signal.type = 'sell'
                        combined_signal.strength = min(0.6, mtf_confidence * 0.85)  # 稍低的强度
                else:
                    self.logger.info(f"{symbol}: 融合信号为hold，且多时间周期分析不支持入场，保持观望")
                    return None
            
            # 确保combined_signal存在（防御性编程）
            if not combined_signal:
                self.logger.warning(f"{symbol}: 融合信号为None，无法生成决策")
                return None
            
            # 3. 合约交易：转换信号类型（buy->long, sell->short）
            contract_config = self.config_mgr.get_config('trading', 'contract_trading', {})
            is_contract_mode = contract_config.get('enabled', True)
            
            # 判断交易动作和方向
            signal_type = combined_signal.type
            # 不允许hold，强制根据趋势选择方向
            # 根据整体趋势选择long或short
            multi_timeframe = market_data.get('multi_timeframe', {})
            overall_trend = multi_timeframe.get('overall_trend', '').lower()
            
            if '上涨' in overall_trend or '看涨' in overall_trend or 'up' in overall_trend:
                action = 'long'
                self.logger.info(f"{symbol}: 根据整体趋势（上涨），强制选择long")
            elif '下跌' in overall_trend or '看跌' in overall_trend or 'down' in overall_trend:
                action = 'short'
                self.logger.info(f"{symbol}: 根据整体趋势（下跌），强制选择short")
            else:
                # 如果无法判断趋势，根据当前价格变化选择
                current_price = market_data.get('price', 0)
                change_24h = market_data.get('change_24h', 0)
                try:
                    change_24h_float = float(change_24h) if change_24h else 0.0
                    if change_24h_float > 0:
                        action = 'long'
                        self.logger.info(f"{symbol}: 根据24h涨跌（+{change_24h_float:.2f}%），强制选择long")
                    else:
                        action = 'short'
                        self.logger.info(f"{symbol}: 根据24h涨跌（{change_24h_float:.2f}%），强制选择short")
                except (ValueError, TypeError):
                    # 如果无法判断，默认选择long
                    action = 'long'
                    self.logger.info(f"{symbol}: 无法判断趋势，默认选择long")
            
            position_side = 'long' if action == 'long' else 'short'
            
            if is_contract_mode:
                # 合约模式：buy->long做多, sell->short做空
                if signal_type == 'buy':
                    action = 'long'
                    position_side = 'long'
                elif signal_type == 'sell':
                    # 检查是否允许做空
                    if contract_config.get('allow_short', True):
                        action = 'short'
                        position_side = 'short'
                    else:
                        self.logger.info(f"{symbol}: 做空被禁用，保持观望")
                        return None
            else:
                # 现货模式：buy/sell
                action = signal_type
                position_side = 'long'  # 现货只能做多
            
            # 合约交易：检查当前持仓，决定开仓还是平仓
            if is_contract_mode and current_position:
                current_side = current_position.get('side', '')  # long或short
                current_size = current_position.get('size', 0)
                
                # 兼容持仓方向格式
                if current_side == 'buy':
                    current_side = 'long'
                elif current_side == 'sell':
                    current_side = 'short'
                
                # 如果已有持仓，且信号方向相反，需要先平仓
                if current_size > 0:
                    if current_side == 'long' and action == 'short':
                        # 有多仓，信号要做空，先平多
                        action = 'close_long'
                        self.logger.info(f"{symbol}: 当前有多仓，先平仓后再开空仓")
                    elif current_side == 'short' and action == 'long':
                        # 有空仓，信号要做多，先平空
                        action = 'close_short'
                        self.logger.info(f"{symbol}: 当前有空仓，先平仓后再开多仓")
                    elif current_side == position_side:
                        # 同方向持仓，检查是否距离上次交易已超过15分钟
                        # 如果超过15分钟，允许重新评估（可能需要调整仓位或平仓后重新开仓）
                        if time_since_last >= min_interval:
                            self.logger.info(
                                f"{symbol}: 当前已有{current_side}仓（持仓量={current_size:.4f}），"
                                f"信号方向相同，但距离上次交易已{time_since_last:.0f}秒 >= {min_interval}秒，"
                                f"允许重新评估（可能需要先平仓）"
                            )
                            # 先平仓，然后开新仓
                            if current_side == 'long':
                                action = 'close_long'
                                self.logger.info(f"{symbol}: 先平多仓，然后准备开新仓")
                            elif current_side == 'short':
                                action = 'close_short'
                                self.logger.info(f"{symbol}: 先平空仓，然后准备开新仓")
                            # 继续执行，会在平仓后生成新的开仓决策
                        else:
                            # 距离上次交易不足15分钟，不重复开仓
                            self.logger.info(
                                f"{symbol}: 当前已有{current_side}仓（持仓量={current_size:.4f}），"
                                f"信号方向一致，且距离上次交易仅{time_since_last:.0f}秒 < {min_interval}秒，"
                                f"不重复开仓（避免过度加仓）"
                            )
                            return None  # 同方向已有持仓，不重复开仓
            
            # 3. 计算仓位
            position_size = self.position_calculator.calculate_position(
                combined_signal, market_data, current_position
            )
            
            if position_size <= 0:
                self.logger.info(f"{symbol}: 计算仓位为0，不执行交易")
                return None
            
            # 4. 风险评估
            risk_assessment = self.risk_evaluator.evaluate_risk(
                symbol, combined_signal, position_size, market_data, current_position
            )
            
            # 5. 风险检查
            if not risk_assessment.get('passed', False):
                risk_level = risk_assessment.get('risk_level', 'unknown')
                warnings = risk_assessment.get('warnings', [])
                var = risk_assessment.get('var', 0.0)
                # 确保var是数字类型，避免格式说明符错误
                try:
                    var_float = float(var) if var is not None else 0.0
                except (ValueError, TypeError):
                    var_float = 0.0
                
                var_str = f"{var_float:.2%}"
                
                self.logger.warning(
                    f"{symbol}: [风险评估] 未通过，拒绝交易 | "
                    f"风险等级={risk_level}, VaR={var_str}, "
                    f"警告={'; '.join(warnings) if warnings else '无'}"
                )
                return None
            
            # 记录风险评估通过
            risk_level = risk_assessment.get('risk_level', 'unknown')
            var = risk_assessment.get('var', 0.0)
            # 确保var是数字类型，避免格式说明符错误
            try:
                var_float = float(var) if var is not None else 0.0
            except (ValueError, TypeError):
                var_float = 0.0
            
            var_str = f"{var_float:.2%}"
            
            self.logger.info(
                f"{symbol}: [风险评估] 通过 | "
                f"风险等级={risk_level}, VaR={var_str}, "
                f"止损={risk_assessment.get('stop_loss', 'N/A')}, "
                f"止盈={risk_assessment.get('take_profit', 'N/A')}"
            )
            
            # 5.1. 优先使用DeepSeek返回的限价（如果AI信号中有的话）
            ai_signal = None
            entry_limit_price = None
            exit_limit_price = None
            
            # 查找AI信号（DeepSeek返回的信号）
            for signal in signals:
                if signal.source == 'ai' and signal.data:
                    ai_signal = signal
                    # 从signal.data中提取限价信息
                    analysis = signal.data.get('analysis', {})
                    if not analysis:
                        analysis = signal.data
                    
                    entry_limit_price = analysis.get('entry_limit_price', 0)
                    exit_limit_price = analysis.get('exit_limit_price', 0)
                    
                    # 如果entry_limit_price有效，使用它
                    if entry_limit_price and entry_limit_price > 0:
                        self.logger.info(
                            f"{symbol}: 使用DeepSeek返回的开仓限价: {entry_limit_price:.5f}"
                        )
                    break
            
            # 如果没有AI限价，计算最佳入场价格（基于技术指标）
            if not entry_limit_price or entry_limit_price <= 0:
                entry_limit_price = self._calculate_optimal_entry_price(
                    symbol, action, position_side, market_data, combined_signal
                )
            
            # 如果AI返回了exit_limit_price，使用它作为止盈目标
            take_profit_price = risk_assessment.get('take_profit')
            if exit_limit_price and exit_limit_price > 0:
                # 验证exit_limit_price是否合理（止盈应该比开仓价格更有利）
                if action == 'long' and exit_limit_price > entry_limit_price:
                    take_profit_price = exit_limit_price
                    self.logger.info(
                        f"{symbol}: 使用DeepSeek返回的平仓限价（止盈）: {exit_limit_price:.5f}"
                    )
                elif action == 'short' and exit_limit_price < entry_limit_price:
                    take_profit_price = exit_limit_price
                    self.logger.info(
                        f"{symbol}: 使用DeepSeek返回的平仓限价（止盈）: {exit_limit_price:.5f}"
                    )
            
            # 6. 生成决策（包含最佳入场价格）
            decision = TradingDecision(
                symbol=symbol,
                action=action,
                position_size=position_size,
                position_side=position_side,
                price=entry_limit_price,  # 使用DeepSeek限价或计算出的最佳入场价格
                stop_loss=risk_assessment.get('stop_loss'),
                take_profit=take_profit_price or risk_assessment.get('take_profit'),
                confidence=combined_signal.strength,
                reasoning=self._build_reasoning(combined_signal, signals, risk_assessment),
                signals=[s.to_dict() for s in signals],
                risk_assessment=risk_assessment
            )
        if strategy_plan:
            decision._strategy_plan = strategy_plan.to_dict()
        decision._fallback = {
            'used': bool(fallback_to_internal),
            'reason': fallback_reason if fallback_reason else None
        }
        
        # 7. 记录决策历史
        self.decision_history.append(decision)
        if len(self.decision_history) > 1000:
            self.decision_history = self.decision_history[-1000:]
        
        # 记录决策（合约交易模式）
        if is_contract_mode:
                action_desc = {
                    'long': '做多',
                    'short': '做空',
                    'close_long': '平多',
                    'close_short': '平空',
                    'hold': '观望'
                }.get(action, action)
                # 确保所有数值都是数字类型，避免格式说明符错误
                try:
                    position_size_float = float(decision.position_size) if decision.position_size is not None else 0.0
                except (ValueError, TypeError):
                    position_size_float = 0.0
                
                try:
                    confidence_float = float(decision.confidence) if decision.confidence is not None else 0.0
                except (ValueError, TypeError):
                    confidence_float = 0.0
                
                # 格式化数值，避免在f-string中使用格式说明符
                position_size_str = f"{position_size_float:.2%}"
                confidence_str = f"{confidence_float:.2f}"
                
                self.logger.info(
                    f"[合约决策] {symbol}: {action_desc}({position_side}) | "
                    f"仓位: {position_size_str} | "
                    f"信心度: {confidence_str} | "
                    f"止损: {decision.stop_loss if decision.stop_loss else 'N/A'} | "
                    f"止盈: {decision.take_profit if decision.take_profit else 'N/A'}"
                )
            else:
                # 确保所有数值都是数字类型，避免格式说明符错误
                try:
                    position_size_float = float(decision.position_size) if decision.position_size is not None else 0.0
                except (ValueError, TypeError):
                    position_size_float = 0.0
                
                try:
                    confidence_float = float(decision.confidence) if decision.confidence is not None else 0.0
                except (ValueError, TypeError):
                    confidence_float = 0.0
                
                # 格式化数值，避免在f-string中使用格式说明符
                position_size_str = f"{position_size_float:.2%}"
                confidence_str = f"{confidence_float:.2f}"
                
                self.logger.info(f"{symbol}: 生成决策 {decision.action}, 仓位 {position_size_str}, 信心度 {confidence_str}")
            
            return decision
        
        except Exception as e:
            self.logger.error(f"生成交易决策失败 {symbol}: {e}")
            raise StrategyException(f"生成交易决策失败: {e}")
    
    def _build_close_decision(self, symbol: str, current_position: Dict[str, Any],
                              analysis: Dict[str, Any], reason: str) -> TradingDecision:
        """构建AI触发的平仓决策"""
        position_side_raw = current_position.get('side', 'long')
        if position_side_raw == 'buy':
            position_side = 'long'
        elif position_side_raw == 'sell':
            position_side = 'short'
        else:
            position_side = position_side_raw

        if position_side == 'long':
            decision_action = 'close_long'
        else:
            decision_action = 'close_short'

        confidence_val = 0.8
        try:
            confidence_val = float(analysis.get('confidence', confidence_val))
        except (TypeError, ValueError):
            confidence_val = 0.8

        return TradingDecision(
            symbol=symbol,
            action=decision_action,
            position_size=1.0,
            position_side=position_side,
            price=None,
            stop_loss=None,
            take_profit=None,
            confidence=max(confidence_val, 0.7),
            reasoning=reason,
            signals=[{'source': 'ai', 'analysis': analysis}],
            risk_assessment={'reason': reason, 'trigger': 'ai_exit'}
        )

    def set_confidence_override(self, threshold: Optional[float]):
        """设置AI最小信心度覆盖值"""
        if threshold is None:
            self.dynamic_confidence_threshold = None
            return
        try:
            value = float(threshold)
            self.dynamic_confidence_threshold = max(0.0, min(value, 1.0))
        except (TypeError, ValueError):
            self.dynamic_confidence_threshold = None

    def _calculate_signal_bias(self, symbol: str, signals: List[Signal]) -> float:
        """根据全部信号计算多因子方向倾向"""
        score = 0.0
        for signal in signals:
            try:
                if signal.symbol != symbol:
                    continue
                if signal.type == 'buy':
                    score += float(signal.strength or 0.0)
                elif signal.type == 'sell':
                    score -= float(signal.strength or 0.0)
            except Exception:
                continue
        return score

    def _calculate_optimal_entry_price(self, symbol: str, action: str, position_side: str,
                                      market_data: Dict[str, Any], signal: Signal) -> Optional[float]:
        """
        计算最佳入场价格（基于技术指标：支撑位、阻力位、布林带、均线等）
        
        Args:
            symbol: 交易对符号
            action: 交易动作（long, short等）
            position_side: 持仓方向（long, short）
            market_data: 市场数据
            signal: 交易信号
            
        Returns:
            最佳入场价格（如果无法计算则返回当前价格）
        """
        try:
            current_price = market_data.get('price', 0)
            if current_price <= 0:
                return None
            
            indicators = market_data.get('indicators', {})
            kline_data = market_data.get('kline', []) or market_data.get('kline_1H', [])
            
            # 获取技术指标
            bb_upper = indicators.get('bb_upper', 0)
            bb_middle = indicators.get('bb_middle', 0)
            bb_lower = indicators.get('bb_lower', 0)
            ma_5 = indicators.get('ma_5', 0)
            ma_20 = indicators.get('ma_20', 0)
            ma_60 = indicators.get('ma_60', 0)
            
            # 计算支撑位和阻力位（基于K线数据）
            support_level = None
            resistance_level = None
            
            if kline_data and len(kline_data) >= 20:
                # 获取最近20根K线的最低价和最高价
                recent_lows = [float(k.get('low', 0)) for k in kline_data[-20:] if k.get('low')]
                recent_highs = [float(k.get('high', 0)) for k in kline_data[-20:] if k.get('high')]
                
                if recent_lows:
                    # 支撑位：最近20根K线的最低价
                    support_level = min(recent_lows)
                
                if recent_highs:
                    # 阻力位：最近20根K线的最高价
                    resistance_level = max(recent_highs)
            
            # 根据交易方向计算最佳入场价格
            optimal_price = current_price  # 默认使用当前价格
            
            if action == 'long' or position_side == 'long':
                # 做多：寻找支撑位附近的低价买入
                price_candidates = []
                
                # 候选价格1：布林带下轨（如果有）
                if bb_lower > 0 and bb_lower < current_price:
                    price_candidates.append(('布林带下轨', bb_lower))
                
                # 候选价格2：支撑位（如果有）
                if support_level and support_level < current_price:
                    price_candidates.append(('支撑位', support_level))
                
                # 候选价格3：20日均线（如果有，且在当前价格下方）
                if ma_20 > 0 and ma_20 < current_price:
                    price_candidates.append(('20日均线', ma_20))
                
                # 候选价格4：60日均线（如果有，且在当前价格下方）
                if ma_60 > 0 and ma_60 < current_price:
                    price_candidates.append(('60日均线', ma_60))
                
                # 候选价格5：当前价格下方0.3%（给一点滑点空间）
                price_candidates.append(('当前价-0.3%', current_price * 0.997))
                
                # 选择最佳价格：选择最低的候选价格，但不能太低（不能低于当前价格的3%）
                min_price = current_price * 0.97  # 最低不能低于当前价格的3%
                
                if price_candidates:
                    # 过滤出合理的价格（在当前价格下方，但不能太低）
                    valid_candidates = [
                        (desc, price) for desc, price in price_candidates
                        if min_price <= price < current_price
                    ]
                    
                    if valid_candidates:
                        # 选择最低的合理价格
                        valid_candidates.sort(key=lambda x: x[1])
                        optimal_price = valid_candidates[0][1]
                        self.logger.info(
                            f"{symbol}: [最佳入场价] 做多 | "
                            f"当前价={current_price:.5f}, "
                            f"最佳价={optimal_price:.5f} ({valid_candidates[0][0]}), "
                            f"差价={(current_price - optimal_price) / current_price * 100:.2f}%"
                        )
                    else:
                        # 如果没有合理的候选价格，使用当前价格下方0.2%
                        optimal_price = current_price * 0.998
                        self.logger.info(
                            f"{symbol}: [最佳入场价] 做多 | "
                            f"使用默认策略：当前价={current_price:.5f}, "
                            f"最佳价={optimal_price:.5f} (当前价-0.2%)"
                        )
                else:
                    optimal_price = current_price * 0.998
                    self.logger.info(
                        f"{symbol}: [最佳入场价] 做多 | "
                        f"使用默认策略：当前价={current_price:.5f}, "
                        f"最佳价={optimal_price:.5f} (当前价-0.2%)"
                    )
            
            elif action == 'short' or position_side == 'short':
                # 做空：寻找阻力位附近的高价卖出
                price_candidates = []
                
                # 候选价格1：布林带上轨（如果有）
                if bb_upper > 0 and bb_upper > current_price:
                    price_candidates.append(('布林带上轨', bb_upper))
                
                # 候选价格2：阻力位（如果有）
                if resistance_level and resistance_level > current_price:
                    price_candidates.append(('阻力位', resistance_level))
                
                # 候选价格3：20日均线（如果有，且在当前价格上方）
                if ma_20 > 0 and ma_20 > current_price:
                    price_candidates.append(('20日均线', ma_20))
                
                # 候选价格4：60日均线（如果有，且在当前价格上方）
                if ma_60 > 0 and ma_60 > current_price:
                    price_candidates.append(('60日均线', ma_60))
                
                # 候选价格5：当前价格上方0.3%（给一点滑点空间）
                price_candidates.append(('当前价+0.3%', current_price * 1.003))
                
                # 选择最佳价格：选择最高的候选价格，但不能太高（不能高于当前价格的3%）
                max_price = current_price * 1.03  # 最高不能高于当前价格的3%
                
                if price_candidates:
                    # 过滤出合理的价格（在当前价格上方，但不能太高）
                    valid_candidates = [
                        (desc, price) for desc, price in price_candidates
                        if current_price < price <= max_price
                    ]
                    
                    if valid_candidates:
                        # 选择最高的合理价格
                        valid_candidates.sort(key=lambda x: x[1], reverse=True)
                        optimal_price = valid_candidates[0][1]
                        self.logger.info(
                            f"{symbol}: [最佳入场价] 做空 | "
                            f"当前价={current_price:.5f}, "
                            f"最佳价={optimal_price:.5f} ({valid_candidates[0][0]}), "
                            f"差价={(optimal_price - current_price) / current_price * 100:.2f}%"
                        )
                    else:
                        # 如果没有合理的候选价格，使用当前价格上方0.2%
                        optimal_price = current_price * 1.002
                        self.logger.info(
                            f"{symbol}: [最佳入场价] 做空 | "
                            f"使用默认策略：当前价={current_price:.5f}, "
                            f"最佳价={optimal_price:.5f} (当前价+0.2%)"
                        )
                else:
                    optimal_price = current_price * 1.002
                    self.logger.info(
                        f"{symbol}: [最佳入场价] 做空 | "
                        f"使用默认策略：当前价={current_price:.5f}, "
                        f"最佳价={optimal_price:.5f} (当前价+0.2%)"
                    )
            
            return optimal_price if optimal_price > 0 else current_price
            
        except Exception as e:
            self.logger.warning(f"计算最佳入场价格失败 {symbol}: {e}，使用当前价格")
            return market_data.get('price', 0)
    
    def _build_reasoning(self, combined_signal: Signal, signals: List[Signal], 
                        risk_assessment: Dict[str, Any]) -> str:
        """
        构建决策理由
        
        Args:
            combined_signal: 融合信号
            signals: 所有信号
            risk_assessment: 风险评估结果
            
        Returns:
            决策理由字符串
        """
        reasoning_parts = []
        
        # 信号分析
        reasoning_parts.append(f"信号分析: 融合{len(signals)}个维度信号，强度{combined_signal.strength:.2f}")
        
        # 各维度信号
        signal_summary = []
        for signal in signals:
            if signal.type != 'hold':
                signal_summary.append(f"{signal.source}({signal.type}, {signal.strength:.2f})")
        
        if signal_summary:
            reasoning_parts.append(f"维度信号: {', '.join(signal_summary)}")
        
        # 风险评估
        risk_level = risk_assessment.get('risk_level', 'unknown')
        reasoning_parts.append(f"风险评估: {risk_level}")
        
        # VaR
        var = risk_assessment.get('var', 0)
        if var > 0:
            # 确保var是数字类型，避免格式说明符错误
            try:
                var_float = float(var) if var is not None else 0.0
            except (ValueError, TypeError):
                var_float = 0.0
            
            var_str = f"{var_float:.2%}"
            reasoning_parts.append(f"VaR: {var_str}")
        
        return " | ".join(reasoning_parts)
    
    def get_decision_history(self, symbol: Optional[str] = None, 
                           limit: int = 100) -> List[TradingDecision]:
        """
        获取决策历史
        
        Args:
            symbol: 交易对符号，如果为None则返回所有
            limit: 返回数量限制
            
        Returns:
            决策历史列表
        """
        if symbol:
            decisions = [d for d in self.decision_history if d.symbol == symbol]
        else:
            decisions = self.decision_history
        
        return decisions[-limit:]
    
    def should_execute_decision(self, decision: TradingDecision) -> bool:
        """
        判断是否应该执行决策
        
        Args:
            decision: 交易决策
            
        Returns:
            是否应该执行
        """
        # 基本检查
        if decision.position_size <= 0:
            return False
        
        if decision.confidence < 0.3:
            return False
        
        # 风险检查
        if not decision.risk_assessment.get('passed', False):
            return False
        
        # 信号强度检查
        thresholds = self.config_mgr.get_config('trading', 'signal_scoring.thresholds')
        min_threshold = thresholds.get('weak', 20) / 100.0
        
        if decision.confidence < min_threshold:
            return False
        
        return True


if __name__ == "__main__":
    # 测试决策引擎
    engine = DecisionEngine()
    
    # 模拟市场数据
    market_data = {
        'price': 50000,
        'kline': [
            {'timestamp': i * 3600000, 'open': 50000 + i * 10, 'high': 50100 + i * 10,
             'low': 49900 + i * 10, 'close': 50050 + i * 10, 'volume': 1000 + i * 100}
            for i in range(100)
        ],
        'funding': {
            'large_order_flow': 'inflow',
            'funding_rate': -0.05,
            'exchange_balance_change': -0.03
        }
    }
    
    print("生成交易决策...")
    decision = engine.make_decision("BTC-USDT", market_data)
    
    if decision:
        print(f"决策: {decision.action}")
        print(f"仓位: {decision.position_size:.2%}")
        print(f"信心度: {decision.confidence:.2f}")
        print(f"理由: {decision.reasoning}")
        print(f"是否执行: {engine.should_execute_decision(decision)}")
    else:
        print("未生成有效决策")

