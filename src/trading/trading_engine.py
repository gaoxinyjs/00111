#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
交易引擎
整合数据采集、信号生成、决策、执行、风险管理的完整交易流程
"""
import asyncio
import json
from copy import deepcopy
from pathlib import Path
from typing import Dict, List, Optional, Any
from datetime import datetime, timezone
from ..core.config_manager import get_config_manager
from ..core.logger import get_logger
from ..data.data_collector import DataCollector
from ..data.data_processor import DataProcessor
from ..analysis.signal_generator import SignalGenerator
from ..analysis.signal_filter import SignalFilter
from ..decision.decision_engine import DecisionEngine
from ..trading.execution_engine import ExecutionEngine
from ..risk.risk_manager import RiskManager
from ..risk.position_controller import PositionController
from ..trading.position_manager import PositionManager
from ..monitoring.profit_statistics import ProfitStatistics
from ..data.okx_client import get_okx_client
from ..core.exception import TradingSystemException


class TradingEngine:
    """交易引擎"""
    
    def __init__(self):
        """初始化交易引擎"""
        self.config_mgr = get_config_manager()
        self.logger = get_logger("trading_engine")
        
        # 初始化各个模块
        trading_pairs_cfg = self.config_mgr.get_config('trading', 'trading_pairs') or []
        self.pair_config_map = {
            pair.get('symbol'): pair
            for pair in trading_pairs_cfg
            if pair.get('symbol')
        }
        self.orderflow_analysis_cfg = self.config_mgr.get_config('trading', 'orderflow_analysis', {}) or {}
        self.macro_events_cfg = self.config_mgr.get_config('risk', 'macro_events', {}) or {}
        self.data_collector = DataCollector()
        self.data_processor = DataProcessor()
        self.signal_generator = SignalGenerator()
        self.signal_filter = SignalFilter()
        self.decision_engine = DecisionEngine()
        self.execution_engine = ExecutionEngine()
        self.risk_manager = RiskManager()
        self.position_controller = PositionController()
        self.position_manager = PositionManager()
        self.profit_statistics = ProfitStatistics()
        self.okx_client = None  # 异步初始化
        self._latest_market_data: Dict[str, Dict[str, Any]] = {}
        self._latest_market_data_ts: Optional[datetime] = None
        
        # 多时间周期分析器
        from ..analysis.multi_timeframe_analyzer import MultiTimeframeAnalyzer
        self.multi_timeframe_analyzer = MultiTimeframeAnalyzer()
        
        # AI仓位管理器
        from ..decision.ai_position_manager import AIPositionManager
        self.ai_position_manager = AIPositionManager()
        
        # 自学习：交易结果记录和提示词优化
        from ..learning.trade_result_recorder import TradeResultRecorder
        from ..learning.prompt_optimizer import PromptOptimizer
        self.result_recorder = TradeResultRecorder()
        self.prompt_optimizer = PromptOptimizer()
        self.strategy_guidelines: List[Dict[str, Any]] = []
        self._active_emphasis_factors: List[str] = []
        self._active_caution_factors: List[str] = []
        self._prompt_opt_running = False
        
        # 记录优化触发间隔（每10笔交易优化一次）
        self.optimization_interval = 10
        self.trade_count_since_optimization = 0
        
        # 交易状态
        self.is_running = False
        
        # 市场数据缓存（用于自学习记录）
        self.market_data_cache: Dict[str, Dict[str, Any]] = {}
        
        # 跟踪待成交的委托订单（用于避免重复创建）
        # key: symbol, value: {'order': Order, 'decision': TradingDecision, 'create_time': datetime}
        self.pending_orders: Dict[str, Dict[str, Any]] = {}
        
        # 跟踪持仓开仓时间（用于15分钟强制平仓）
        # key: symbol, value: {'entry_time': datetime, 'position_side': str, 'size': float}
        self.position_entry_times: Dict[str, Dict[str, Any]] = {}
        
        # 跟踪已开仓的交易记录信息，用于平仓写入结果
        self.active_trade_records: Dict[str, Dict[str, Any]] = {}
        
        # 交易记录日志目录
        self.trade_log_dir = Path("logs/trades")
        self.trade_log_dir.mkdir(parents=True, exist_ok=True)
        
        # 15分钟超时配置（秒）
        self.force_close_timeout = 15 * 60  # 15分钟 = 900秒（强制平仓）
        self.pending_order_timeout = 15 * 60  # 15分钟 = 900秒（挂单超时）
        
        # 从配置读取是否启用自动交易
        auto_trading_config = self.config_mgr.get_config('trading', 'auto_trading', {})
        self.trading_enabled = auto_trading_config.get('enabled', True)
        self.min_confidence = auto_trading_config.get('min_confidence', 0.3)
        self.min_position_size = auto_trading_config.get('min_position_size', 0.01)
        
        ai_position_config = self.config_mgr.get_config('trading', 'ai_position_management', {}) or {}
        self.ai_review_enabled = ai_position_config.get('enabled', True)
        # 强制设置为60秒（1分钟），确保每分钟检查一次持仓
        try:
            config_interval = int(ai_position_config.get('review_interval', 60))
            # 如果配置的间隔小于60秒，使用60秒；否则使用配置值
            self.ai_review_interval = max(60, config_interval)
        except (TypeError, ValueError):
            self.ai_review_interval = 60
        max_adj = ai_position_config.get('max_adjustments_per_cycle')
        try:
            max_adj_val = int(max_adj)
            self.ai_review_max_adjustments = max_adj_val if max_adj_val > 0 else None
        except (TypeError, ValueError):
            self.ai_review_max_adjustments = None
        self.ai_review_task = None
        
        # 注册数据回调
        self._register_callbacks()
    
    def _register_callbacks(self):
        """注册数据回调"""
        # 注册行情数据回调
        self.data_collector.register_callback('ticker', self._on_ticker_update)
    
    def _on_ticker_update(self, ticker_data: Dict[str, Any]):
        """行情数据更新回调"""
        symbol = ticker_data.get('symbol')
        self.logger.debug(f"行情更新: {symbol} = {ticker_data.get('price')}")
    
    async def start(self):
        """启动交易引擎"""
        if self.is_running:
            self.logger.warning("交易引擎已在运行")
            return
        
        self.is_running = True
        self.logger.info("=" * 60)
        self.logger.info("交易引擎启动中...")
        self.logger.info("=" * 60)
        
        try:
            # 1. 初始化账户
            await self._initialize_account()
            
            # 2. 启动数据采集
            asyncio.create_task(self.data_collector.start_collection_loop())
            
            # 2.1. 启动快速止损检查任务（每5秒检查一次，保护资金）
            asyncio.create_task(self._rapid_stop_loss_check_loop())
            
            # 2.2. 启动AI仓位审查任务（按配置间隔执行）
            if self.ai_review_enabled and self.ai_review_task is None:
                self.ai_review_task = asyncio.create_task(self._ai_position_review_loop())
            
            # 3. 启动主交易循环
            await self._main_trading_loop()
        
        except Exception as e:
            self.logger.error(f"交易引擎运行失败: {e}")
            raise TradingSystemException(f"交易引擎运行失败: {e}")
        finally:
            self.is_running = False
    
    async def stop(self):
        """停止交易引擎"""
        self.is_running = False
        self.logger.info("交易引擎停止中...")
        
        # 取消所有未完成的订单
        await self._cancel_all_orders()
        
        # 取消AI审查任务
        if self.ai_review_task:
            self.ai_review_task.cancel()
            try:
                await self.ai_review_task
            except asyncio.CancelledError:
                pass
            self.ai_review_task = None
        
        self.logger.info("交易引擎已停止")
    
    async def _initialize_account(self):
        """初始化账户"""
        try:
            # 获取OKX客户端单例
            if self.okx_client is None:
                self.okx_client = await get_okx_client()
            # 获取账户余额
            balance_data = await self.okx_client.async_get_balance()
            
            if balance_data:
                balance = float(balance_data[0].get('availBal', 0)) if balance_data else 0
                self.profit_statistics.save_balance_snapshot(balance)
                self.logger.info(f"账户初始化完成，当前余额: {balance:.2f} USDT")
            else:
                self.logger.warning("无法获取账户余额")
        
        except Exception as e:
            self.logger.error(f"账户初始化失败: {e}")
    
    def _get_next_15min_interval(self, current_time: Optional[datetime] = None) -> datetime:
        """
        计算下一个15分钟整点时间（如9:00、9:15、9:30、9:45）
        
        Args:
            current_time: 当前时间，如果为None则使用当前时间
            
        Returns:
            下一个15分钟整点的datetime对象
        """
        if current_time is None:
            current_time = datetime.now()
        
        # 获取当前时间的分钟数
        current_minute = current_time.minute
        
        # 计算下一个15分钟整点
        # 例如：如果现在是9:07，下一个整点是9:15
        # 如果现在是9:15，下一个整点是9:30
        next_minute = ((current_minute // 15) + 1) * 15
        
        if next_minute >= 60:
            # 如果超过60分钟，则进入下一小时
            next_time = current_time.replace(
                hour=(current_time.hour + 1) % 24,
                minute=0,
                second=0,
                microsecond=0
            )
        else:
            # 在同一小时内
            next_time = current_time.replace(
                minute=next_minute,
                second=0,
                microsecond=0
            )
        
        return next_time
    
    async def _wait_until_next_15min_interval(self):
        """
        等待到下一个15分钟整点时间
        """
        current_time = datetime.now()
        next_interval = self._get_next_15min_interval(current_time)
        
        # 计算需要等待的秒数
        wait_seconds = (next_interval - current_time).total_seconds()
        
        if wait_seconds > 0:
            self.logger.info(
                f"⏰ [等待整点时间] 当前时间: {current_time.strftime('%H:%M:%S')}, "
                f"下一个15分钟整点: {next_interval.strftime('%H:%M:%S')}, "
                f"等待时间: {wait_seconds:.1f}秒"
            )
            await asyncio.sleep(wait_seconds)
        else:
            # 如果已经过了整点，等待下一个整点
            next_interval = self._get_next_15min_interval(next_interval)
            wait_seconds = (next_interval - current_time).total_seconds()
            self.logger.info(
                f"⏰ [等待整点时间] 当前时间: {current_time.strftime('%H:%M:%S')}, "
                f"下一个15分钟整点: {next_interval.strftime('%H:%M:%S')}, "
                f"等待时间: {wait_seconds:.1f}秒"
            )
            await asyncio.sleep(wait_seconds)
    
    async def _main_trading_loop(self):
        """主交易循环"""
        try:
            signal_interval = self.config_mgr.get_config('main', 'scheduler.signal_generation_interval')
        except (KeyError, TypeError):
            signal_interval = 300  # 默认5分钟
        
        self.logger.info(f"主交易循环启动，将在每15分钟整点执行交易（如9:00、9:15、9:30、9:45）")
        
        # 首次启动时，等待到下一个15分钟整点
        await self._wait_until_next_15min_interval()
        
        while self.is_running:
            try:
                # 记录当前执行时间
                execution_time = datetime.now()
                self.logger.info(f"🕐 [整点执行] 当前时间: {execution_time.strftime('%H:%M:%S')}，开始执行交易逻辑")
                
                # 1. 数据采集（已在后台运行）
                # 等待数据采集完成
                await asyncio.sleep(1)
                
                # 2. 获取市场数据（包含多时间周期数据）
                market_data = await self._collect_market_data()
                self._update_market_data_cache(market_data)
                
                # 2.1. 多时间周期趋势分析和量价分析
                multi_timeframe_analysis = self.multi_timeframe_analyzer.analyze_trends(market_data)
                
                # 将多时间周期分析结果添加到市场数据中
                for symbol, analysis in multi_timeframe_analysis.items():
                    if symbol in market_data:
                        market_data[symbol]['multi_timeframe'] = analysis
                        
                        # 记录多时间周期分析结果
                        self.logger.info(
                            f"[多周期分析] {symbol} | "
                            f"15m趋势: {analysis.get('trend_15m', 'N/A')} | "
                            f"4H趋势: {analysis.get('trend_4H', 'N/A')} | "
                            f"1H趋势: {analysis.get('trend_1H', 'N/A')} | "
                            f"综合趋势: {analysis.get('overall_trend', 'N/A')} | "
                            f"趋势强度: {analysis.get('trend_strength', 0):.2f} | "
                            f"入场时机: {analysis.get('entry_timing', 'N/A')} | "
                            f"入场方向: {analysis.get('entry_direction', 'N/A')} | "
                            f"信心度: {analysis.get('confidence', 0):.2f}"
                        )
                
                # 3. 生成信号（结合多时间周期分析）
                signals = await self._generate_signals(market_data)
                
                # 4. 过滤信号
                filtered_signals = self.signal_filter.filter_signals(signals)
                
                # 5. 生成决策
                decisions = await self._make_decisions(market_data, filtered_signals)
                
                # 5.1. AI仓位管理和智能平仓检查（在生成新决策前）
                await self._check_position_adjustments(
                    market_data,
                    enable_ai_analysis=False
                )
                
                # 6. 执行交易
                await self._execute_trades(decisions)
                
                # 7. 更新持仓
                await self._update_positions()
                
                # 7.1. 持仓止损检查（更新持仓后立即检查） - 更频繁的止损保护
                await self._check_position_adjustments(
                    market_data,
                    enable_ai_analysis=False
                )
                
                # 7.2. 检查15分钟强制平仓（每15分钟检查一次）
                await self._check_force_close_positions(market_data)
                
                # 7.3. 检查15分钟挂单超时（每15分钟检查一次）
                await self._check_pending_orders_timeout(market_data)
                
                # 8. 风险监控
                await self._monitor_risk()
                
                # 等待到下一个15分钟整点
                await self._wait_until_next_15min_interval()
            
            except Exception as e:
                self.logger.error(f"主交易循环出错: {e}")
                await asyncio.sleep(10)  # 出错后等待10秒再继续
    
    async def _collect_market_data(self, symbols: Optional[List[str]] = None) -> Dict[str, Dict[str, Any]]:
        """
        收集市场数据
        
        Args:
            symbols: 需要收集的交易对列表（为None时收集全部配置的交易对）
        
        Returns:
            市场数据字典（按交易对索引）
        """
        market_data: Dict[str, Dict[str, Any]] = {}
        
        try:
            trading_pairs = self.config_mgr.get_config('trading', 'trading_pairs')
            symbols_filter = set(symbols) if symbols else None
            symbols_to_collect: List[str] = []
            
            for pair in trading_pairs:
                if not pair.get('enabled', True):
                    continue
                symbol = pair.get('symbol')
                if symbols_filter and symbol not in symbols_filter:
                    continue
                symbols_to_collect.append(symbol)
            
            if not symbols_to_collect:
                return market_data
            
            tasks = [self._collect_symbol_market_data(symbol) for symbol in symbols_to_collect]
            results = await asyncio.gather(*tasks, return_exceptions=True)
            
            collected_symbols = set()
            for symbol, result in zip(symbols_to_collect, results):
                if isinstance(result, Exception):
                    self.logger.error(f"收集{symbol}市场数据失败: {result}")
                    continue
                if not result:
                    continue
                market_data[symbol] = result
                self.market_data_cache[symbol] = result.copy()
                collected_symbols.add(symbol)
            
            if symbols_filter:
                missing_symbols = symbols_filter - collected_symbols
                for symbol in missing_symbols:
                    self.logger.warning(f"请求的交易对{symbol}未在交易配置中找到或数据收集失败")
        
        except Exception as e:
            self.logger.error(f"收集市场数据失败: {e}")
        
        return market_data
    
    def _update_market_data_cache(self, market_data: Dict[str, Dict[str, Any]],
                                  symbols: Optional[List[str]] = None):
        """更新市场数据缓存"""
        if not market_data:
            return
        now = datetime.now()
        if symbols:
            if not self._latest_market_data:
                self._latest_market_data = {}
            for symbol in symbols:
                if symbol in market_data:
                    self._latest_market_data[symbol] = deepcopy(market_data[symbol])
        else:
            self._latest_market_data = deepcopy(market_data)
        self._latest_market_data_ts = now
    
    def _get_cached_market_data(self, symbols: Optional[List[str]] = None,
                                max_age_seconds: int = 5) -> Optional[Dict[str, Dict[str, Any]]]:
        """在允许的时间窗内返回缓存的市场数据"""
        if not self._latest_market_data_ts:
            return None
        age = (datetime.now() - self._latest_market_data_ts).total_seconds()
        if age > max_age_seconds:
            return None
        if symbols:
            if any(symbol not in self._latest_market_data for symbol in symbols):
                return None
            return deepcopy({symbol: self._latest_market_data[symbol] for symbol in symbols})
        return deepcopy(self._latest_market_data)

    def _derive_session_tag(self, current_time: Optional[datetime] = None) -> str:
        """根据UTC时间估算交易会话"""
        now = current_time or datetime.utcnow()
        hour = now.hour
        if 0 <= hour < 8:
            return 'asia'
        if 8 <= hour < 16:
            return 'europe'
        return 'us'
    
    def _derive_volatility_regime(self, market_data: Dict[str, Any]) -> str:
        """根据波动率指标估算市场状态"""
        indicators = (market_data or {}).get('indicators', {}) or {}
        volatility = indicators.get('volatility')
        try:
            vol_value = float(str(volatility).replace('%', ''))
            if vol_value < 2:
                return 'low'
            if vol_value < 4:
                return 'medium'
            return 'high'
        except (ValueError, TypeError):
            return 'unknown'
    
    def _build_strategy_context(self, decision, ai_analysis: Dict[str, Any],
                                market_data: Dict[str, Any]) -> Dict[str, Any]:
        """构建用于自学习的策略快照"""
        ai_analysis = ai_analysis or {}
        multi_timeframe = (market_data or {}).get('multi_timeframe', {}) or {}
        fallback_meta = getattr(decision, '_fallback', {})
        context = {
            'position': {
                'size': decision.position_size,
                'side': decision.position_side,
                'stop_loss': decision.stop_loss,
                'take_profit': decision.take_profit
            },
            'risk_assessment': decision.risk_assessment,
            'signals': decision.signals,
            'fallback': fallback_meta,
            'entry_timing': multi_timeframe.get('entry_timing'),
            'multi_timeframe': multi_timeframe,
            'ai_confidence': ai_analysis.get('confidence'),
            'ai_recommendation': ai_analysis.get('recommendation'),
            'key_factors': ai_analysis.get('key_factors')
        }
        return context
    
    def _get_prompt_optimization_threshold(self) -> int:
        """根据近期表现动态设定触发优化所需的交易数量"""
        base_threshold = self.optimization_interval
        try:
            stats = self.result_recorder.get_performance_stats()
            win_rate = stats.get('win_rate', 0) or 0
            total_trades = stats.get('total_trades', 0) or 0
            if total_trades >= 5 and win_rate < 40:
                base_threshold = max(5, int(self.optimization_interval * 0.8))
            elif total_trades >= 10 and win_rate > 60:
                base_threshold = int(self.optimization_interval * 1.5)
        except Exception as e:
            self.logger.debug(f"计算提示词优化阈值失败: {e}")
        return max(5, base_threshold)
    
    def _schedule_prompt_optimization(self):
        """在达到条件时异步触发提示词优化"""
        if self._prompt_opt_running:
            return
        threshold = self._get_prompt_optimization_threshold()
        if self.trade_count_since_optimization < threshold:
            return
        if not self.prompt_optimizer:
            return
        self._prompt_opt_running = True
        asyncio.create_task(self._run_prompt_optimization(threshold))
    
    async def _run_prompt_optimization(self, min_trades: int):
        """后台执行提示词优化并应用指导原则"""
        try:
            self.logger.info(f"[自学习] 达到{min_trades}笔交易，启动提示词优化")
            optimized_prompt = await asyncio.to_thread(self.prompt_optimizer.optimize_prompt, min_trades)
            if optimized_prompt:
                guidelines = self.prompt_optimizer.get_current_guidelines()
                self.logger.info(
                    f"[自学习] 提示词优化完成，版本: {optimized_prompt.get('version')}, "
                    f"指导原则数: {len(guidelines)}"
                )
                self._apply_guidelines_to_strategy(guidelines)
                self.trade_count_since_optimization = 0
            else:
                self.logger.info("[自学习] 本轮无可用优化建议")
        except Exception as e:
            self.logger.error(f"[自学习] 提示词优化失败: {e}")
        finally:
            self._prompt_opt_running = False
    
    def _apply_guidelines_to_strategy(self, guidelines: List[Dict[str, Any]]):
        """将提示词指导原则反馈至策略与决策引擎"""
        self.strategy_guidelines = guidelines or []
        confidence_applied = False
        self._active_emphasis_factors = []
        self._active_caution_factors = []
        
        for guideline in self.strategy_guidelines:
            gtype = guideline.get('type')
            if gtype == 'confidence_threshold':
                value = guideline.get('value')
                try:
                    threshold = float(value)
                    self.decision_engine.set_confidence_override(threshold)
                    self.min_confidence = max(self.min_confidence, threshold)
                    confidence_applied = True
                    self.logger.info(f"[自学习] 应用AI信心度下限: {threshold:.2f}")
                except (TypeError, ValueError):
                    self.logger.warning(f"[自学习] 无法解析信心度指导: {value}")
            elif gtype == 'emphasis':
                self._active_emphasis_factors = guideline.get('factors', []) or []
                self.logger.info(f"[自学习] 重点关注因子: {', '.join(self._active_emphasis_factors)}")
            elif gtype == 'deemphasis':
                self._active_caution_factors = guideline.get('factors', []) or []
                self.logger.info(f"[自学习] 谨慎因子: {', '.join(self._active_caution_factors)}")
        
        if not confidence_applied:
            self.decision_engine.set_confidence_override(None)

    async def _collect_symbol_market_data(self, symbol: str) -> Optional[Dict[str, Any]]:
        """并发采集单个交易对的行情、K线、指标与订单簿"""
        try:
            ticker = await self.data_collector.collect_ticker(symbol)
        except Exception as e:
            self.logger.error(f"收集{symbol}行情失败: {e}")
            return None
        
        try:
            kline_15m, kline_1h, kline_4h = await asyncio.gather(
                self.data_collector.collect_kline(symbol, '15m', 100),
                self.data_collector.collect_kline(symbol, '1H', 100),
                self.data_collector.collect_kline(symbol, '4H', 100)
            )
        except Exception as e:
            self.logger.error(f"收集{symbol}K线数据失败: {e}")
            return None
        
        orderbook_data: Dict[str, Any] = {}
        funding_data: Dict[str, Any] = {}
        open_interest_data: Dict[str, Any] = {}
        taker_volume_data: Dict[str, Any] = {}
        long_short_ratio_data: Dict[str, Any] = {}
        recent_trades: List[Dict[str, Any]] = []
        orderflow_metrics: Dict[str, Any] = {}
        
        try:
            (
                orderbook_result,
                funding_result,
                oi_result,
                taker_volume_result,
                long_short_result,
                trades_result,
                mark_price_result,
                index_price_result,
                liquidation_result
            ) = await asyncio.gather(
                self.data_collector.collect_orderbook(symbol, 20),
                self.data_collector.collect_funding_rate(symbol),
                self.data_collector.collect_open_interest(symbol),
                self.data_collector.collect_taker_volume(symbol),
                self.data_collector.collect_long_short_ratio(symbol),
                self.data_collector.collect_recent_trades(symbol, 120),
                self.data_collector.collect_mark_price(symbol),
                self.data_collector.collect_index_price(symbol),
                self.data_collector.collect_liquidations(symbol),
                return_exceptions=True
            )
        except Exception as gather_error:
            self.logger.warning(f"{symbol}: 批量采集前瞻指标失败: {gather_error}", exc_info=True)
            orderbook_result = funding_result = oi_result = taker_volume_result = long_short_result = trades_result = None
        
        if isinstance(orderbook_result, Exception):
            self.logger.warning(f"{symbol}: 订单簿采集出错: {orderbook_result}")
            orderbook_result = None
        if isinstance(funding_result, Exception):
            self.logger.warning(f"{symbol}: 资金费率采集出错: {funding_result}")
            funding_result = None
        if isinstance(oi_result, Exception):
            self.logger.warning(f"{symbol}: 未平仓量采集出错: {oi_result}")
            oi_result = None
        if isinstance(taker_volume_result, Exception):
            self.logger.warning(f"{symbol}: 主动买卖量采集出错: {taker_volume_result}")
            taker_volume_result = None
        if isinstance(long_short_result, Exception):
            self.logger.warning(f"{symbol}: 多空账户占比采集出错: {long_short_result}")
            long_short_result = None
        if isinstance(trades_result, Exception):
            self.logger.warning(f"{symbol}: 成交明细采集出错: {trades_result}")
            trades_result = None
        if isinstance(mark_price_result, Exception):
            self.logger.warning(f"{symbol}: 标记价格采集出错: {mark_price_result}")
            mark_price_result = None
        if isinstance(index_price_result, Exception):
            self.logger.warning(f"{symbol}: 指数价格采集出错: {index_price_result}")
            index_price_result = None
        if isinstance(liquidation_result, Exception):
            self.logger.warning(f"{symbol}: 强平订单采集出错: {liquidation_result}")
            liquidation_result = None
        
        orderbook = orderbook_result if isinstance(orderbook_result, dict) else None
        if orderbook:
            bids = orderbook.get('bids', [])
            asks = orderbook.get('asks', [])
            bid_volume = sum(float(bid[1]) for bid in bids if len(bid) >= 2)
            ask_volume = sum(float(ask[1]) for ask in asks if len(ask) >= 2)
            depth_levels = min(5, len(bids), len(asks))
            near_bid_volume = sum(float(bids[i][1]) for i in range(depth_levels)) if depth_levels > 0 else bid_volume
            near_ask_volume = sum(float(asks[i][1]) for i in range(depth_levels)) if depth_levels > 0 else ask_volume
            bid_ask_ratio = bid_volume / ask_volume if ask_volume > 0 else 1.0
            imbalance = (bid_volume - ask_volume) / (bid_volume + ask_volume) if (bid_volume + ask_volume) > 0 else 0
            orderbook_data = {
                'bids': bids,
                'asks': asks,
                'spread': orderbook.get('spread', 0),
                'bid_volume': bid_volume,
                'ask_volume': ask_volume,
                'bid_ask_ratio': bid_ask_ratio,
                'imbalance': imbalance,
                'near_bid_volume': near_bid_volume,
                'near_ask_volume': near_ask_volume,
                'top_depth_levels': depth_levels
            }
        
        if isinstance(funding_result, dict):
            funding_data = funding_result
        if isinstance(oi_result, dict):
            open_interest_data = oi_result
        if isinstance(taker_volume_result, dict):
            taker_volume_data = taker_volume_result
        if isinstance(long_short_result, dict):
            long_short_ratio_data = long_short_result
        if isinstance(trades_result, list):
            recent_trades = trades_result
        
        impact_metrics: Dict[str, Any] = {}
        block_trades_summary: Dict[str, Any] = {}
        basis_data: Dict[str, Any] = {}
        liquidation_data: Dict[str, Any] = {}
        
        if recent_trades:
            buy_notional = sum(trade['notional'] for trade in recent_trades if trade.get('side') == 'buy')
            sell_notional = sum(trade['notional'] for trade in recent_trades if trade.get('side') == 'sell')
            total_notional = buy_notional + sell_notional
            buy_volume = sum(trade['size'] for trade in recent_trades if trade.get('side') == 'buy')
            sell_volume = sum(trade['size'] for trade in recent_trades if trade.get('side') == 'sell')
            timestamps = [trade['ts'] for trade in recent_trades if trade.get('ts')]
            if timestamps:
                span_ms = max(timestamps) - min(timestamps) if len(timestamps) > 1 else 1000
            else:
                span_ms = 1000
            trades_per_sec = len(recent_trades) / max(span_ms / 1000, 1)
            avg_trade_size = (buy_volume + sell_volume) / len(recent_trades)
            orderflow_metrics = {
                'taker_buy_notional': buy_notional,
                'taker_sell_notional': sell_notional,
                'taker_buy_ratio': buy_notional / total_notional if total_notional > 0 else None,
                'net_flow': buy_notional - sell_notional,
                'buy_volume': buy_volume,
                'sell_volume': sell_volume,
                'avg_trade_size': avg_trade_size,
                'trades_per_sec': trades_per_sec,
                'sample_size': len(recent_trades),
                'latest_trade': recent_trades[0] if recent_trades else None
            }
            if not taker_volume_data:
                taker_volume_data = {
                    'symbol': symbol,
                    'period': 'recent_trades',
                    'buy_vol': buy_volume,
                    'sell_vol': sell_volume,
                    'taker_buy_ratio': orderflow_metrics['taker_buy_ratio'],
                    'timestamp': recent_trades[0].get('ts') if recent_trades else None
                }
            block_threshold = float(self.orderflow_analysis_cfg.get('block_trade_notional', 80000) or 0)
            block_window = int(self.orderflow_analysis_cfg.get('block_trade_window_sec', 180) or 0)
            block_trades_summary = self._summarize_block_trades(recent_trades, block_threshold, block_window)
            if block_trades_summary:
                orderflow_metrics['block_trades'] = block_trades_summary
        
        mid_price = float(ticker.get('price', 0) or 0)
        impact_notional = float(self.orderflow_analysis_cfg.get('impact_notional', 50000) or 0)
        if orderbook_data and impact_notional > 0 and mid_price > 0:
            impact_metrics = self._calculate_market_impact(orderbook_data, impact_notional, mid_price)
        
        mark_price = None
        if isinstance(mark_price_result, dict) and mark_price_result:
            mark_price = float(mark_price_result.get('mark_price', 0) or 0)
        index_price = None
        if isinstance(index_price_result, dict) and index_price_result:
            index_price = float(index_price_result.get('index_price', 0) or 0)
        if (mark_price and mark_price > 0) or (index_price and index_price > 0):
            spot_basis_pct = ((mid_price - index_price) / index_price) if index_price and index_price > 0 else None
            mark_basis_pct = ((mark_price - index_price) / index_price) if index_price and index_price > 0 and mark_price else None
            premium_pct = ((mid_price - mark_price) / mark_price) if mark_price else None
            basis_data = {
                'mark_price': mark_price,
                'index_price': index_price,
                'spot_basis_pct': spot_basis_pct,
                'mark_basis_pct': mark_basis_pct,
                'premium_pct': premium_pct,
                'timestamp': (mark_price_result or {}).get('timestamp') or (index_price_result or {}).get('timestamp')
            }
            current_rate = funding_data.get('current_rate') if isinstance(funding_data, dict) else None
            if current_rate is not None:
                try:
                    annualized = float(current_rate) * 3 * 365  # 8小时=3次/天
                    basis_data['funding_annualized_pct'] = annualized
                except (TypeError, ValueError):
                    pass
        
        if isinstance(liquidation_result, dict):
            liquidation_data = liquidation_result
        
        macro_risk = self._evaluate_macro_risk(symbol)
        
        kline = kline_15m
        indicators_dict: Dict[str, Any] = {}
        df = None
        if kline and isinstance(kline, list) and len(kline) > 0:
            try:
                df = self.data_processor.calculate_indicators(kline)
                if df is not None and not df.empty:
                    indicators_dict = df.iloc[-1].to_dict()
            except Exception as e:
                self.logger.error(f"计算{symbol}技术指标失败: {e}", exc_info=True)
                indicators_dict = {}
        
        if indicators_dict:
            def _fmt(value, fmt_str="{:.2f}"):
                return fmt_str.format(value) if isinstance(value, (int, float)) else str(value)
            self.logger.info(
                f"[指标汇总] 交易对: {symbol} | "
                f"价格: {ticker.get('price', 0)} | "
                f"24h涨跌: {ticker.get('change_24h', 0):.2f}% | "
                f"RSI: {_fmt(indicators_dict.get('rsi'), '{:.2f}')} | "
                f"MACD: {_fmt(indicators_dict.get('macd'), '{:.4f}')} | "
                f"MACD_Hist: {_fmt(indicators_dict.get('macd_hist'), '{:.4f}')} | "
                f"BB_Upper: {_fmt(indicators_dict.get('bb_upper'), '{:.2f}')} | "
                f"BB_Lower: {_fmt(indicators_dict.get('bb_lower'), '{:.2f}')}"
            )
            self.logger.debug(f"[指标完整数据] 交易对: {symbol} - {indicators_dict}")
        
        detailed_indicators = indicators_dict.copy()
        if df is not None and not df.empty:
            latest = df.iloc[-1]
            detailed_indicators['close'] = float(latest.get('close', 0))
            detailed_indicators['high'] = float(latest.get('high', 0))
            detailed_indicators['low'] = float(latest.get('low', 0))
            detailed_indicators['volume'] = float(latest.get('volume', 0))
            for key in ['ma_5', 'ma_20', 'ma_60']:
                if key in latest:
                    detailed_indicators[key] = float(latest.get(key, 0))
            if 'volume_ma_5' in latest:
                detailed_indicators['volume_ma_5'] = float(latest.get('volume_ma_5', 0))
            if 'volume_ma_20' in latest:
                detailed_indicators['volume_ma_20'] = float(latest.get('volume_ma_20', 0))
            if len(df) >= 5:
                recent_5 = df.iloc[-5:]
                price_change_5 = ((recent_5['close'].iloc[-1] - recent_5['close'].iloc[0]) / recent_5['close'].iloc[0] * 100) if recent_5['close'].iloc[0] > 0 else 0
                detailed_indicators['price_change_5k'] = price_change_5
            if len(df) >= 10:
                recent_10 = df.iloc[-10:]
                price_change_10 = ((recent_10['close'].iloc[-1] - recent_10['close'].iloc[0]) / recent_10['close'].iloc[0] * 100) if recent_10['close'].iloc[0] > 0 else 0
                detailed_indicators['price_change_10k'] = price_change_10
        
        primary_taker_ratio = orderflow_metrics.get('taker_buy_ratio')
        if primary_taker_ratio is None:
            primary_taker_ratio = taker_volume_data.get('taker_buy_ratio')
        
        sentiment_label = None
        if primary_taker_ratio is not None:
            if primary_taker_ratio > 0.6:
                sentiment_label = 'strong_buy_flow'
            elif primary_taker_ratio < 0.4:
                sentiment_label = 'strong_sell_flow'
            else:
                sentiment_label = 'neutral_flow'
        
        sentiment_data = {
            'funding_rate': funding_data.get('current_rate'),
            'next_funding_rate': funding_data.get('next_rate'),
            'taker_buy_ratio': primary_taker_ratio,
            'orderbook_imbalance': orderbook_data.get('imbalance') if orderbook_data else None,
            'long_short_ratio': long_short_ratio_data.get('long_short_ratio'),
            'macro_risk': macro_risk.get('risk_level'),
            'block_trades': block_trades_summary,
            'label': sentiment_label
        }
        
        symbol_market_data = {
            'symbol': symbol,
            'price': ticker.get('price', 0),
            'change_24h': ticker.get('change_24h', 0),
            'volume_24h': ticker.get('volume_24h', 0),
            'high_24h': ticker.get('high_24h', 0),
            'low_24h': ticker.get('low_24h', 0),
            'kline_15m': kline_15m,
            'kline_1H': kline_1h,
            'kline_4H': kline_4h,
            'kline': kline,
            'indicators': detailed_indicators,
            'orderbook': orderbook_data,
            'impact': impact_metrics,
            'funding': funding_data,
            'derivatives': {
                'open_interest': open_interest_data,
                'taker_volume': taker_volume_data,
                'long_short_ratio': long_short_ratio_data,
                'liquidations': liquidation_data,
                'basis': basis_data
            },
            'orderflow': orderflow_metrics,
            'chain': {},
            'sentiment': sentiment_data,
            'macro': macro_risk,
            'pair_config': self.pair_config_map.get(symbol, {})
        }
        return symbol_market_data
    
    def _calculate_market_impact(self, orderbook: Dict[str, Any], target_notional: float, mid_price: float) -> Dict[str, Any]:
        """估算吃掉指定名义金额时的冲击成本"""
        def _calc(levels: List[List[float]], direction: str) -> Dict[str, Any]:
            remaining = target_notional
            total_notional = 0.0
            total_qty = 0.0
            worst_price = mid_price
            for level in levels:
                if len(level) < 2:
                    continue
                price = float(level[0])
                size = abs(float(level[1]))
                level_notional = price * size
                if level_notional <= 0:
                    continue
                take = min(level_notional, remaining)
                if take <= 0:
                    break
                worst_price = price
                total_notional += take
                total_qty += take / price if price > 0 else 0
                remaining -= take
                if remaining <= 0:
                    break
            filled_ratio = total_notional / target_notional if target_notional > 0 else 0
            impact_pct = None
            if total_notional > 0 and mid_price > 0:
                move_pct = (worst_price - mid_price) / mid_price
                impact_pct = move_pct if direction == 'buy' else -move_pct
            return {
                'filled_ratio': filled_ratio,
                'worst_price': worst_price if total_notional > 0 else None,
                'avg_price': (total_notional / total_qty) if total_qty > 0 else None,
                'impact_pct': impact_pct
            }
        
        bids = orderbook.get('bids', []) if orderbook else []
        asks = orderbook.get('asks', []) if orderbook else []
        return {
            'impact_notional': target_notional,
            'buy': _calc(asks, 'buy'),
            'sell': _calc(bids, 'sell')
        }
    
    def _summarize_block_trades(self, trades: List[Dict[str, Any]], threshold: float, window_sec: int) -> Dict[str, Any]:
        """统计大额成交簇"""
        if not trades or threshold <= 0:
            return {}
        block_trades = [trade for trade in trades if trade.get('notional', 0) >= threshold]
        if not block_trades:
            return {}
        sorted_blocks = sorted(block_trades, key=lambda t: t.get('ts', 0) or 0, reverse=True)
        latest_ts = sorted_blocks[0].get('ts')
        window_ms = window_sec * 1000 if window_sec else None
        if window_ms and latest_ts:
            window_blocks = [
                trade for trade in sorted_blocks
                if trade.get('ts') and (latest_ts - trade['ts']) <= window_ms
            ]
        else:
            window_blocks = sorted_blocks
        buy_count = sum(1 for trade in window_blocks if trade.get('side') == 'buy')
        sell_count = sum(1 for trade in window_blocks if trade.get('side') == 'sell')
        net_notional = 0.0
        for trade in window_blocks:
            notional = trade.get('notional', 0.0)
            if trade.get('side') == 'buy':
                net_notional += notional
            elif trade.get('side') == 'sell':
                net_notional -= notional
        latest_trade = sorted_blocks[0]
        bias = 'buy' if net_notional > 0 else 'sell' if net_notional < 0 else 'neutral'
        return {
            'count': len(window_blocks),
            'buy_count': buy_count,
            'sell_count': sell_count,
            'net_notional': net_notional,
            'last_trade': latest_trade,
            'bias': bias,
            'threshold': threshold
        }
    
    def _parse_iso_datetime(self, value: Optional[Any]) -> Optional[datetime]:
        """解析ISO或毫秒时间戳"""
        if value is None:
            return None
        if isinstance(value, (int, float)):
            try:
                return datetime.fromtimestamp(float(value) / 1000.0, tz=timezone.utc)
            except (TypeError, ValueError, OSError):
                return None
        if isinstance(value, str):
            try:
                if value.endswith('Z'):
                    value = value.replace('Z', '+00:00')
                parsed = datetime.fromisoformat(value)
                if parsed.tzinfo is None:
                    parsed = parsed.replace(tzinfo=timezone.utc)
                return parsed.astimezone(timezone.utc)
            except ValueError:
                return None
        return None
    
    def _evaluate_macro_risk(self, symbol: str) -> Dict[str, Any]:
        """基于配置计算当前宏观风险"""
        macro_cfg = self.macro_events_cfg or self.config_mgr.get_config('risk', 'macro_events', {})
        if not macro_cfg or not macro_cfg.get('enabled', True):
            return {'risk_level': 'normal', 'active_events': []}
        now = datetime.now(timezone.utc)
        events = macro_cfg.get('events', []) or []
        risk_levels = macro_cfg.get('risk_levels', {}) or {}
        default_level = macro_cfg.get('default_level', 'normal')
        highest_level = default_level
        active_events: List[Dict[str, Any]] = []
        cumulative_score = risk_levels.get(default_level, 0.0)
        
        for event in events:
            start = self._parse_iso_datetime(event.get('start'))
            end = self._parse_iso_datetime(event.get('end'))
            if start and now < start:
                continue
            if end and now > end:
                continue
            symbols = event.get('symbols')
            if symbols and symbol not in symbols:
                continue
            level = (event.get('level') or 'medium').lower()
            active_events.append({
                'name': event.get('name'),
                'level': level,
                'note': event.get('note'),
                'start': event.get('start'),
                'end': event.get('end')
            })
            cumulative_score += risk_levels.get(level, 0.0)
            if risk_levels.get(level, 0.0) >= risk_levels.get(highest_level, 0.0):
                highest_level = level
        
        return {
            'risk_level': highest_level,
            'score': cumulative_score,
            'active_events': active_events,
            'evaluated_at': now.isoformat()
        }
    
    async def _generate_signals(self, market_data: Dict[str, Dict[str, Any]]) -> List:
        """
        生成信号
        
        Args:
            market_data: 市场数据
            
        Returns:
            信号列表
        """
        all_signals = []
        
        for symbol, data in market_data.items():
            try:
                # 生成信号
                signals = self.signal_generator.generate_signals(symbol, data)
                
                # 更新信号历史（用于过滤）
                for signal in signals:
                    self.signal_filter.update_signal_history(signal)
                
                all_signals.extend(signals)
            
            except Exception as e:
                self.logger.error(f"生成{symbol}信号失败: {e}")
        
        return all_signals
    
    async def _make_decisions(self, market_data: Dict[str, Dict[str, Any]],
                            signals: List) -> List:
        """
        生成交易决策
        
        Args:
            market_data: 市场数据
            signals: 信号列表
            
        Returns:
            决策列表
        """
        decisions = []
        
        # 按交易对分组信号
        signals_by_symbol = {}
        for signal in signals:
            symbol = signal.symbol
            if symbol not in signals_by_symbol:
                signals_by_symbol[symbol] = []
            signals_by_symbol[symbol].append(signal)
        
        # 获取当前持仓
        positions = self.position_manager.get_all_positions()
        
        for symbol, symbol_signals in signals_by_symbol.items():
            try:
                # 获取当前持仓
                current_position = positions.get(symbol)
                
                # 获取市场数据
                symbol_market_data = market_data.get(symbol, {})
                
                # 生成决策
                decision = self.decision_engine.make_decision(
                    symbol, symbol_market_data, current_position
                )
                
                if decision:
                    decisions.append(decision)
            
            except Exception as e:
                self.logger.error(f"生成{symbol}决策失败: {e}")
        
        return decisions
    
    async def _execute_trades(self, decisions: List):
        """
        执行交易
        
        Args:
            decisions: 决策列表
        """
        if not self.trading_enabled:
            self.logger.info("交易已禁用，跳过执行")
            return
        
        for decision in decisions:
            try:
                symbol = decision.symbol
                
                # 检查是否为DeepSeek决策（必须严格执行）
                # 优先检查decision对象上的标记
                is_deepseek_decision = getattr(decision, '_is_deepseek_decision', False)
                
                # 如果没有标记，检查signals中的direction字段
                if not is_deepseek_decision and decision.signals:
                    for signal_data in decision.signals:
                        if signal_data.get('source') == 'ai':
                            # 检查是否有direction字段
                            analysis = signal_data.get('data', {}).get('analysis', {})
                            if not analysis:
                                analysis = signal_data.get('data', {})
                            
                            if analysis.get('direction') in ['long', 'short', 'hold']:
                                is_deepseek_decision = True
                                break
                
                # 如果是DeepSeek决策，跳过所有检查，直接执行
                if is_deepseek_decision:
                    self.logger.info(
                        f"🎯 [严格执行DeepSeek决策] {symbol}: "
                        f"这是DeepSeek的决策，跳过所有检查，直接执行"
                    )
                else:
                    # 非DeepSeek决策，进行常规检查
                    # 检查是否应该执行
                    if not self.decision_engine.should_execute_decision(decision):
                        self.logger.info(f"{symbol}: 决策不满足执行条件，跳过")
                        continue
                    
                    # 检查信心度
                    if decision.confidence < self.min_confidence:
                        self.logger.info(
                            f"{symbol}: 信心度{decision.confidence:.2f}低于阈值{self.min_confidence}，跳过执行"
                        )
                        continue
                    
                    # 检查仓位大小
                    if decision.position_size < self.min_position_size:
                        self.logger.info(
                            f"{symbol}: 仓位大小{decision.position_size:.2%}低于阈值{self.min_position_size:.2%}，跳过执行"
                        )
                        continue
                    
                    # 风险检查（平仓操作跳过风险检查，因为平仓是保护性操作，不会增加风险）
                    is_closing = self._is_closing_position(symbol, decision.action)
                    self.logger.info(f"🔍 [风险检查判断] {symbol}: action={decision.action}, is_closing={is_closing}")
                    
                    position_size = decision.position_size
                    market_data = {'price': decision.price or 0, 'volatility': 0.25}
                    
                    if not self.risk_manager.check_risk_before_trade(symbol, position_size, market_data, is_closing=is_closing):
                        self.logger.warning(f"{symbol}: 风险检查未通过，拒绝交易")
                        continue
                
                # 记录准备执行的决策
                action_desc = {
                    'long': '做多',
                    'short': '做空',
                    'close_long': '平多',
                    'close_short': '平空',
                    'buy': '买入',
                    'sell': '卖出'
                }.get(decision.action, decision.action)
                
                if is_deepseek_decision:
                    self.logger.info(
                        f"🎯 [准备执行DeepSeek决策] {symbol}: {action_desc}({decision.position_side}) | "
                        f"仓位: {decision.position_size:.2%} | "
                        f"信心度: {decision.confidence:.2f} | "
                        f"开仓限价: {decision.price if decision.price else '市价'} | "
                        f"平仓限价: {decision.take_profit if decision.take_profit else 'N/A'} | "
                        f"严格执行DeepSeek的决策"
                    )
                else:
                    self.logger.info(
                        f"[准备执行交易] {symbol}: {action_desc}({decision.position_side}) | "
                        f"仓位: {decision.position_size:.2%} | "
                        f"信心度: {decision.confidence:.2f} | "
                        f"价格: {decision.price if decision.price else '市价'}"
                    )
                
                # 获取市场数据和AI分析结果（用于记录）
                symbol_market_data = self.market_data_cache.get(symbol, {})
                
                # 获取AI分析结果（从决策中提取）
                ai_analysis = getattr(decision, 'ai_analysis', None) or {}
                
                # 🔍 检查是否有待成交的委托订单，避免重复创建（只检查开仓订单）
                if not self._is_closing_position(symbol, decision.action):
                    existing_pending = self.pending_orders.get(symbol)
                    if existing_pending:
                        existing_order = existing_pending.get('order')
                        existing_decision = existing_pending.get('decision')
                        
                        if existing_order and existing_order.status.value in ['submitted', 'partial_filled']:
                            # 比较新决策和已有委托的差异
                            is_similar = self._is_decision_similar(decision, existing_decision, existing_order)
                            
                            if is_similar:
                                self.logger.info(
                                    f"🔍 {symbol}: 已有相似委托订单，跳过创建新委托 | "
                                    f"现有订单ID={existing_order.order_id}, "
                                    f"价格={existing_order.price:.5f if existing_order.price else '市价'}, "
                                    f"新决策价格={decision.price:.5f if decision.price else '市价'}"
                                )
                                continue  # 跳过，不创建新委托
                            else:
                                # 决策有差异，取消旧委托，创建新委托
                                self.logger.info(
                                    f"🔄 {symbol}: 新分析与之前有差异，取消旧委托并创建新委托 | "
                                    f"旧订单ID={existing_order.order_id}, "
                                    f"旧价格={existing_order.price:.5f if existing_order.price else '市价'}, "
                                    f"新价格={decision.price:.5f if decision.price else '市价'}"
                                )
                                try:
                                    # 取消旧委托
                                    if existing_order.order_id and existing_order.order_id.isdigit():
                                        await asyncio.to_thread(
                                            self.execution_engine.order_manager.cancel_order,
                                            existing_order
                                        )
                                        self.logger.info(f"✅ {symbol}: 已取消旧委托订单 {existing_order.order_id}")
                                except Exception as e:
                                    self.logger.warning(f"取消旧委托订单失败 {symbol}: {e}")
                                # 删除记录
                                del self.pending_orders[symbol]
                
                # 记录交易决策（开仓时）
                if not self._is_closing_position(symbol, decision.action):
                    strategy_context = self._build_strategy_context(decision, ai_analysis, symbol_market_data)
                    session_tag = self._derive_session_tag()
                    volatility_regime = self._derive_volatility_regime(symbol_market_data)
                    # 这是开仓，记录决策
                    record_id = self.result_recorder.record_trade_decision(
                        symbol=symbol,
                        decision={
                            'action': decision.action,
                            'position_size': decision.position_size,
                            'entry_price': decision.price or symbol_market_data.get('price', 0),
                            'confidence': decision.confidence,
                        },
                        ai_analysis=ai_analysis,
                        market_data=symbol_market_data,
                        strategy_context=strategy_context,
                        session_tag=session_tag,
                        volatility_regime=volatility_regime
                    )
                    # 将record_id保存到决策中，以便平仓时使用
                    decision._record_id = record_id
                    self.logger.info(f"[自学习] 记录开仓决策，记录ID: {record_id}")
                
                # 执行交易
                order = await self.execution_engine.execute_decision(decision)
                
                if order:
                    self.logger.info(f"{symbol}: 交易执行成功，订单ID: {order.order_id}")
                    
                    # 如果是限价单且未成交，记录为待成交委托
                    if order.order_type == 'limit' and order.status.value in ['submitted', 'partial_filled']:
                        self.pending_orders[symbol] = {
                            'order': order,
                            'decision': decision,
                            'create_time': datetime.now()  # 记录挂单时间
                        }
                        self.logger.info(
                            f"📝 {symbol}: 记录待成交委托订单 | "
                            f"订单ID={order.order_id}, "
                            f"价格={order.price:.5f if order.price else 'N/A'}, "
                            f"状态={order.status.value} | "
                            f"挂单时间={datetime.now().strftime('%Y-%m-%d %H:%M:%S')} | "
                            f"将在15分钟后检查是否撤销"
                        )
                    
                    # 更新持仓
                    if order.status.value == 'filled':
                        # 订单已成交，清除待成交记录
                        if symbol in self.pending_orders:
                            del self.pending_orders[symbol]
                            self.logger.debug(f"✅ {symbol}: 订单已成交，清除待成交记录")
                        
                        self.position_manager.update_position_from_order(order)
                        
                        fill_price = order.average_price or order.filled_price or decision.price or symbol_market_data.get('price', 0)
                        fill_time = order.executed_at or datetime.now()
                        
                        # 记录开仓时间（如果是开仓订单）
                        if not self._is_closing_position(symbol, decision.action):
                            # 只有开仓时才更新决策引擎的交易时间（用于15分钟间隔检查）
                            # 平仓后不受限制，可以随时开仓
                            self.decision_engine.trade_stats['last_trade_time'] = datetime.now()
                            self.logger.debug(
                                f"⏰ [更新交易时间] {symbol}: "
                                f"上次开仓时间={datetime.now().strftime('%Y-%m-%d %H:%M:%S')}, "
                                f"下次可在15分钟后生成新决策"
                            )
                            self.position_entry_times[symbol] = {
                                'entry_time': fill_time,
                                'position_side': decision.position_side,
                                'size': order.filled_size,
                                'order_id': order.order_id
                            }
                            # 记录用于后续结果写入的关键信息
                            record_id = getattr(decision, '_record_id', None)
                            if record_id:
                                self.active_trade_records[symbol] = {
                                    'record_id': record_id,
                                    'entry_price': fill_price,
                                    'entry_time': fill_time,
                                    'position_side': decision.position_side,
                                    'position_size': order.filled_size,
                                    'entry_reason': decision.reasoning or 'open',
                                    'ai_analysis': ai_analysis
                                }
                            self.logger.info(
                                f"📌 [记录开仓时间] {symbol}: {decision.position_side} | "
                                f"开仓时间={fill_time.strftime('%Y-%m-%d %H:%M:%S')} | "
                                f"将在15分钟后检查是否强制平仓"
                            )
                            
                            # 记录开仓信息到交易日志
                            self._write_trade_log_entry(symbol, decision, order, fill_price, fill_time)
                        else:
                            # 这是平仓订单，清除开仓时间记录
                            # 注意：平仓时不更新 last_trade_time，所以平仓后可以随时开仓
                            if symbol in self.position_entry_times:
                                entry_time = self.position_entry_times[symbol].get('entry_time')
                                hold_duration = (fill_time - entry_time).total_seconds() / 60 if entry_time else 0
                                del self.position_entry_times[symbol]
                                self.logger.info(
                                    f"✅ [平仓清除时间记录] {symbol}: 持仓时长={hold_duration:.2f}分钟 | "
                                    f"平仓后不受交易频率限制，可以随时开仓"
                                )
                        
                        # 计算收益（如果是平仓）
                        if self._is_closing_position(symbol, decision.action):
                            trade_info = self.active_trade_records.pop(symbol, None) or {}
                            trade_info.update({
                                'exit_price': fill_price,
                                'exit_time': fill_time,
                                'exit_reason': decision.reasoning or decision.action,
                                'order': order,
                                'position_side': decision.position_side
                            })
                            await self._calculate_profit(order, trade_info)
                            
                            # 平仓成功后，等待1分钟后生成下一次交易决策
                            self.logger.info(
                                f"🔄 [平仓后延迟决策] {symbol}: 平仓成功，等待1分钟后生成下一次交易决策（跳过交易频率限制）"
                            )
                            
                            # 等待一小段时间确保平仓订单完全成交
                            await asyncio.sleep(2)
                            
                            # 等待1分钟后再生成下一次交易决策
                            await asyncio.sleep(60)
                            
                            self.logger.info(
                                f"⏰ [延迟决策触发] {symbol}: 1分钟等待完成，开始生成新的交易决策"
                            )
                            
                            # 生成下一次交易决策
                            try:
                                # 临时保存并清除 last_trade_time，以跳过交易频率限制
                                saved_last_trade_time = self.decision_engine.trade_stats.get('last_trade_time')
                                self.decision_engine.trade_stats['last_trade_time'] = None
                                
                                try:
                                    # 获取最新市场数据
                                    latest_market_data = await self._collect_market_data()
                                    self._update_market_data_cache(latest_market_data)
                                    symbol_market_data = latest_market_data.get(symbol, {})
                                    
                                    if symbol_market_data:
                                        # 生成信号
                                        all_signals = await self._generate_signals({symbol: symbol_market_data})
                                        
                                        # 过滤信号
                                        filtered_signals = self.signal_filter.filter_signals(all_signals)
                                        
                                        # 生成决策（此时不会受到交易频率限制）
                                        new_decisions = await self._make_decisions(
                                            {symbol: symbol_market_data},
                                            filtered_signals
                                        )
                                        
                                        if new_decisions:
                                            self.logger.info(
                                                f"✅ [平仓后延迟决策] {symbol}: 已生成新的交易计划，准备执行"
                                            )
                                            # 执行新决策（异步执行，不阻塞）
                                            asyncio.create_task(self._execute_trades(new_decisions))
                                        else:
                                            self.logger.info(
                                                f"ℹ️ [平仓后延迟决策] {symbol}: 未生成新的交易计划，保持观望"
                                            )
                                finally:
                                    # 恢复 last_trade_time（如果之前有值）
                                    if saved_last_trade_time:
                                        self.decision_engine.trade_stats['last_trade_time'] = saved_last_trade_time
                            except Exception as e:
                                self.logger.error(f"平仓后立即生成决策失败 {symbol}: {e}")
                
                # 避免频繁交易
                await asyncio.sleep(1)
            
            except Exception as e:
                self.logger.error(f"执行交易失败 {decision.symbol}: {e}")
    
    async def _check_position_adjustments(self, market_data: Dict[str, Dict[str, Any]],
                                          enable_ai_analysis: bool = True,
                                          max_adjustments: Optional[int] = None,
                                          source: str = "default"):
        """
        检查并执行AI仓位调整和智能平仓（包含快速止损止盈检查）
        
        Args:
            market_data: 市场数据
            enable_ai_analysis: 是否调用AI分析模块
            max_adjustments: 单次检查允许执行的最大非风险调整次数
            source: 日志标记，用于识别触发来源
        """
        try:
            adjustments_executed = 0
            max_adjustments = max_adjustments if max_adjustments and max_adjustments > 0 else None
            source_tag = f"@{source}" if source and source != "default" else ""
            
            # ⚠️ 首先从API实时获取最新持仓数据（确保数据准确）
            try:
                if self.okx_client is None:
                    self.okx_client = await get_okx_client()
                positions_result = await self.okx_client.async_get_positions()
                
                # 处理不同的返回格式
                if isinstance(positions_result, dict):
                    if positions_result.get('code') != '0':
                        return
                    positions_list = positions_result.get('data', [])
                elif isinstance(positions_result, list):
                    positions_list = positions_result
                else:
                    positions_list = []
            except Exception as e:
                self.logger.warning(f"获取实时持仓失败，使用缓存: {e}")
                # 如果API失败，使用缓存的持仓数据
                positions = self.position_manager.get_all_positions()
                positions_list = []
                for sym, pos in positions.items():
                    positions_list.append({
                        'instId': sym,
                        'pos': str(pos.get('size', 0)) if pos.get('side') == 'long' else str(-pos.get('size', 0)),
                        'posSide': 'long' if pos.get('side') == 'long' else 'short',
                        'avgPx': str(pos.get('avg_price', 0) or pos.get('average_price', 0)),
                        'markPx': str(market_data.get(sym, {}).get('price', 0))
                    })
            
            if not positions_list:
                return
            
            # 遍历每个持仓（从API获取的真实数据）
            for pos_data in positions_list:
                try:
                    if not isinstance(pos_data, dict):
                        continue
                    
                    symbol = pos_data.get('instId', '')
                    if not symbol:
                        continue
                    
                    pos_str = pos_data.get('pos', '0')
                    position_size = abs(float(pos_str)) if pos_str else 0
                    if position_size <= 0:
                        continue
                    
                    # 获取该交易对的市场数据
                    symbol_market_data = market_data.get(symbol, {})
                    if not symbol_market_data:
                        # 如果没有市场数据，尝试从ticker获取价格（异步）
                        try:
                            ticker = await self.data_collector.collect_ticker(symbol)
                            if ticker:
                                symbol_market_data = {
                                    'symbol': symbol,
                                    'price': ticker.get('price', 0)
                                }
                        except Exception:
                            continue
                    
                    if not symbol_market_data:
                        continue
                    
                    # 从API数据构建position对象（使用真实的开仓均价）
                    # 获取 posSide（从 API 原始数据中获取）
                    pos_side_from_api = pos_data.get('posSide', 'net')
                    
                    position = {
                        'symbol': symbol,
                        'size': position_size,
                        'side': 'long' if float(pos_str) > 0 else 'short',
                        'avg_price': float(pos_data.get('avgPx', '0')) if pos_data.get('avgPx') else 0,
                        'average_price': float(pos_data.get('avgPx', '0')) if pos_data.get('avgPx') else 0,
                        'mark_price': float(pos_data.get('markPx', '0')) if pos_data.get('markPx') else 0,
                        'posSide': pos_side_from_api  # 保存 posSide 字段，用于平仓时使用
                    }
                    
                    # AI分析是否应该调整仓位
                    adjustment = self.ai_position_manager.should_adjust_position(
                        symbol, position, symbol_market_data,
                        enable_ai=enable_ai_analysis
                    )
                    
                    if adjustment:
                        action = adjustment.get('action')
                        adjust_size = adjustment.get('adjust_size', 0.0)
                        reason = adjustment.get('reason', '')
                        is_risk_event = any(
                            adjustment.get(flag)
                            for flag in ['stop_loss_triggered', 'take_profit_triggered', 'wolf_strategy']
                        )
                        
                        if max_adjustments and not is_risk_event and adjustments_executed >= max_adjustments:
                            self.logger.info(
                                f"[AI仓位调整{source_tag}] {symbol}: "
                                f"已达到本轮最大调整次数{max_adjustments}，跳过{action}"
                            )
                            continue
                        
                        adjust_size_str = (
                            f"{float(adjust_size):.2%}" if isinstance(adjust_size, (int, float)) else str(adjust_size)
                        )
                        
                        # 如果是平仓建议，使用更醒目的日志
                        if action == 'close':
                            self.logger.warning(
                                f"🚨 [AI建议平仓{source_tag}] {symbol}: AI分析建议立即平仓！"
                                f"原因: {reason} | 调整比例: {adjust_size_str}"
                            )
                        else:
                            self.logger.info(
                                f"[AI仓位调整{source_tag}] {symbol}: 建议{action}, "
                                f"调整比例: {adjust_size_str}, "
                                f"原因: {reason}"
                            )
                        
                        # 生成调整决策
                        if action == 'close':
                            trigger_price = adjustment.get('stop_loss_price') or adjustment.get('take_profit_price') \
                                or symbol_market_data.get('price', 0)
                            decision = await self._create_close_decision(
                                symbol, position, reason or 'AI建议平仓', symbol_market_data, trigger_price
                            )
                            if decision:
                                self.logger.warning(
                                    f"⚡ [立即执行AI平仓] {symbol}: 正在执行AI建议的平仓操作..."
                                )
                        else:
                            decision = await self._create_adjustment_decision(
                                symbol, position, adjustment, symbol_market_data
                            )
                        
                        if decision:
                            # 执行调整（如果是平仓，立即执行，不等待）
                            await self._execute_trades([decision])
                            if action == 'close':
                                self.logger.warning(
                                    f"✅ [AI平仓执行完成] {symbol}: AI建议的平仓操作已执行"
                                )
                            
                            if max_adjustments and not is_risk_event:
                                adjustments_executed += 1
                            
                            # 已执行调整，无需重复执行后续检查
                            continue
                    
                    # 获取当前价格（优先使用API的标记价格，其次使用市场数据）
                    current_price = position.get('mark_price', 0) or symbol_market_data.get('price', 0)
                    
                    # 兼容不同的持仓方向格式
                    position_side_raw = position.get('side', 'long')
                    if position_side_raw == 'buy':
                        position_side = 'long'
                    elif position_side_raw == 'sell':
                        position_side = 'short'
                    else:
                        position_side = position_side_raw
                    
                    # ⚠️ 计算盈亏百分比（用于快速止损止盈）- 必须优先检查！
                    # 直接从API数据获取开仓均价（确保准确性）
                    entry_price = position.get('avg_price', 0) or position.get('average_price', 0) or float(pos_data.get('avgPx', '0') if pos_data.get('avgPx') else 0)
                    
                    # 记录详细的持仓信息日志
                    self.logger.info(
                        f"📊 [持仓数据] {symbol}: {position_side} | "
                        f"API开仓价={pos_data.get('avgPx', 'N/A')}, "
                        f"API标记价={pos_data.get('markPx', 'N/A')}, "
                        f"持仓量={position_size:.4f}, "
                        f"解析后开仓价={entry_price:.5f}, "
                        f"解析后当前价={current_price:.5f}"
                    )
                    
                    if entry_price > 0 and current_price > 0:
                        # 计算价格变动百分比
                        if position_side == 'long':
                            # 做多：价格涨就盈利，价格跌就亏损
                            price_change_pct = ((current_price - entry_price) / entry_price) * 100
                        else:  # short
                            # 做空：价格跌就盈利，价格涨就亏损
                            price_change_pct = ((entry_price - current_price) / entry_price) * 100
                        
                        # 获取杠杆倍数（用于计算账户盈亏）
                        leverage = 1  # 默认1倍杠杆
                        try:
                            trading_config_pairs = self.config_mgr.get_config('trading', 'trading_pairs')
                            for pair in trading_config_pairs:
                                if pair.get('symbol') == symbol:
                                    leverage = pair.get('leverage', 1)
                                    leverage = int(leverage) if leverage else 1
                                    break
                        except Exception as e:
                            self.logger.warning(f"获取杠杆倍数失败 {symbol}: {e}，使用默认值1")
                        
                        # 计算账户盈亏百分比（考虑杠杆倍数）
                        # 账户盈亏 = 价格变动百分比 × 杠杆倍数
                        account_pnl_pct = price_change_pct * leverage
                        
                        # 强制记录盈亏日志（每次检查都记录）
                        self.logger.info(
                            f"🔍 [持仓检查] {symbol}: {position_side} | "
                            f"开仓价={entry_price:.5f}, 当前价={current_price:.5f}, "
                            f"价格变动={price_change_pct:.2f}% | "
                            f"账户盈亏={account_pnl_pct:.2f}% (杠杆{leverage}x) | "
                            f"持仓量={position_size:.4f}"
                        )
                        
                        # 获取快速止损止盈配置（账户盈亏百分比）
                        trading_config = self.config_mgr.get_config('trading', 'auto_trading', {})
                        risk_limits_cfg = self.config_mgr.get_config('risk', 'risk_limits', {}) or {}
                        max_loss_per_trade = risk_limits_cfg.get('max_loss_per_trade')
                        quick_stop_loss_ratio = trading_config.get('quick_stop_loss', max_loss_per_trade or 0.02)
                        if max_loss_per_trade:
                            quick_stop_loss_ratio = max_loss_per_trade
                        quick_profit_target_ratio = trading_config.get('quick_profit_target')
                        if quick_profit_target_ratio is None:
                            quick_profit_target_ratio = quick_stop_loss_ratio * 2
                        if quick_profit_target_ratio < quick_stop_loss_ratio * 1.5:
                            quick_profit_target_ratio = quick_stop_loss_ratio * 2
                        quick_profit_target = quick_profit_target_ratio * 100
                        quick_stop_loss = quick_stop_loss_ratio * 100
                        
                        # ⚠️ 优先检查快速止损（保护资金）- 这是最重要的检查！
                        # 使用账户盈亏百分比进行比较
                        if account_pnl_pct <= -quick_stop_loss:
                            self.logger.error(
                                f"🚨 [快速止损触发] {symbol}: {position_side} | "
                                f"账户盈亏{account_pnl_pct:.2f}% <= 止损限制{-quick_stop_loss:.2f}% | "
                                f"价格变动={price_change_pct:.2f}% (杠杆{leverage}x) | "
                                f"开仓价={entry_price:.5f}, 当前价={current_price:.5f} | "
                                f"持仓量={position_size:.4f} | ⚠️ 立即平仓！"
                            )
                            # 生成平仓决策
                            close_decision = await self._create_close_decision(
                                symbol, position, '快速止损', symbol_market_data, current_price
                            )
                            if close_decision:
                                await self._execute_trades([close_decision])
                                continue  # 已平仓，跳过后续检查
                            else:
                                self.logger.error(f"❌ [快速止损] {symbol}: 生成平仓决策失败！")
                        
                        # 检查快速止盈（盈利超过目标）
                        elif account_pnl_pct >= quick_profit_target:
                            self.logger.info(
                                f"💰 [快速止盈触发] {symbol}: {position_side} | "
                                f"账户盈亏{account_pnl_pct:.2f}% >= 止盈目标{quick_profit_target:.2f}% | "
                                f"价格变动={price_change_pct:.2f}% (杠杆{leverage}x) | "
                                f"开仓价={entry_price:.5f}, 当前价={current_price:.5f} | "
                                f"持仓量={position_size:.4f}"
                            )
                            # 生成平仓决策
                            close_decision = await self._create_close_decision(
                                symbol, position, '快速止盈', symbol_market_data, current_price
                            )
                            if close_decision:
                                await self._execute_trades([close_decision])
                                continue  # 已平仓，跳过后续检查
                        else:
                            # 记录当前盈亏状态（即使未触发止损止盈）
                            self.logger.debug(
                                f"[持仓盈亏] {symbol}: {position_side} | "
                                f"账户盈亏={account_pnl_pct:.2f}% | "
                                f"价格变动={price_change_pct:.2f}% (杠杆{leverage}x) | "
                                f"止损阈值={-quick_stop_loss:.2f}% (账户盈亏) | "
                                f"止盈阈值={quick_profit_target:.2f}% (账户盈亏)"
                            )
                    
                    # 计算动态止损止盈价格（用于价格止损止盈检查）
                    stop_loss_price = None
                    take_profit_price = None
                    try:
                        stop_loss_price, take_profit_price = self.ai_position_manager.calculate_dynamic_stop_loss(
                            symbol, position, symbol_market_data
                        )
                    except Exception as e:
                        self.logger.debug(f"计算动态止损止盈失败 {symbol}: {e}")
                    
                    # 检查价格止损止盈（基于止损止盈价格）
                    if stop_loss_price and current_price > 0:
                        stop_loss_triggered = False
                        if position_side == 'long' and current_price <= stop_loss_price:
                            # 做多：价格下跌触发止损
                            stop_loss_triggered = True
                        elif position_side == 'short' and current_price >= stop_loss_price:
                            # 做空：价格上涨触发止损
                            stop_loss_triggered = True
                        
                        if stop_loss_triggered:
                            self.logger.warning(
                                f"[价格止损触发] {symbol}: {position_side} | "
                                f"当前价格{current_price:.4f}触发止损价格{stop_loss_price:.4f} | "
                                f"开仓价={entry_price:.4f if entry_price > 0 else 'N/A'}"
                            )
                            # 生成平仓决策
                            close_decision = await self._create_close_decision(
                                symbol, position, '价格止损', symbol_market_data, stop_loss_price
                            )
                            if close_decision:
                                await self._execute_trades([close_decision])
                                continue  # 已平仓，跳过后续检查
                    
                    if take_profit_price and current_price > 0:
                        take_profit_triggered = False
                        if position_side == 'long' and current_price >= take_profit_price:
                            # 做多：价格上涨触发止盈
                            take_profit_triggered = True
                        elif position_side == 'short' and current_price <= take_profit_price:
                            # 做空：价格下跌触发止盈
                            take_profit_triggered = True
                        
                        if take_profit_triggered:
                            self.logger.info(
                                f"[价格止盈触发] {symbol}: {position_side} | "
                                f"当前价格{current_price:.4f}触发止盈价格{take_profit_price:.4f} | "
                                f"开仓价={entry_price:.4f if entry_price > 0 else 'N/A'}"
                            )
                            # 生成平仓决策
                            close_decision = await self._create_close_decision(
                                symbol, position, '价格止盈', symbol_market_data, take_profit_price
                            )
                            if close_decision:
                                await self._execute_trades([close_decision])
                                continue  # 已平仓，跳过后续检查
                    
                except Exception as e:
                    self.logger.error(f"检查仓位调整失败 {symbol}: {e}")
            
        except Exception as e:
            self.logger.error(f"检查仓位调整失败: {e}")
    
    async def _create_adjustment_decision(self, symbol: str, position: Dict[str, Any],
                                         adjustment: Dict[str, Any],
                                         market_data: Dict[str, Any]) -> Optional[Any]:
        """
        创建仓位调整决策
        
        Args:
            symbol: 交易对符号
            position: 当前持仓
            adjustment: 调整建议
            market_data: 市场数据
        
        Returns:
            交易决策
        """
        try:
            from ..decision.decision_engine import TradingDecision
            
            action = adjustment.get('action')
            adjust_size = adjustment.get('adjust_size', 0.0)
            # 兼容不同的持仓方向格式
            position_side_raw = position.get('side', 'long')
            if position_side_raw == 'buy':
                position_side = 'long'
            elif position_side_raw == 'sell':
                position_side = 'short'
            else:
                position_side = position_side_raw
            
            if action == 'close':
                # 平仓
                if position_side == 'long':
                    decision_action = 'close_long'
                else:
                    decision_action = 'close_short'
                
                return TradingDecision(
                    symbol=symbol,
                    action=decision_action,
                    position_size=1.0,  # 全部平仓
                    position_side=position_side,
                    price=market_data.get('price'),
                    stop_loss=None,
                    take_profit=None,
                    confidence=adjustment.get('confidence', 0.8),
                    reasoning=adjustment.get('reason', 'AI建议平仓'),
                    signals=[],
                    risk_assessment={'passed': True}  # 平仓操作必须执行，跳过风险检查
                )
            elif action == 'add':
                # 加仓
                if position_side == 'long':
                    decision_action = 'long'
                else:
                    decision_action = 'short'
                
                return TradingDecision(
                    symbol=symbol,
                    action=decision_action,
                    position_size=adjust_size,
                    position_side=position_side,
                    price=market_data.get('price'),
                    stop_loss=adjustment.get('stop_loss_price'),
                    take_profit=adjustment.get('take_profit_price'),
                    confidence=adjustment.get('confidence', 0.7),
                    reasoning=adjustment.get('reason', 'AI建议加仓'),
                    signals=[],
                    risk_assessment={}
                )
            elif action == 'reduce':
                # 减仓（通过部分平仓实现）
                if position_side == 'long':
                    decision_action = 'close_long'
                else:
                    decision_action = 'close_short'
                
                return TradingDecision(
                    symbol=symbol,
                    action=decision_action,
                    position_size=adjust_size,  # 减仓比例
                    position_side=position_side,
                    price=market_data.get('price'),
                    stop_loss=adjustment.get('stop_loss_price'),
                    take_profit=adjustment.get('take_profit_price'),
                    confidence=adjustment.get('confidence', 0.7),
                    reasoning=adjustment.get('reason', 'AI建议减仓'),
                    signals=[],
                    risk_assessment={'passed': True}  # 减仓操作必须执行，跳过风险检查
                )
            
            return None
            
        except Exception as e:
            self.logger.error(f"创建仓位调整决策失败 {symbol}: {e}")
            return None
    
    async def _create_close_decision(self, symbol: str, position: Dict[str, Any],
                                    reason: str, market_data: Dict[str, Any],
                                    trigger_price: float) -> Optional[Any]:
        """
        创建平仓决策（止损/止盈）
        
        Args:
            symbol: 交易对符号
            position: 当前持仓
            reason: 平仓原因
            market_data: 市场数据
            trigger_price: 触发价格
        
        Returns:
            交易决策
        """
        try:
            from ..decision.decision_engine import TradingDecision
            
            # 兼容不同的持仓方向格式
            position_side_raw = position.get('side', 'long')
            # 检查实际持仓的 posSide（可能是 'net', 'long', 'short'）
            actual_pos_side = position.get('posSide', None)
            
            # 如果 posSide 不存在，尝试从其他字段推断
            if actual_pos_side is None:
                # 检查是否有其他字段可以推断
                if 'posSide' in position:
                    actual_pos_side = position['posSide']
                else:
                    # 默认使用 'net'（单向持仓模式）
                    actual_pos_side = 'net'
                    self.logger.warning(f"⚠️ {symbol}: 持仓数据中没有 posSide 字段，使用默认值 'net'")
            
            self.logger.info(
                f"🔍 [平仓决策] {symbol}: position数据 keys={list(position.keys())}, "
                f"side={position_side_raw}, posSide={actual_pos_side}"
            )
            
            if position_side_raw == 'buy':
                position_side = 'long'
            elif position_side_raw == 'sell':
                position_side = 'short'
            else:
                position_side = position_side_raw
            
            # 如果实际持仓是 'net' 模式，平仓时也应该使用 'net'
            # 否则使用具体的 'long' 或 'short'
            if actual_pos_side == 'net' or actual_pos_side is None or actual_pos_side == '':
                # 单向持仓模式，使用 'net'
                pos_side_for_order = 'net'
                self.logger.info(f"✅ {symbol}: 使用 'net' 模式平仓（单向持仓）")
            else:
                # 双向持仓模式，使用具体的方向
                pos_side_for_order = position_side
                self.logger.info(f"✅ {symbol}: 使用 '{pos_side_for_order}' 模式平仓（双向持仓）")
            
            if position_side == 'long':
                decision_action = 'close_long'
            else:
                decision_action = 'close_short'
            
            return TradingDecision(
                symbol=symbol,
                action=decision_action,
                position_size=1.0,  # 全部平仓
                position_side=pos_side_for_order,  # 使用正确的 posSide（可能是 'net'）
                price=trigger_price,
                stop_loss=None,
                take_profit=None,
                confidence=0.9,  # 止损止盈触发时，信心度很高
                reasoning=f'{reason}触发：触发价格{trigger_price:.2f}',
                signals=[],
                risk_assessment={'passed': True}  # 止损/止盈必须执行，跳过风险检查
            )
            
        except Exception as e:
            self.logger.error(f"创建平仓决策失败 {symbol}: {e}")
            return None
    
    def _is_closing_position(self, symbol: str, action: str) -> bool:
        """判断是否为平仓操作（支持合约交易）"""
        # 最简单直接的判断：如果 action 是 close_long 或 close_short，就是平仓
        if action in ['close_long', 'close_short']:
            self.logger.debug(f"✅ [平仓判断] {symbol}: action={action} 是平仓操作")
            return True
        
        # 其他情况需要检查当前持仓
        current_position = self.position_manager.get_position(symbol)
        
        if not current_position or current_position.get('size', 0) == 0:
            self.logger.debug(f"❌ [平仓判断] {symbol}: action={action}, 无持仓，不是平仓")
            return False
        
        current_side = current_position.get('side', 'none')
        
        # 现货交易：如果当前是多仓且操作为卖出，或当前是空仓且操作为买入，则为平仓
        if (current_side == 'buy' and action == 'sell') or \
           (current_side == 'sell' and action == 'buy'):
            self.logger.debug(f"✅ [平仓判断] {symbol}: action={action}, current_side={current_side} 是平仓操作")
            return True
        
        # 合约交易：如果当前是多仓且操作为做空，或当前是空仓且操作为做多，则为先平仓再开仓
        if (current_side == 'long' and action == 'short') or \
           (current_side == 'short' and action == 'long'):
            self.logger.debug(f"✅ [平仓判断] {symbol}: action={action}, current_side={current_side} 是平仓操作")
            return True
        
        self.logger.debug(f"❌ [平仓判断] {symbol}: action={action}, current_side={current_side} 不是平仓操作")
        return False
    
    async def _update_positions(self):
        """更新持仓"""
        try:
            # 获取OKX客户端单例
            if self.okx_client is None:
                self.okx_client = await get_okx_client()
            # 从交易所获取最新持仓（异步）
            positions_result = await self.okx_client.async_get_positions()
            
            # 处理不同的返回格式
            if isinstance(positions_result, dict):
                # 如果返回的是字典（包含code和data）
                if positions_result.get('code') != '0':
                    return
                positions_list = positions_result.get('data', [])
            elif isinstance(positions_result, list):
                # 如果直接返回列表
                positions_list = positions_result
            else:
                # 其他格式，尝试转换
                self.logger.warning(f"未知的持仓数据格式: {type(positions_result)}")
                return
            
            # 更新持仓管理器
            for pos_data in positions_list:
                try:
                    if isinstance(pos_data, dict):
                        symbol = pos_data.get('instId', '')
                        pos_str = pos_data.get('pos', '0')
                        size = abs(float(pos_str)) if pos_str else 0
                        side_str = pos_data.get('posSide', 'net')
                        
                        # 判断持仓方向
                        if pos_str and float(pos_str) > 0:
                            if side_str == 'long' or side_str == 'net':
                                side = 'long'
                            else:
                                side = 'short'
                        elif pos_str and float(pos_str) < 0:
                            side = 'short'
                            size = abs(float(pos_str))
                        else:
                            # 持仓为0，清除开仓时间记录
                            if symbol in self.position_entry_times:
                                del self.position_entry_times[symbol]
                                self.logger.debug(f"✅ {symbol}: 持仓为0，清除开仓时间记录")
                            continue
                        
                        # 获取开仓均价和标记价格
                        avg_price_str = pos_data.get('avgPx', '0')
                        avg_price = float(avg_price_str) if avg_price_str else 0
                        mark_price_str = pos_data.get('markPx', '0')
                        current_price = float(mark_price_str) if mark_price_str else 0
                        
                        if size > 0 and avg_price > 0:
                            # 更新持仓（使用开仓均价，不是当前价格！）
                            self.position_controller.update_position(
                                symbol, side, size, avg_price  # 使用开仓均价！
                            )
                            
                            # 如果持仓存在但没有开仓时间记录，初始化记录（可能是从API同步的）
                            if symbol not in self.position_entry_times:
                                # 从API同步的持仓，记录当前时间（但标记为不确定）
                                self.position_entry_times[symbol] = {
                                    'entry_time': datetime.now(),  # 使用当前时间作为近似值
                                    'position_side': side,
                                    'size': size,
                                    'synced_from_api': True  # 标记为从API同步
                                }
                                self.logger.debug(
                                    f"📌 [初始化开仓时间] {symbol}: {side} | "
                                    f"从API同步的持仓，使用当前时间作为开仓时间"
                                )
                            
                            # 记录更新日志
                            self.logger.debug(
                                f"[更新持仓] {symbol}: {side} | "
                                f"持仓量={size:.4f}, 开仓均价={avg_price:.5f}, "
                                f"标记价格={current_price:.5f}"
                            )
                except Exception as e:
                    self.logger.warning(f"更新单个持仓失败: {e}")
                    continue
        
        except Exception as e:
            self.logger.error(f"更新持仓失败: {e}")
    
    async def _check_force_close_positions(self, market_data: Dict[str, Dict[str, Any]]):
        """
        检查15分钟强制平仓：如果持仓超过15分钟未平仓，强制平仓并生成下一次计划
        
        Args:
            market_data: 市场数据
        """
        try:
            if not self.position_entry_times:
                return  # 没有持仓，无需检查
            
            current_time = datetime.now()
            positions_to_close = []
            
            # 检查每个持仓的开仓时间
            for symbol, entry_info in list(self.position_entry_times.items()):
                entry_time = entry_info.get('entry_time')
                if not entry_time:
                    continue
                
                # 计算持仓时长（秒）
                hold_duration = (current_time - entry_time).total_seconds()
                hold_duration_minutes = hold_duration / 60
                
                # 检查是否超过15分钟
                if hold_duration >= self.force_close_timeout:
                    position_side = entry_info.get('position_side', 'long')
                    size = entry_info.get('size', 0)
                    
                    # 验证持仓是否还存在
                    current_position = self.position_manager.get_position(symbol)
                    if current_position and current_position.get('size', 0) > 0:
                        positions_to_close.append({
                            'symbol': symbol,
                            'position_side': position_side,
                            'size': size,
                            'entry_time': entry_time,
                            'hold_duration': hold_duration_minutes
                        })
                    else:
                        # 持仓已不存在，清除记录
                        del self.position_entry_times[symbol]
                        self.logger.debug(f"✅ {symbol}: 持仓已不存在，清除开仓时间记录")
            
            # 执行强制平仓
            for pos_info in positions_to_close:
                symbol = pos_info['symbol']
                position_side = pos_info['position_side']
                hold_duration = pos_info['hold_duration']
                
                try:
                    self.logger.warning(
                        f"⏰ [15分钟强制平仓] {symbol}: {position_side} | "
                        f"持仓时长={hold_duration:.2f}分钟（超过15分钟） | "
                        f"强制平仓并生成下一次计划"
                    )
                    
                    # 获取当前持仓信息
                    current_position = self.position_manager.get_position(symbol)
                    if not current_position or current_position.get('size', 0) == 0:
                        # 持仓已不存在，清除记录
                        if symbol in self.position_entry_times:
                            del self.position_entry_times[symbol]
                        continue
                    
                    # 获取市场数据
                    symbol_market_data = market_data.get(symbol, {})
                    if not symbol_market_data:
                        # 如果没有市场数据，尝试获取（异步）
                        try:
                            ticker = await self.data_collector.collect_ticker(symbol)
                            if ticker:
                                symbol_market_data = {
                                    'symbol': symbol,
                                    'price': ticker.get('price', 0)
                                }
                        except Exception as e:
                            self.logger.error(f"获取{symbol}市场数据失败: {e}")
                            continue
                    
                    # 创建强制平仓决策
                    close_decision = await self._create_close_decision(
                        symbol,
                        current_position,
                        '15分钟强制平仓',
                        symbol_market_data,
                        symbol_market_data.get('price', 0)
                    )
                    
                    if close_decision:
                        # 执行强制平仓
                        self.logger.info(
                            f"🚨 [执行强制平仓] {symbol}: {position_side} | "
                            f"持仓时长={hold_duration:.2f}分钟 | "
                            f"开始平仓"
                        )
                        
                        await self._execute_trades([close_decision])
                        
                        # 清除开仓时间记录
                        if symbol in self.position_entry_times:
                            del self.position_entry_times[symbol]
                        
                        # 等待平仓完成（给一点时间让订单成交）
                        await asyncio.sleep(2)
                        
                        # 等待1分钟后再生成下一次交易计划
                        self.logger.info(
                            f"📋 [生成下一次计划] {symbol}: 强制平仓后，等待1分钟后生成下一次交易计划"
                        )
                        await asyncio.sleep(60)
                        
                        self.logger.info(
                            f"⏰ [延迟计划触发] {symbol}: 1分钟等待完成，开始生成新的交易计划"
                        )
                        
                        # 重新生成信号和决策
                        try:
                            # 获取最新市场数据
                            latest_market_data = await self._collect_market_data()
                            self._update_market_data_cache(latest_market_data)
                            symbol_market_data = latest_market_data.get(symbol, {})
                            
                            if symbol_market_data:
                                # 生成信号
                                all_signals = await self._generate_signals({symbol: symbol_market_data})
                                
                                # 过滤信号
                                filtered_signals = self.signal_filter.filter_signals(all_signals)
                                
                                # 生成决策
                                new_decisions = await self._make_decisions(
                                    {symbol: symbol_market_data},
                                    filtered_signals
                                )
                                
                                if new_decisions:
                                    # 执行下一次计划
                                    self.logger.info(
                                        f"✅ [执行下一次计划] {symbol}: 已生成新的交易计划，准备执行"
                                    )
                                    await self._execute_trades(new_decisions)
                                else:
                                    self.logger.info(
                                        f"ℹ️ [下一次计划] {symbol}: 未生成新的交易计划，保持观望"
                                    )
                        except Exception as e:
                            self.logger.error(f"生成下一次计划失败 {symbol}: {e}")
                    else:
                        self.logger.error(f"❌ [强制平仓失败] {symbol}: 无法创建平仓决策")
                
                except Exception as e:
                    self.logger.error(f"强制平仓处理失败 {symbol}: {e}")
        
        except Exception as e:
            self.logger.error(f"检查强制平仓失败: {e}")
    
    async def _rapid_stop_loss_check_loop(self):
        """
        快速止损检查循环（每5秒检查一次，保护资金）
        这是一个独立的后台任务，确保快速止损能及时触发
        """
        check_interval = 5  # 每5秒检查一次
        self.logger.info(f"快速止损检查任务启动，检查间隔: {check_interval}秒")
        
        while self.is_running:
            try:
                await asyncio.sleep(check_interval)
                
                if not self.is_running:
                    break
                
                # 获取市场数据
                try:
                    market_data = self._get_cached_market_data(max_age_seconds=5)
                    if market_data is None:
                        market_data = await self._collect_market_data()
                        self._update_market_data_cache(market_data)
                    if market_data:
                        # 执行快速止损检查
                        await self._check_position_adjustments(
                            market_data,
                            enable_ai_analysis=False
                        )
                except Exception as e:
                    self.logger.debug(f"快速止损检查出错（可忽略）: {e}")
                    continue
                    
            except asyncio.CancelledError:
                self.logger.info("快速止损检查任务已取消")
                break
            except Exception as e:
                self.logger.error(f"快速止损检查循环出错: {e}", exc_info=True)
                await asyncio.sleep(check_interval)  # 出错后等待再继续
    
    async def _ai_position_review_loop(self):
        """
        AI持仓审查循环：每分钟检查一次持仓，如果AI分析建议平仓，立即执行平仓
        """
        if not self.ai_review_enabled:
            return
        
        self.logger.info(f"🤖 [AI持仓审查] 任务启动，每分钟检查一次持仓，AI建议平仓时立即执行")
        
        try:
            while self.is_running:
                cycle_start = datetime.now()
                
                try:
                    # 从API实时获取最新持仓数据
                    if self.okx_client is None:
                        self.okx_client = await get_okx_client()
                    positions_result = await self.okx_client.async_get_positions()
                    
                    # 处理不同的返回格式
                    if isinstance(positions_result, dict):
                        if positions_result.get('code') != '0':
                            self.logger.warning("[AI持仓审查] 获取持仓失败，跳过本次检查")
                        else:
                            positions_list = positions_result.get('data', [])
                    elif isinstance(positions_result, list):
                        positions_list = positions_result
                    else:
                        positions_list = []
                    
                    if not positions_list:
                        self.logger.debug("[AI持仓审查] 当前无持仓，跳过本次检查")
                    else:
                        # 提取有持仓的交易对
                        symbols = [pos.get('instId', '') for pos in positions_list if pos.get('instId')]
                        symbols = [s for s in symbols if s]
                        
                        if symbols:
                            # 获取市场数据
                            market_data = await self._collect_market_data(symbols)
                            if market_data:
                                self._update_market_data_cache(market_data)
                                
                                # 执行AI持仓分析和调整（如果AI建议平仓，立即执行）
                                await self._check_position_adjustments(
                                    market_data,
                                    enable_ai_analysis=True,  # 启用AI分析
                                    max_adjustments=None,  # 不限制调整次数，确保平仓能立即执行
                                    source="ai_review_minute"
                                )
                                self.logger.info(f"✅ [AI持仓审查] 完成本次检查，已分析 {len(symbols)} 个持仓")
                            else:
                                self.logger.warning("[AI持仓审查] 市场数据为空，跳过本次检查")
                        else:
                            self.logger.debug("[AI持仓审查] 当前无有效持仓，跳过本次检查")
                            
                except Exception as loop_err:
                    self.logger.error(f"❌ [AI持仓审查] 执行失败: {loop_err}", exc_info=True)
                
                # 计算本次循环耗时，确保每分钟执行一次
                elapsed = (datetime.now() - cycle_start).total_seconds()
                sleep_time = max(60 - elapsed, 1)  # 确保间隔为60秒（1分钟）
                await asyncio.sleep(sleep_time)
        
        except asyncio.CancelledError:
            self.logger.info("AI仓位审查任务已取消")
        except Exception as e:
            self.logger.error(f"AI仓位审查任务异常: {e}", exc_info=True)
    
    async def _check_pending_orders_timeout(self, market_data: Dict[str, Dict[str, Any]]):
        """
        检查15分钟挂单超时：如果挂单超过15分钟未成交，撤销挂单并重新分析重新开仓
        
        Args:
            market_data: 市场数据
        """
        try:
            if not self.pending_orders:
                return  # 没有挂单，无需检查
            
            current_time = datetime.now()
            orders_to_cancel = []
            
            # 检查每个挂单的时间
            for symbol, order_info in list(self.pending_orders.items()):
                create_time = order_info.get('create_time')
                if not create_time:
                    continue
                
                order = order_info.get('order')
                if not order:
                    continue
                
                # 检查订单状态（可能已经成交或被取消）
                try:
                    # 更新订单状态
                    updated_order = self.execution_engine.order_manager.update_order_status(order)
                    
                    # 如果订单已成交或已取消，清除记录
                    if updated_order.status.value in ['filled', 'cancelled', 'rejected']:
                        del self.pending_orders[symbol]
                        self.logger.debug(
                            f"✅ {symbol}: 挂单已{updated_order.status.value}，清除记录"
                        )
                        continue
                except Exception as e:
                    self.logger.warning(f"更新挂单状态失败 {symbol}: {e}")
                
                # 计算挂单时长（秒）
                pending_duration = (current_time - create_time).total_seconds()
                pending_duration_minutes = pending_duration / 60
                
                # 检查是否超过15分钟
                if pending_duration >= self.pending_order_timeout:
                    orders_to_cancel.append({
                        'symbol': symbol,
                        'order': order,
                        'decision': order_info.get('decision'),
                        'create_time': create_time,
                        'pending_duration': pending_duration_minutes
                    })
            
            # 执行撤销挂单并重新分析
            for cancel_info in orders_to_cancel:
                symbol = cancel_info['symbol']
                order = cancel_info['order']
                decision = cancel_info.get('decision')
                pending_duration = cancel_info['pending_duration']
                
                try:
                    self.logger.warning(
                        f"⏰ [15分钟挂单超时] {symbol}: "
                        f"挂单时长={pending_duration:.2f}分钟（超过15分钟） | "
                        f"撤销挂单并重新分析重新开仓"
                    )
                    
                    # 1. 撤销挂单
                    try:
                        await asyncio.to_thread(
                            self.execution_engine.order_manager.cancel_order,
                            order
                        )
                        self.logger.info(
                            f"✅ [撤销挂单] {symbol}: 订单ID={order.order_id} | "
                            f"挂单时长={pending_duration:.2f}分钟"
                        )
                    except Exception as e:
                        self.logger.error(f"❌ [撤销挂单失败] {symbol}: {e}")
                        # 即使撤销失败，也继续重新分析
                    
                    # 清除挂单记录
                    if symbol in self.pending_orders:
                        del self.pending_orders[symbol]
                    
                    # 等待撤销完成
                    await asyncio.sleep(1)
                    
                    # 2. 重新分析市场
                    self.logger.info(
                        f"📋 [重新分析] {symbol}: 撤销挂单后，立即重新分析市场并生成新的交易计划"
                    )
                    
                    try:
                        # 获取最新市场数据
                        latest_market_data = await self._collect_market_data()
                        self._update_market_data_cache(latest_market_data)
                        symbol_market_data = latest_market_data.get(symbol, {})
                        
                        if not symbol_market_data:
                            # 如果没有市场数据，尝试获取（异步）
                            try:
                                ticker = await self.data_collector.collect_ticker(symbol)
                                if ticker:
                                    symbol_market_data = {
                                        'symbol': symbol,
                                        'price': ticker.get('price', 0)
                                    }
                            except Exception as e:
                                self.logger.error(f"获取{symbol}市场数据失败: {e}")
                                continue
                        
                        if symbol_market_data:
                            # 生成信号
                            all_signals = await self._generate_signals({symbol: symbol_market_data})
                            
                            # 过滤信号
                            filtered_signals = self.signal_filter.filter_signals(all_signals)
                            
                            # 生成决策
                            new_decisions = await self._make_decisions(
                                {symbol: symbol_market_data},
                                filtered_signals
                            )
                            
                            if new_decisions:
                                # 执行新的交易计划
                                self.logger.info(
                                    f"✅ [重新开仓] {symbol}: 已生成新的交易计划，准备执行"
                                )
                                await self._execute_trades(new_decisions)
                            else:
                                self.logger.info(
                                    f"ℹ️ [重新分析结果] {symbol}: 未生成新的交易计划，保持观望"
                                )
                    except Exception as e:
                        self.logger.error(f"重新分析失败 {symbol}: {e}")
                
                except Exception as e:
                    self.logger.error(f"处理挂单超时失败 {symbol}: {e}")
        
        except Exception as e:
            self.logger.error(f"检查挂单超时失败: {e}")
    
    async def _monitor_risk(self):
        """监控风险"""
        try:
            # 获取所有持仓
            positions = self.position_manager.get_all_positions()
            
            # 获取市场数据
            market_data = {}
            for symbol in positions.keys():
                ticker = self.data_collector.get_cached_data('ticker', symbol)
                if ticker:
                    market_data[symbol] = {
                        'price': ticker.get('price', 0),
                        'volatility': 0.25  # 简化处理
                    }
            
            # 监控风险
            risk_metrics = self.risk_manager.monitor_risk(
                list(positions.values()),
                market_data
            )
            
            # 检查止损
            for symbol, position in positions.items():
                if position.get('size', 0) > 0:
                    position_id = f"{symbol}_{position.get('side', 'none')}"
                    current_price = market_data.get(symbol, {}).get('price', 0)
                    
                    if current_price > 0:
                        self.risk_manager.stop_loss_manager.check_stop_loss(
                            position_id, current_price
                        )
        
        except Exception as e:
            self.logger.error(f"风险监控失败: {e}")
    
    def _is_decision_similar(self, new_decision, old_decision, old_order) -> bool:
        """
        判断新决策和已有委托订单是否相似（避免重复创建）
        
        Args:
            new_decision: 新决策
            old_decision: 旧决策
            old_order: 旧订单
            
        Returns:
            True表示相似，False表示有差异
        """
        try:
            # 1. 检查交易方向是否一致
            if new_decision.action != old_decision.action:
                return False  # 方向不同，有差异
            
            if new_decision.position_side != old_decision.position_side:
                return False  # 持仓方向不同，有差异
            
            # 2. 检查价格差异（如果都是限价单）
            if new_decision.price and old_order.price:
                price_diff_pct = abs(new_decision.price - old_order.price) / old_order.price * 100
                if price_diff_pct > 0.5:  # 价格差异超过0.5%，认为有差异
                    return False
            
            # 3. 检查仓位大小差异
            position_diff = abs(new_decision.position_size - old_decision.position_size)
            if position_diff > 0.01:  # 仓位差异超过1%，认为有差异
                return False
            
            # 4. 检查信心度差异
            confidence_diff = abs(new_decision.confidence - old_decision.confidence)
            if confidence_diff > 0.1:  # 信心度差异超过0.1，认为有差异
                return False
            
            # 如果以上都相似，认为决策相似
            return True
            
        except Exception as e:
            self.logger.warning(f"比较决策相似性失败: {e}")
            return False  # 出错时认为有差异，允许创建新订单
    
    async def _calculate_profit(self, order, trade_info: Optional[Dict[str, Any]] = None):
        """计算交易收益并写回结果记录"""
        try:
            trade_id = order.order_id
            symbol = order.symbol
            exit_price = trade_info.get('exit_price') if trade_info else None
            if exit_price is None:
                exit_price = order.average_price or order.filled_price or 0.0
            
            entry_price = trade_info.get('entry_price') if trade_info else 0.0
            quantity = trade_info.get('position_size') if trade_info else order.filled_size
            entry_time = trade_info.get('entry_time') if trade_info else (order.created_at or datetime.now())
            exit_time = trade_info.get('exit_time') if trade_info else (order.executed_at or datetime.now())
            position_side = trade_info.get('position_side') if trade_info else order.side
            
            if isinstance(position_side, str):
                position_side = position_side.lower()
                if position_side == 'buy':
                    position_side = 'long'
                elif position_side == 'sell':
                    position_side = 'short'
            else:
                position_side = 'long'
            
            fees = getattr(order, 'fee', 0) or 0.0
            
            gross_profit = 0.0
            profit_pct = 0.0
            if entry_price and quantity:
                if position_side == 'short':
                    gross_profit = (entry_price - exit_price) * quantity
                    profit_pct = ((entry_price - exit_price) / entry_price) * 100
                else:
                    gross_profit = (exit_price - entry_price) * quantity
                    profit_pct = ((exit_price - entry_price) / entry_price) * 100
            
            trade_data = {
                'trade_id': trade_id,
                'symbol': symbol,
                'entry_time': entry_time,
                'exit_time': exit_time,
                'entry_price': entry_price,
                'exit_price': exit_price,
                'quantity': quantity,
                'fees': fees
            }
            
            trade_profit = self.profit_statistics.calculate_trade_profit(trade_data)
            
            if trade_info and trade_info.get('record_id'):
                holding_hours = (exit_time - entry_time).total_seconds() / 3600 if entry_time else 0.0
                exit_reason = trade_info.get('exit_reason', 'close')
                try:
                    self.result_recorder.record_trade_result(
                        record_id=trade_info['record_id'],
                        exit_price=exit_price,
                        profit_pct=profit_pct,
                        holding_duration_hours=holding_hours,
                        exit_reason=exit_reason
                    )
                    self.trade_count_since_optimization += 1
                    self._schedule_prompt_optimization()
                except Exception as err:
                    self.logger.error(f"写入交易结果失败 {symbol}: {err}")
            
            self.logger.info(
                f"交易收益: {trade_profit.symbol} {trade_profit.trade_id}, "
                f"收益={trade_profit.net_profit:.2f}, 收益率={trade_profit.return_rate:.2f}%"
            )
            
            # 写入交易记录日志
            self._write_trade_log(trade_info, order, trade_profit)
        
        except Exception as e:
            self.logger.error(f"计算交易收益失败: {e}")
    
    async def _cancel_all_orders(self):
        """取消所有未完成订单"""
        try:
            active_orders = self.execution_engine.order_manager.get_active_orders()
            
            for order in active_orders:
                try:
                    self.execution_engine.order_manager.cancel_order(order)
                except Exception as e:
                    self.logger.error(f"取消订单失败 {order.order_id}: {e}")
            
            # 清除待成交订单记录
            self.pending_orders.clear()
            self.logger.info("已清除所有待成交订单记录")
        except Exception as e:
            self.logger.error(f"取消所有订单失败: {e}")
    
    def enable_trading(self):
        """启用交易"""
        self.trading_enabled = True
        self.logger.info("交易已启用")
    
    def disable_trading(self):
        """禁用交易"""
        self.trading_enabled = False
        self.logger.info("交易已禁用")
    
    def _write_trade_log_entry(self, symbol: str, decision, order, entry_price: float, entry_time: datetime):
        """
        记录开仓信息到交易日志
        
        Args:
            symbol: 交易对
            decision: 交易决策
            order: 订单对象
            entry_price: 开仓价
            entry_time: 开仓时间
        """
        try:
            # 生成日志文件名：交易对_日期_时间_开仓.log
            timestamp = entry_time.strftime('%Y%m%d_%H%M%S')
            log_file = self.trade_log_dir / f"{symbol}_{timestamp}_ENTRY.json"
            
            trade_log = {
                'symbol': symbol,
                'action': 'ENTRY',
                'timestamp': entry_time.isoformat(),
                'order_id': order.order_id,
                'position_side': decision.position_side,
                'entry_price': float(entry_price),
                'quantity': float(order.filled_size),
                'confidence': float(decision.confidence) if decision.confidence else 0.0,
                'entry_reason': decision.reasoning or 'open',
                'decision_action': decision.action,
                'position_size_pct': float(decision.position_size) if decision.position_size else 0.0,
            }
            
            # 如果有AI分析，也记录
            if hasattr(decision, 'signals') and decision.signals:
                for signal in decision.signals:
                    if signal.get('source') == 'ai':
                        trade_log['ai_analysis'] = signal.get('data', {})
                        break
            
            # 写入JSON文件
            with open(log_file, 'w', encoding='utf-8') as f:
                json.dump(trade_log, f, indent=2, ensure_ascii=False)
            
            self.logger.info(f"📝 [交易日志] 开仓记录已保存: {log_file}")
            
        except Exception as e:
            self.logger.error(f"写入开仓日志失败 {symbol}: {e}")
    
    def _write_trade_log(self, trade_info: Dict[str, Any], order, trade_profit):
        """
        记录完整交易记录到日志文件（平仓时）
        
        Args:
            trade_info: 交易信息
            order: 订单对象
            trade_profit: 交易收益对象
        """
        try:
            symbol = order.symbol
            entry_time = trade_info.get('entry_time') if trade_info else (order.created_at or datetime.now())
            
            # 生成日志文件名：交易对_日期_时间_完整.log
            timestamp = entry_time.strftime('%Y%m%d_%H%M%S')
            log_file = self.trade_log_dir / f"{symbol}_{timestamp}_COMPLETE.json"
            
            exit_time = trade_info.get('exit_time') if trade_info else (order.executed_at or datetime.now())
            holding_duration = (exit_time - entry_time).total_seconds() / 60 if entry_time else 0  # 分钟
            
            trade_log = {
                'symbol': symbol,
                'action': 'COMPLETE',
                'trade_id': order.order_id,
                'entry_time': entry_time.isoformat() if isinstance(entry_time, datetime) else str(entry_time),
                'exit_time': exit_time.isoformat() if isinstance(exit_time, datetime) else str(exit_time),
                'holding_duration_minutes': round(holding_duration, 2),
                'position_side': trade_info.get('position_side', 'long') if trade_info else 'long',
                'entry_price': float(trade_info.get('entry_price', 0)) if trade_info else 0.0,
                'exit_price': float(trade_info.get('exit_price', 0)) if trade_info else float(order.average_price or order.filled_price or 0),
                'quantity': float(trade_info.get('position_size', 0)) if trade_info else float(order.filled_size or 0),
                'gross_profit': float(trade_profit.gross_profit) if trade_profit else 0.0,
                'net_profit': float(trade_profit.net_profit) if trade_profit else 0.0,
                'return_rate_pct': float(trade_profit.return_rate) if trade_profit else 0.0,
                'fees': float(trade_profit.fees) if trade_profit else 0.0,
                'entry_reason': trade_info.get('entry_reason', 'open') if trade_info else 'open',
                'exit_reason': trade_info.get('exit_reason', 'close') if trade_info else 'close',
            }
            
            # 如果有AI分析，也记录
            if trade_info and trade_info.get('ai_analysis'):
                trade_log['ai_analysis'] = trade_info.get('ai_analysis')
            
            # 写入JSON文件
            with open(log_file, 'w', encoding='utf-8') as f:
                json.dump(trade_log, f, indent=2, ensure_ascii=False)
            
            self.logger.info(
                f"📝 [交易日志] 完整交易记录已保存: {log_file} | "
                f"盈亏={trade_log['net_profit']:.2f} USDT ({trade_log['return_rate_pct']:.2f}%)"
            )
            
        except Exception as e:
            self.logger.error(f"写入交易日志失败 {order.symbol if order else 'unknown'}: {e}")


if __name__ == "__main__":
    # 测试交易引擎
    engine = TradingEngine()
    
    # 启动交易引擎（异步）
    async def test():
        await engine.start()
    
    # asyncio.run(test())

