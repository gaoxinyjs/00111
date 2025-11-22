#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
DeepSeek API客户端
封装DeepSeek API调用，构建分析提示词，解析AI返回结果
"""

import json
import time
import os
import requests
from typing import Dict, List, Optional, Any
from datetime import datetime
from ..core.config_manager import get_config_manager
from ..core.logger import get_logger
from ..core.security import get_security_manager
from ..core.exception import APIException


class DeepSeekClient:
    """DeepSeek API客户端"""
    
    def __init__(self):
        """初始化DeepSeek客户端"""
        self.config_mgr = get_config_manager()
        self.logger = get_logger("deepseek_client")
        self.security = get_security_manager()
        
        # 获取配置
        deepseek_config = self.config_mgr.get_config('api', 'deepseek')
        self.api_key = self.security.get_api_key('deepseek', 'api_key')
        self.base_url = deepseek_config.get('base_url', 'https://api.deepseek.com')
        self.model = deepseek_config.get('model', 'deepseek-chat')
        self.temperature = deepseek_config.get('temperature', 0.3)
        self.max_tokens = deepseek_config.get('max_tokens', 2000)
        
        # 限流配置
        rate_limit = deepseek_config.get('rate_limit', {})
        self.requests_per_minute = rate_limit.get('requests_per_minute', 20)
        self.last_request_times: List[float] = []
        
        # 重试配置
        retry_config = deepseek_config.get('retry', {})
        self.max_retries = retry_config.get('max_retries', 5)  # 增加最大重试次数到5次
        self.retry_delay = retry_config.get('retry_delay', 3)  # 增加初始重试延迟到3秒
        
        # 超时配置
        timeout_config = deepseek_config.get('timeout', {})
        self.connect_timeout = timeout_config.get('connect_timeout', 10)  # 连接超时：10秒
        self.read_timeout = timeout_config.get('read_timeout', 90)  # 读取超时：90秒（AI响应可能需要更长时间）
        self.total_timeout = timeout_config.get('total_timeout', 120)  # 总超时：120秒
        
        # 自学习：初始化优化指导原则属性（必须在__init__中初始化）
        self.optimization_guidelines = []
        
        # 延迟加载优化指导原则，避免初始化时的循环依赖
        try:
            self._load_optimization_guidelines()
        except Exception as e:
            self.logger.debug(f"初始化优化指导原则失败（将在首次使用时加载）: {e}")
            # 属性已初始化，保持为空列表即可
        
        if not self.api_key:
            self.logger.warning("DeepSeek API密钥未配置，请检查配置")
        
        # 初始化DeepSeek结果记录目录
        try:
            system_config = self.config_mgr.get_config('system')
            data_dir = system_config.get('data_dir', 'data') if system_config else 'data'
        except (KeyError, TypeError):
            data_dir = 'data'
        
        self.results_dir = os.path.join(data_dir, 'deepseek_responses')
        os.makedirs(self.results_dir, exist_ok=True)
    
    def _rate_limit(self):
        """API限流"""
        current_time = time.time()
        
        # 清除1分钟前的请求记录
        self.last_request_times = [
            t for t in self.last_request_times 
            if current_time - t < 60
        ]
        
        if len(self.last_request_times) >= self.requests_per_minute:
            sleep_time = 60 - (current_time - self.last_request_times[0]) + 1
            if sleep_time > 0:
                self.logger.info(f"API限流，等待{sleep_time:.2f}秒...")
                time.sleep(sleep_time)
        
        self.last_request_times.append(time.time())
    
    def _serialize_for_json(self, obj: Any) -> Any:
        """
        将对象序列化为JSON兼容的类型
        处理pandas Timestamp、numpy类型、datetime等不可序列化的对象
        
        Args:
            obj: 要序列化的对象
            
        Returns:
            JSON兼容的对象
        """
        # 处理pandas Timestamp
        try:
            if hasattr(obj, 'strftime'):
                # datetime-like对象
                if hasattr(obj, 'to_pydatetime'):
                    # pandas Timestamp
                    return obj.to_pydatetime().isoformat()
                else:
                    # datetime对象
                    return obj.isoformat()
        except (AttributeError, ValueError):
            pass
        
        # 处理numpy类型
        try:
            import numpy as np
            if isinstance(obj, (np.integer, np.floating)):
                return obj.item()
            if isinstance(obj, np.ndarray):
                return obj.tolist()
        except (ImportError, AttributeError, ValueError):
            pass
        
        # 处理字典
        if isinstance(obj, dict):
            return {k: self._serialize_for_json(v) for k, v in obj.items()}
        
        # 处理列表
        if isinstance(obj, (list, tuple)):
            return [self._serialize_for_json(item) for item in obj]
        
        # 处理其他可序列化的类型
        return obj
    
    def _build_prompt(self, market_data: Dict[str, Any], signal_context: Dict[str, Any]) -> str:
        """
        构建分析提示词
        
        Args:
            market_data: 市场数据
            signal_context: 信号上下文
            
        Returns:
            完整的提示词
        """
        # 提取详细的技术指标数据
        indicators = market_data.get('indicators', {})
        # 优先使用kline（15分钟K线），如果没有则使用kline_1H
        kline_data = market_data.get('kline', []) or market_data.get('kline_1H', [])
        multi_timeframe = market_data.get('multi_timeframe', {})
        
        # 计算技术指标的详细解读
        technical_analysis = self._analyze_technical_indicators(indicators, kline_data)
        
        # 提取价格趋势信息
        price_trend = self._extract_price_trend(kline_data)
        
        # 提取量价关系
        volume_price_analysis = self._extract_volume_price_relationship(kline_data)
        
        # 提取做市商意图分析
        orderbook_data = market_data.get('orderbook', {})
        market_maker_analysis = self._analyze_market_maker_intent(orderbook_data, market_data.get('price', 0))
        
        # 准备数据，避免在f-string中使用{}导致的语法问题
        empty_dict = {}
        funding_data = market_data.get('funding', empty_dict) or {}
        derivatives_data = market_data.get('derivatives', empty_dict) or {}
        orderflow_data = market_data.get('orderflow', empty_dict) or {}
        impact_data = market_data.get('impact', empty_dict) or {}
        chain_data = market_data.get('chain', empty_dict) or {}
        sentiment_data = market_data.get('sentiment', empty_dict) or {}
        macro_data = market_data.get('macro', empty_dict) or {}
        open_interest_data = derivatives_data.get('open_interest', {}) or {}
        taker_volume_data = derivatives_data.get('taker_volume', {}) or {}
        long_short_data = derivatives_data.get('long_short_ratio', {}) or {}
        liquidation_data = derivatives_data.get('liquidations', {}) or {}
        basis_data = derivatives_data.get('basis', {}) or {}
        
        # 序列化数据
        funding_json = json.dumps(self._serialize_for_json(funding_data), indent=2, ensure_ascii=False)
        chain_json = json.dumps(self._serialize_for_json(chain_data), indent=2, ensure_ascii=False)
        sentiment_json = json.dumps(self._serialize_for_json(sentiment_data), indent=2, ensure_ascii=False)
        
        # 计算MACD强度，避免在f-string中使用复杂表达式导致格式说明符错误
        try:
            macd_value = indicators.get('macd')
            macd_hist_value = indicators.get('macd_hist', 0)
            if macd_value and float(macd_value) != 0:
                macd_strength = abs(float(macd_hist_value)) / abs(float(macd_value)) * 100
                macd_strength_str = f"{macd_strength:.2f}%"
            else:
                macd_strength_str = 'N/A'
        except (ValueError, TypeError, ZeroDivisionError):
            macd_strength_str = 'N/A'
        
        # 格式化市场数据，避免在f-string中使用.get()并格式化导致格式说明符错误
        try:
            change_24h_value = market_data.get('change_24h')
            if change_24h_value is not None:
                try:
                    change_24h_float = float(change_24h_value)
                    change_24h_str = f"{change_24h_float:.2f}%"
                except (ValueError, TypeError):
                    change_24h_str = f"{change_24h_value}%"
            else:
                change_24h_str = 'N/A'
        except Exception:
            change_24h_str = 'N/A'
        
        try:
            atr_pct_value = indicators.get('atr_pct')
            if atr_pct_value is not None:
                try:
                    atr_pct_float = float(atr_pct_value)
                    atr_pct_str = f"{atr_pct_float:.2f}%"
                except (ValueError, TypeError):
                    # 如果不是数字，直接转换为字符串，确保安全
                    atr_pct_safe = str(atr_pct_value).replace('{', '{{').replace('}', '}}')
                    atr_pct_str = f"{atr_pct_safe}%"
            else:
                atr_pct_str = 'N/A'
        except Exception:
            atr_pct_str = 'N/A'
        
        # 预先提取所有在f-string中使用的值，避免在f-string中使用.get()导致格式说明符错误
        def safe_get_str(d, key, default='N/A'):
            """安全获取值并转换为字符串"""
            try:
                value = d.get(key, default)
                if value is None:
                    return str(default)
                return str(value)
            except Exception:
                return str(default)
        
        def format_percent(value: Any, precision: int = 2, scale: float = 100.0, default: str = 'N/A') -> str:
            """将数值格式化为百分比字符串"""
            try:
                if value is None:
                    return default
                return f"{float(value) * scale:.{precision}f}%"
            except (ValueError, TypeError):
                return str(value) if value is not None else default
        
        # 提取所有market_data中的值
        symbol_str = safe_get_str(market_data, 'symbol', 'UNKNOWN')
        price_str = safe_get_str(market_data, 'price', 'N/A')
        high_24h_str = safe_get_str(market_data, 'high_24h', 'N/A')
        low_24h_str = safe_get_str(market_data, 'low_24h', 'N/A')
        volume_24h_str = safe_get_str(market_data, 'volume_24h', 'N/A')
        
        # 提取所有indicators中的值
        macd_str = safe_get_str(indicators, 'macd', 'N/A')
        macd_signal_str = safe_get_str(indicators, 'macd_signal', 'N/A')
        macd_hist_str = safe_get_str(indicators, 'macd_hist', 'N/A')
        rsi_str = safe_get_str(indicators, 'rsi', 'N/A')
        bb_upper_str = safe_get_str(indicators, 'bb_upper', 'N/A')
        bb_middle_str = safe_get_str(indicators, 'bb_middle', 'N/A')
        bb_lower_str = safe_get_str(indicators, 'bb_lower', 'N/A')
        bb_width_str = safe_get_str(indicators, 'bb_width', 'N/A')
        ma_5_str = safe_get_str(indicators, 'ma_5', 'N/A')
        ma_20_str = safe_get_str(indicators, 'ma_20', 'N/A')
        ma_60_str = safe_get_str(indicators, 'ma_60', 'N/A')
        ema_12_str = safe_get_str(indicators, 'ema_12', 'N/A')
        ema_26_str = safe_get_str(indicators, 'ema_26', 'N/A')
        ema_50_str = safe_get_str(indicators, 'ema_50', 'N/A')
        kdj_k_str = safe_get_str(indicators, 'kdj_k', 'N/A')
        kdj_d_str = safe_get_str(indicators, 'kdj_d', 'N/A')
        kdj_j_str = safe_get_str(indicators, 'kdj_j', 'N/A')
        cci_str = safe_get_str(indicators, 'cci', 'N/A')
        obv_str = safe_get_str(indicators, 'obv', 'N/A')
        obv_ma_str = safe_get_str(indicators, 'obv_ma', 'N/A')
        atr_str = safe_get_str(indicators, 'atr', 'N/A')
        adx_str = safe_get_str(indicators, 'adx', 'N/A')
        plus_di_str = safe_get_str(indicators, 'plus_di', 'N/A')
        minus_di_str = safe_get_str(indicators, 'minus_di', 'N/A')
        momentum_str = safe_get_str(indicators, 'momentum', 'N/A')
        price_change_str = safe_get_str(indicators, 'price_change', 'N/A')
        volatility_str = safe_get_str(indicators, 'volatility', 'N/A')
        
        # 前瞻指标字符串
        funding_current_str = format_percent(funding_data.get('current_rate'))
        funding_next_str = format_percent(funding_data.get('next_rate'))
        funding_time_str = safe_get_str(funding_data, 'funding_time', 'N/A')
        next_funding_time_str = safe_get_str(funding_data, 'next_funding_time', 'N/A')
        oi_amount_str = safe_get_str(open_interest_data, 'amount', 'N/A')
        oi_ccy_str = safe_get_str(open_interest_data, 'amount_ccy', 'N/A')
        taker_buy_ratio_str = format_percent(orderflow_data.get('taker_buy_ratio', taker_volume_data.get('taker_buy_ratio')))
        net_flow_str = safe_get_str(orderflow_data, 'net_flow', 'N/A')
        trades_per_sec_str = safe_get_str(orderflow_data, 'trades_per_sec', 'N/A')
        orderbook_imbalance_str = format_percent(orderbook_data.get('imbalance'))
        near_depth_str = f"{safe_get_str(orderbook_data, 'near_bid_volume', 'N/A')} / {safe_get_str(orderbook_data, 'near_ask_volume', 'N/A')}"
        long_short_ratio_str = safe_get_str(long_short_data, 'long_short_ratio', 'N/A')
        sentiment_label_str = safe_get_str(sentiment_data, 'label', 'N/A')
        liquidation_long_str = safe_get_str(liquidation_data, 'long_volume', 'N/A')
        liquidation_short_str = safe_get_str(liquidation_data, 'short_volume', 'N/A')
        liquidation_max_str = safe_get_str(liquidation_data.get('largest_liquidation', {}), 'notional', 'N/A')
        basis_spot_str = format_percent(basis_data.get('spot_basis_pct'))
        basis_mark_str = format_percent(basis_data.get('mark_basis_pct'))
        funding_annualized_str = format_percent(basis_data.get('funding_annualized_pct'))
        premium_pct_str = format_percent(basis_data.get('premium_pct'))
        impact_notional_str = safe_get_str(impact_data, 'impact_notional', 'N/A')
        impact_buy_pct_str = format_percent((impact_data.get('buy') or {}).get('impact_pct'))
        impact_sell_pct_str = format_percent((impact_data.get('sell') or {}).get('impact_pct'))
        block_data = orderflow_data.get('block_trades', {}) or {}
        block_count_str = safe_get_str(block_data, 'count', '0')
        block_bias_str = safe_get_str(block_data, 'bias', 'neutral')
        block_net_notional_str = safe_get_str(block_data, 'net_notional', '0')
        macro_risk_label_str = safe_get_str(macro_data, 'risk_level', 'normal')
        macro_events_summary = ', '.join(
            event.get('name', '') for event in macro_data.get('active_events', []) or []
        ) or '无'
        
        # 提取所有technical_analysis中的值
        macd_signal_analysis_str = safe_get_str(technical_analysis, 'macd_signal', 'N/A')
        rsi_signal_str = safe_get_str(technical_analysis, 'rsi_signal', 'N/A')
        rsi_strength_str = safe_get_str(technical_analysis, 'rsi_strength', 'N/A')
        bb_position_str = safe_get_str(technical_analysis, 'bb_position', 'N/A')
        bb_signal_str = safe_get_str(technical_analysis, 'bb_signal', 'N/A')
        ma_relationship_str = safe_get_str(technical_analysis, 'ma_relationship', 'N/A')
        
        # 提取所有multi_timeframe中的值
        overall_trend_str = safe_get_str(multi_timeframe, 'overall_trend', 'N/A')
        trend_strength_str = safe_get_str(multi_timeframe, 'trend_strength', 'N/A')
        trend_24h_str = safe_get_str(multi_timeframe, 'trend_24H', 'N/A')
        strength_24h_str = safe_get_str(multi_timeframe, 'strength_24H', 'N/A')
        trend_4h_str = safe_get_str(multi_timeframe, 'trend_4H', 'N/A')
        strength_4h_str = safe_get_str(multi_timeframe, 'strength_4H', 'N/A')
        trend_1h_str = safe_get_str(multi_timeframe, 'trend_1H', 'N/A')
        strength_1h_str = safe_get_str(multi_timeframe, 'strength_1H', 'N/A')
        entry_timing_str = safe_get_str(multi_timeframe, 'entry_timing', 'N/A')
        entry_direction_str = safe_get_str(multi_timeframe, 'entry_direction', 'N/A')
        confidence_str = safe_get_str(multi_timeframe, 'confidence', 'N/A')
        
        prompt = f"""你是一位顶级的加密货币量化交易分析师，拥有超过15年的实战经验，擅长短线交易和合约交易。

## 🎯 核心任务（必须完成）

  **你必须根据以下市场数据和技术指标，给出明确的交易决策或观望理由：**

  1. **direction**（必填）：允许返回 "long"（做多）、"short"（做空）或 "hold"（观望/暂缓）
  2. **entry_limit_price**：当direction为long或short时必填（具体数字，不要百分比；若观望请返回`null`）
  3. **exit_limit_price**：当direction为long或short时必填（止盈目标，具体数字，不要百分比；若观望返回`null`）
  4. **noise_risk / avoid_reason / entry_delay_seconds**：必须评估噪音风险，若不满足交易条件需要解释原因

  **⚠️ 重要提示**：代码内部不做决策，只提供指标数据。**所有决策都由你完成**。除非你详细写出`avoid_reason`说明为什么观望，否则系统会默认执行你的方向。

  **🚨 关键要求**：当你认为市场噪音高、信号矛盾、风险收益比不足或关键价位尚未确认时，可以返回"hold"并给出`avoid_reason`和建议的重新评估时间；只有在前瞻性指标、量价、做市商意图至少两项共振且噪音风险可控时，才返回long或short。

**🎯 分析优先级（必须严格遵守）**：
- **优先级1（最高）**：前瞻性指标（订单簿、订单流、成交量分布）- 比滞后指标更早捕捉价格变化，必须优先分析
- **优先级2（辅助确认）**：技术指标（MACD、RSI、KDJ等）- 滞后指标，用于确认前瞻性信号的强弱
- **优先级3（关键确认）**：量价关系和做市商意图 - 验证信号的真实性
- **优先级4（综合判断）**：结合所有指标，给出最终决策

**重要**：如果前瞻性指标和技术指标方向相反，**以前瞻性指标为主**，因为前瞻性指标能更早捕捉价格变化。

## 核心交易策略（重新设计）
**交易模式**: 短线合约交易（默认≤5倍杠杆，如需更高杠杆必须给出理由）
**核心原则**:
1. **稳健交易**：优先保证资金安全，追求稳定收益，不追求暴利
2. **严格止损**：根据市场波动率动态调整止损（价格0.08%-0.25%），止盈（0.15%-0.45%），风险收益比≥1:1.8
3. **多指标共振**：前瞻性指标+量价关系+技术指标至少两者同向才给出强烈建议
4. **量价配合**：成交量必须配合价格变化，量价背离必须警惕
5. **做市商意图**：订单簿分析是关键，大单分布揭示真实意图
6. **动态仓位**：根据信心度与噪音分级（高信心度≤5%仓位，中等3-4%，低信心度≤2%）
7. **方向判断**：必须结合前瞻性指标和技术指标，若矛盾请返回hold

## 交易对信息
**交易对**: {symbol_str}
**当前价格**: {price_str} USDT
**24小时涨跌**: {change_24h_str}
**24小时最高**: {high_24h_str}
**24小时最低**: {low_24h_str}
**24小时成交量**: {volume_24h_str}
**当前趋势**: {overall_trend_str} | 趋势强度: {trend_strength_str}

 ## 🔮 前瞻性指标（必须优先分析）
 - **资金费率**: 当前 {funding_current_str} | 下次 {funding_next_str} | 时间 {funding_time_str} -> {next_funding_time_str}
 - **未平仓量**: 合约张数 {oi_amount_str} | 币本位 {oi_ccy_str}
 - **主动成交/订单流**: 买方占比 {taker_buy_ratio_str} | 净流入 {net_flow_str} | 每秒成交 {trades_per_sec_str}
 - **订单簿**: 近端深度 (Bid/Ask) {near_depth_str} | 不平衡 {orderbook_imbalance_str} | 做市商分析: {market_maker_analysis}
 - **多空账户情绪**: Long/Short 比 {long_short_ratio_str} | 系统情绪标签: {sentiment_label_str}
 - **强平压力**: 多头 {liquidation_long_str} / 空头 {liquidation_short_str} | 最大单笔 {liquidation_max_str}
 - **价差/拥挤度**: 永续-指数 {basis_spot_str} | Mark {basis_mark_str} | Premium {premium_pct_str} | 资金年化 {funding_annualized_str}
 - **冲击成本**: 吃掉 {impact_notional_str} USDT -> 买侧冲击 {impact_buy_pct_str} / 卖侧 {impact_sell_pct_str}
 - **区块大单**: {block_count_str} 笔 | 偏向 {block_bias_str} | 净流 {block_net_notional_str}
 - **宏观风险**: 当前级别 {macro_risk_label_str} | 活跃事件: {macro_events_summary}
 
## 📈 技术指标分析（滞后指标，用于确认前瞻性信号）

**⚠️ 重要提示**：技术指标是滞后指标，主要用于确认前瞻性指标的信号强弱。如果前瞻性指标和技术指标方向相反，**必须以前瞻性指标为主**。

### MACD指标（趋势动量指标）
- **MACD线**: {macd_str}
- **信号线**: {macd_signal_str}
- **MACD柱状图**: {macd_hist_str}
- **信号解读**: {macd_signal_analysis_str}
- **MACD强度**: {macd_strength_str}

**MACD关键判断**：
  * **强烈看涨**：MACD线 > 信号线且MACD_Hist > 0且MACD_Hist强度 > 10%，为金叉且趋势强
  * **看涨**：MACD线 > 信号线且MACD_Hist > 0，为金叉信号
  * **看跌**：MACD线 < 信号线且MACD_Hist < 0，为死叉信号
  * **强烈看跌**：MACD线 < 信号线且MACD_Hist < 0且MACD_Hist强度 > 10%，为死叉且趋势强
  * **注意**：MACD_Hist的数值越大（绝对值），趋势越强；MACD_Hist接近0时，趋势可能反转

### RSI相对强弱指标（超买超卖指标）
- **RSI值**: {rsi_str}
- **信号解读**: {rsi_signal_str}
- **RSI强度**: {rsi_strength_str}

**RSI关键判断**：
  * **强烈超卖**：RSI < 25，可能出现强烈反弹（买入机会，但需配合成交量）
  * **超卖**：RSI < 30，可能出现反弹（买入机会，但需确认）
  * **偏弱**：30 < RSI < 40，可能继续下跌，谨慎做多
  * **中性**：40 < RSI < 60，跟随趋势方向
  * **偏强**：60 < RSI < 70，可能继续上涨，谨慎做空
  * **超买**：RSI > 70，可能出现回调（卖出/做空机会，但需确认）
  * **强烈超买**：RSI > 75，可能出现强烈回调（强烈卖出/做空信号）
  * **注意**：RSI必须配合成交量分析，超卖+放量上涨才是真正的买入信号，超买+放量下跌才是真正的卖出信号

### 布林带指标
- **上轨**: {bb_upper_str}
- **中轨（20日均线）**: {bb_middle_str}
- **下轨**: {bb_lower_str}
- **当前价格相对位置**: {bb_position_str}
- **布林带宽度**: {bb_width_str}
- **信号解读**: {bb_signal_str}
  * 价格触及下轨：可能超卖，买入机会（但需确认）
  * 价格触及上轨：可能超买，卖出机会（但需确认）
  * 价格在中轨上方：偏多
  * 价格在中轨下方：偏空
  * 布林带收窄：可能酝酿大波动

### 移动平均线
- **5日均线**: {ma_5_str}
- **20日均线**: {ma_20_str}
- **60日均线**: {ma_60_str}
- **均线关系**: {ma_relationship_str}
  * 5日均线 > 20日均线：短期上涨趋势
  * 5日均线 < 20日均线：短期下跌趋势
  * 金叉（5日上穿20日）：强烈看涨信号
  * 死叉（5日下穿20日）：强烈看跌信号

### EMA指数移动平均线
- **EMA12**: {ema_12_str}
- **EMA26**: {ema_26_str}
- **EMA50**: {ema_50_str}
  * EMA12 > EMA26 > EMA50：多头排列，看涨
  * EMA12 < EMA26 < EMA50：空头排列，看跌
  * EMA12与EMA26金叉：短期看涨信号
  * EMA12与EMA26死叉：短期看跌信号

### KDJ随机指标（超买超卖）
- **K值**: {kdj_k_str}
- **D值**: {kdj_d_str}
- **J值**: {kdj_j_str}
  * K > 80, D > 80：超买区域，可能回调（做空机会）
  * K < 20, D < 20：超卖区域，可能反弹（做多机会）
  * K线上穿D线（金叉）：看涨信号
  * K线下穿D线（死叉）：看跌信号
  * J值 > 100：极度超买，强烈看空
  * J值 < 0：极度超卖，强烈看多

### CCI商品通道指标
- **CCI值**: {cci_str}
  * CCI > 100：超买，可能回调
  * CCI < -100：超卖，可能反弹
  * CCI在+100到-100之间：震荡区间
  * CCI突破+100：强势上涨信号
  * CCI跌破-100：强势下跌信号

### OBV能量潮指标（量价关系）
- **OBV**: {obv_str}
- **OBV移动平均**: {obv_ma_str}
  * OBV上升 + 价格上涨：量价齐升，看涨
  * OBV下降 + 价格下跌：量价齐跌，看跌
  * OBV上升 + 价格下跌：量价背离，可能反弹
  * OBV下降 + 价格上涨：量价背离，可能回调
  * OBV突破OBV_MA：能量增强，趋势确认

### ATR平均真实波幅（波动率）
- **ATR**: {atr_str}
- **ATR百分比**: {atr_pct_str}
  * ATR高：市场波动大，风险高，止损范围应扩大
  * ATR低：市场波动小，风险低，止损范围可缩小
  * ATR上升：波动加剧，可能有大行情
  * ATR下降：波动收窄，可能酝酿突破

### ADX平均趋向指标（趋势强度）
- **ADX**: {adx_str}
- **+DI**: {plus_di_str}
- **-DI**: {minus_di_str}
  * ADX > 25：趋势强，适合趋势交易
  * ADX < 20：趋势弱，市场震荡
  * +DI > -DI：上升趋势，看涨
  * +DI < -DI：下降趋势，看跌
  * ADX上升 + +DI > -DI：上升趋势加强，强烈看涨
  * ADX上升 + +DI < -DI：下降趋势加强，强烈看跌

### 价格动量指标
- **10周期动量**: {momentum_str}
- **单周期价格变化**: {price_change_str}
- **波动率**: {volatility_str}
  * 动量 > 0：价格上涨动能
  * 动量 < 0：价格下跌动能
  * 波动率高：市场不确定性大，谨慎操作
  * 波动率低：市场稳定，适合交易

## 价格趋势分析
{price_trend}

## 量价关系分析
{volume_price_analysis}

## 做市商意图分析
{market_maker_analysis}

## 多时间周期分析
- **24小时（1D）趋势**: {trend_24h_str} | 强度: {strength_24h_str}
- **4小时趋势**: {trend_4h_str} | 强度: {strength_4h_str}
- **1小时趋势**: {trend_1h_str} | 强度: {strength_1h_str}
- **综合趋势**: {overall_trend_str} | 趋势强度: {trend_strength_str}
- **入场时机**: {entry_timing_str} | 入场方向: {entry_direction_str}
- **综合信心度**: {confidence_str}

**多周期分析解读**:
- 当多个周期趋势一致时，信号更强
- 大周期趋势决定方向，小周期决定入场时机
- 如果大周期上涨，小周期回调，是买入机会
- 如果大周期下跌，小周期反弹，是卖出（做空）机会

## ⚡ 前瞻性分析数据（优先级：最高 - 必须优先分析，比滞后指标更早捕捉价格变化）

**⚠️ 重要提示**：前瞻性指标（订单簿、订单流、成交量分布）比技术指标（MACD、RSI等）更早捕捉价格变化，**必须优先分析**。如果前瞻性指标和技术指标方向相反，**以前瞻性指标为主**。

{self._format_forward_analysis(market_data)}

## 📊 订单簿数据（实时买卖盘压力，优先级：最高）

**⚠️ 重要提示**：订单簿数据是实时数据，反映当前买卖盘压力，**必须优先分析**。

{self._format_orderbook_data(market_data)}

## 📈 最近成交记录（订单流分析，实际成交方向，优先级：最高）

**⚠️ 重要提示**：订单流数据反映实际成交方向，**必须优先分析**。

{self._format_recent_trades(market_data)}

## 资金面数据
{funding_json}

## 链上数据
{chain_json}

## 情绪数据
{sentiment_json}

## 📋 分析流程（按优先级顺序执行）

**分析顺序**：前瞻性指标 > 技术指标 > 量价关系 > 综合判断

### ⭐ 第一步：前瞻性指标分析（优先级最高，比滞后指标更早捕捉价格变化）
- **订单簿不平衡（OBI）**：
  * 买卖盘不平衡比例如何？买盘压力大还是卖盘压力大？
  * 不平衡比例是否显著（>0.2或<-0.2）？
  * 如果买盘压力显著，短期看涨；如果卖盘压力显著，短期看跌
- **订单流（Order Flow）**：
  * 最近的成交记录显示主动买入多还是主动卖出多？
  * 订单流方向与价格方向是否一致？
  * 如果订单流显示大量主动买入，但价格未涨，可能是建仓信号
  * 如果订单流显示大量主动卖出，但价格未跌，可能是出货信号
- **成交量分布（Volume Profile）**：
  * VWAP（成交量加权平均价）在哪里？
  * 当前价格相对于VWAP的位置如何？
  * 如果价格突破VWAP，可能继续上涨；如果跌破VWAP，可能继续下跌
- **订单簿深度**：
  * 买盘前5档总量与卖盘前5档总量的比例如何？
  * 如果买盘总量远大于卖盘总量（比例>1.3），看涨压力大
  * 如果卖盘总量远大于买盘总量（比例<0.77），看跌压力大
  * 大单集中在买盘还是卖盘？

### 第二步：技术指标分析（滞后指标，用于确认前瞻性信号）

**⚠️ 重要说明**：
- **技术指标是滞后指标**，主要用于确认前瞻性指标的信号强弱
- **如果前瞻性指标和技术指标方向一致**，信号更强，信心度更高
- **如果前瞻性指标和技术指标方向相反**，**必须以前瞻性指标为主**，因为前瞻性指标能更早捕捉价格变化
- **技术指标的作用是辅助确认**，不是主导决策，不要被技术指标误导

**分析要点**：

**需要分析的指标**：
- **MACD信号**：
  * 是否出现金叉/死叉？MACD_Hist的强度如何（绝对值越大趋势越强）？
  * MACD_Hist是否在增强（绝对值变大）还是减弱（绝对值变小）？
  * 如果MACD_Hist接近0，可能是趋势转换的信号
- **RSI信号**：
  * 是否超买/超卖？RSI的具体数值是多少（<25/30-40/40-60/60-70/>70）？
  * RSI的趋势如何（上升/下降/横盘）？
  * 如果RSI超卖但价格继续下跌，可能是假信号
- **KDJ信号**（随机指标，超买超卖）：
  * K值和D值是否在超买区（>80）或超卖区（<20）？
  * 是否出现KDJ金叉（K上穿D）或死叉（K下穿D）？
  * J值是否极度超买（>100）或极度超卖（<0）？
  * KDJ与RSI是否共振（同时超买或超卖）？
- **CCI信号**（商品通道指标）：
  * CCI是否突破+100（强势上涨）或跌破-100（强势下跌）？
  * CCI是否在震荡区间（-100到+100）？
  * CCI与价格是否背离？
- **OBV信号**（能量潮，量价关系）：
  * OBV趋势与价格趋势是否一致？
  * OBV是否突破OBV移动平均？
  * 是否存在量价背离（OBV上升但价格下跌，或OBV下降但价格上涨）？
- **ADX信号**（趋势强度）：
  * ADX是否大于25（趋势强）或小于20（趋势弱）？
  * +DI是否大于-DI（上升趋势）？
  * ADX是否在上升（趋势加强）？
  * 如果ADX低（<20），市场可能震荡，不适合趋势交易
- **ATR信号**（波动率）：
  * ATR是否较高（市场波动大，需要更大的止损范围）？
  * ATR是否在上升（波动加剧，可能有大行情）？
  * ATR是否在下降（波动收窄，可能酝酿突破）？
- **布林带信号**：
  * 价格在布林带的什么位置（0-10%/10-30%/30-70%/70-90%/90-100%）？
  * 是否触及上下轨？触及后是否反弹或继续突破？
  * 布林带宽度如何（收窄表示可能酝酿大波动）？
- **均线关系**：
  * 是否出现金叉/死叉？均线排列如何（多头排列/空头排列/混乱）？
  * 价格与均线的距离如何（距离越大可能回调）？
  * EMA12、EMA26、EMA50是否形成多头/空头排列？
- **价格动量**：
  * 10周期动量是否为正（价格上涨动能）？
  * 单周期价格变化幅度如何？
  * 波动率是否较高（市场不确定性大）？
- **多周期确认**：
  * 1小时、4小时、24小时趋势是否一致？
  * 如果不一致，哪个周期的信号更强？
  * 大周期趋势和小周期趋势的关系如何（大周期上涨+小周期回调=买入机会）？

### 第三步：量价关系和做市商意图分析（关键确认）

- **量价关系**（最关键的判断依据）：
  * 成交量与价格变化的关系如何？
  * **量价齐升**（价格上涨+成交量放大）：最健康的上涨信号，强烈看涨
  * **量价齐跌**（价格下跌+成交量放大）：强烈的下跌信号，适合做空
  * **价涨量缩**（价格上涨+成交量萎缩）：可能是假上涨，需要警惕，不建议追高
  * **价跌量缩**（价格下跌+成交量萎缩）：可能是最后一跌，可关注反弹机会
  * **价涨量平**（价格上涨+成交量不变）：可能乏力，谨慎做多
  * **价跌量平**（价格下跌+成交量不变）：可能继续下跌，谨慎做空
  * 成交量放大倍数如何（>1.5倍为显著放大）？
  
- **做市商意图**（订单簿分析最关键）：
  * 买盘和卖盘哪边更强？买卖盘比例是多少（>1.3为买盘强，<0.77为卖盘强）？
  * 大单集中在买盘还是卖盘？大单占比如何？
  * 价格附近（±1%）是否有强支撑或强压力？
  * 价差如何（价差大表示流动性差，可能出现大幅波动）？
  * **综合判断**：做市商是在看多还是看空？是否有大资金准备入场？
  
- **大单分析**（大资金动向）：
  * 大单集中在买盘还是卖盘？大单占买卖盘的比例？
  * 大单是否在关键价格位附近？
  * 大单的出现时机如何（上涨时大单买盘=真涨，下跌时大单卖盘=真跌）？
  
**重要提醒**：
- 如果技术指标看涨但做市商在看空（卖盘强），必须警惕，可能是诱多
- 如果技术指标看跌但做市商在看多（买盘强），必须警惕，可能是诱空
- 量价背离是最危险的信号，必须建议观望或谨慎操作

### 第四步：综合判断和交易决策

**综合判断要点**：
1. **趋势方向**：判断当前市场处于什么趋势（上涨/下跌/震荡/趋势不明）
2. **趋势强度**：趋势强度如何（强/中/弱）
3. **趋势持续性**：趋势持续性如何（可持续/可能反转/不确定）
4. **最佳入场点**：结合前瞻性指标、技术指标、量价关系，现在是好的入场时机吗？
5. **风险收益比**：当前入场的风险收益比如何？（必须≥1:2才建议入场，根据波动率动态调整）
6. **止损止盈**：根据市场波动率动态调整（低波动率：止损1.2%止盈2.5%，中等：止损1.5%止盈3%，高波动率：止损2%止盈4%）

**决策标准**：
**交易建议类型**（只能选择long或short，不允许hold）：
- **强烈买入（long）**：前瞻性指标+量价关系+技术指标三者一致，多周期趋势一致，风险收益比≥1:2（信心度>0.75，仓位5-8%）
  - **买入（long）**：前瞻性指标与量价关系至少两个同向，风险收益≥1:1.8（信心度≥0.65，仓位≤4%）
  - **谨慎买入（long）**：部分指标确认但噪音<0.4，风险收益≥1:2（信心度0.5-0.65，仓位≤2.5%）
  - **谨慎卖出（short）**：条件同上但方向相反
  - **卖出（short）**：前瞻性指标+量价关系共振（信心度≥0.65，仓位≤4%）
  - **强烈卖出（short）**：前瞻性+量价+做市商意图三者一致，且多周期一致（信心度≥0.8，仓位≤5%）
  - **观望（hold）**：信心度<0.5、噪音风险≥0.4、风险收益比不足1:1.8、关键价位未确认或宏观事件干扰；必须提供`avoid_reason`

**关键判断标准（必须严格遵守）**：
1. **多指标确认**：MACD、RSI、布林带、均线、多周期至少3个以上确认才给出强烈建议
2. **量价配合**：价格上涨必须配合成交量放大，价格下跌必须配合成交量放大，否则可能是假信号
3. **做市商意图**：订单簿分析显示做市商在看多/看空，这是重要的参考依据
4. **多周期一致性**：1小时、4小时、24小时趋势一致时信号更强
  5. **风险收益比**：只有风险收益比≥1:1.8且预计持仓时间<30分钟时才建议入场
  6. **信号矛盾时**：如果技术指标矛盾或量价背离，请返回hold并写出`avoid_reason`（例如“量价背离，等待成交量确认”）

**止损止盈要求**（根据市场波动率动态调整）：
  - **止损策略**：
    * 低波动率（ATR < 1%）：价格变动0.08%-0.12%（账户亏损≤1% @10x）
    * 中等波动率（1% ≤ ATR < 2%）：价格变动0.12%-0.18%
    * 高波动率（ATR ≥ 2%）：价格变动0.18%-0.25%
  - **止盈策略**：
    * 低波动率：价格变动0.15%-0.25%（账户盈利1.5%-2.5%）
    * 中等波动率：价格变动0.25%-0.35%
    * 高波动率：价格变动0.35%-0.45%
    * 强烈信号（信心度>0.8）：可分两档止盈（先锁利润后再看延伸）
  - **杠杆倍数**：默认≤5x，若建议使用更高杠杆必须说明原因和额外保护
  - **移动止损**：盈利>0.2%时移动止损到开仓价，盈利>0.35%时锁定至少一半利润
- **重要**：止损止盈根据市场波动率动态调整，避免被正常波动触发，同时控制风险

**特别强调**：
  - 不要只看到技术指标就给出建议，必须结合量价关系和做市商意图
  - 如果RSI超卖但成交量萎缩，可能是假反弹，请返回hold并写明条件
  - 如果MACD死叉但成交量放大，做空信号更强，但仍需评估噪音
  - 如果多个周期趋势不一致，必须谨慎，默认观望并提示需要的触发条件
  - 默认低杠杆运行，只有在噪音风险<0.3且信心度>0.8时才建议激进仓位

## 📤 输出格式（JSON - 必须严格遵守）

**🚨 关键要求**：必须返回**纯JSON格式**，不要包含任何markdown代码块标记（不要```json```或```），不要包含任何注释、解释性文字或额外内容。

**JSON格式示例（不要包含这些文字，只输出纯JSON）**：

  {{
      "direction": "long / short / hold",
      "entry_limit_price": 具体数字（若观望则为null；做多建议低于当前价格0.1-0.25%，做空建议高于0.1-0.25%）,
      "exit_limit_price": 具体数字（若观望则为null；做多建议高于entry 0.15%-0.45%，做空建议低于entry 0.15%-0.45%）,
    "trend": "上涨/下跌/震荡/趋势不明",
    "trend_strength": "强/中/弱",
    "trend_sustainability": "可持续/可能反转/不确定",
    "technical_signal": "强烈看涨/看涨/谨慎看涨/中性/谨慎看跌/看跌/强烈看跌",
    "macd_analysis": "MACD详细解读（包括是否金叉/死叉，强度如何）",
    "rsi_analysis": "RSI详细解读（是否超买超卖，趋势如何）",
    "bb_analysis": "布林带详细解读（价格位置，是否触及上下轨）",
    "volume_price_analysis": "量价关系详细解读（成交量与价格的关系，是否背离）",
    "market_maker_intent": "做市商意图详细解读（根据订单簿分析，做市商是在看多还是看空）",
    "entry_timing": "最佳入场时机/观望等待/不建议入场（综合考虑技术指标、量价关系和做市商意图）",
      "risk_reward_ratio": "风险收益比评估（必须≥1:1.8才建议入场）",
      "recommendation": "强烈买入/买入/谨慎买入/观望/谨慎卖出/卖出/强烈卖出",
    "confidence": 0.0-1.0之间的浮点数（信心度，基于信号确认程度）,
    "reasoning": "详细的交易理由和分析逻辑（至少200字）",
    "stop_loss_suggestion": "建议的止损位置（百分比或价格）",
    "take_profit_suggestion": "建议的止盈位置（百分比或价格）",
    "key_factors": ["关键因素1", "关键因素2", "关键因素3"],
      "entry_price_reason": "开仓限价的理由（为什么选择这个价格，至少50字）",
      "exit_price_reason": "平仓限价的理由（为什么选择这个价格，至少50字）",
      "noise_risk": 0.0-1.0之间的浮点数（噪音/突发反向风险，≥0.6必须观望）,
      "avoid_reason": "当direction=hold时必须说明原因；若方向明确但有隐患，也请写出主要风险",
      "entry_delay_seconds": 建议等待的秒数（0/60/120等，用于等待确认信号）,
      "strict_mode": true或false（只有在非常确定且允许立即执行时才设为true）,
      "confidence_breakdown": {
          "forward": 0-1之间浮点数,
          "technical": 0-1之间浮点数,
          "orderflow": 0-1之间浮点数
      }
}}

**⚠️ JSON格式要求（必须严格遵守，否则将导致交易失败）**：

**格式要求**：
1. 必须返回**纯JSON格式**，不要包含markdown代码块标记（不要```json```或```）
2. 所有字符串字段必须用双引号（"）
3. 数字字段必须是数字类型（不要用字符串）
4. 不要包含任何注释、解释性文字或额外内容
5. JSON必须完整且有效，可以被直接解析
6. 必须以{{开头，以}}结尾，中间是完整的JSON对象

  **⚠️ 关键要求（必须严格遵守，否则将导致交易失败）**：
  
  1. **direction字段**（必填）：
     - "long" / "short"：只有在风险收益比≥1:1.8、噪音风险<0.5、至少两个核心因子共振时才返回
     - "hold"：当前不建议入场。返回hold时必须提供 `avoid_reason`、`entry_delay_seconds`，并可附上触发条件
   
  2. **entry_limit_price字段**：
     - **做多时**：建议低于当前价格0.1-0.25%，以便在回调时买入，获得更好的入场价格，同时确保能够成交
     * 示例：当前价格50000 → entry_limit_price可以是49950（低于0.1%）或49850（低于0.3%）或49900（低于0.2%）
     * **重要**：不要设置过低（低于0.5%），否则可能无法成交；也不要设置过高（高于0.1%），否则可能失去最佳入场价格
     - **做空时**：建议高于当前价格0.1-0.25%，以便在反弹时卖出，获得更好的入场价格，同时确保能够成交
     * 示例：当前价格50000 → entry_limit_price可以是50050（高于0.1%）或50150（高于0.3%）或50100（高于0.2%）
     * **重要**：不要设置过高（高于0.5%），否则可能无法成交；也不要设置过低（低于0.1%），否则可能失去最佳入场价格
     - **direction=hold时请返回null**
   
  3. **exit_limit_price字段**：
     - **做多时**：建议高于entry_limit_price，目标价格变动0.15%-0.45%
       * 低波动率：entry_limit_price * (1 + 0.0015 ~ 0.0025)
       * 中等波动率：entry_limit_price * (1 + 0.0025 ~ 0.0035)
       * 高波动率：entry_limit_price * (1 + 0.0035 ~ 0.0045)
     - **做空时**：建议低于entry_limit_price，目标价格变动0.15%-0.45%
       * 低波动率：entry_limit_price * (1 - 0.0015 ~ 0.0025)
       * 中等波动率：entry_limit_price * (1 - 0.0025 ~ 0.0035)
       * 高波动率：entry_limit_price * (1 - 0.0035 ~ 0.0045)
     - **direction=hold时请返回null；若分批止盈，请给出最主要的一档目标**
     - **注意**：这是止盈目标价格，止损由系统根据市场波动率自动设置（账户盈亏≤2%，考虑杠杆倍数）
   
  4. **噪音评估与观望条件**：
     - 如果订单簿/订单流/量价任意两个维度出现冲突，或宏观事件造成异常波动，请返回"hold"
     - `noise_risk` ≥ 0.6 时必须观望；0.4-0.6 区间需要降低仓位并详细说明风险
     - 返回hold时必须填写 `avoid_reason`，并给出 `entry_delay_seconds` 或触发条件（如“突破MA20且成交量放大”）

5. **reasoning字段**（必须详细，至少200字）：
   - 必须包含：为什么选择这个方向（long/short/hold）以及关键依据
   - 必须包含：前瞻性指标的分析结果（订单簿、订单流、成交量分布）
   - 必须包含：技术指标的综合判断（MACD、RSI、KDJ、ADX等）
   - 必须包含：量价关系和做市商意图分析
   - 必须包含：为什么选择这个开仓价格（entry_limit_price）的理由
   - 必须包含：为什么选择这个平仓价格（exit_limit_price）的理由
   - 必须包含：风险收益比分析（必须≥1:2才建议入场，根据市场波动率动态调整止损止盈）

**🚨 JSON格式最终要求（最严格）**：
- **必须返回纯JSON格式**，不要包含任何markdown代码块标记（不要```json```或```）
- **必须直接以{{开头**，不要有任何前置文字
- **必须直接以}}结尾**，不要有任何后续文字
- 所有字符串字段必须用双引号（"）
- 数字字段必须是数字类型（不要用字符串）
- 不要包含任何注释、解释性文字或额外内容
- JSON必须完整且有效，可以被直接解析

**📝 正确输出示例（只输出这部分，不要包含其他任何文字）：**
{{"direction": "long", "entry_limit_price": 49750.0, "exit_limit_price": 49999.75, ...}}
（说明：entry_limit_price=49750.0，exit_limit_price=49750.0 * 1.005 = 49999.75，价格变动+0.5%，对应账户盈亏5%）

**❌ 错误输出示例（不要这样做）：**
```json
{{"direction": "long", ...}}
```
或者
JSON格式输出：
{{"direction": "long", ...}}

**🚨 最终提醒**：
- **direction只能返回"long"或"short"，不能返回"hold"**
- 如果信号不明确或矛盾，根据整体趋势选择long或short
- 如果风险收益比<1:2.5，仍然要选择long或short（可以选择更保守的开仓限价，但必须确保止损2%对应止盈5%）
- 如果前瞻性指标和技术指标严重矛盾，选择与前瞻性指标一致的方向
- 如果无法确定方向，优先选择与当前趋势一致的方向
- 必须给出具体的价格数字，不要用百分比或null
- **开仓限价必须合理**：做多时建议低于当前价格0.1-0.3%，做空时建议高于当前价格0.1-0.3%，确保能够成交并获得更好的入场价格
"""
        return prompt
    
    def _format_forward_analysis(self, market_data: Dict[str, Any]) -> str:
        """
        格式化前瞻性分析数据
        
        Args:
            market_data: 市场数据
            
        Returns:
            格式化后的文本
        """
        forward_analysis = market_data.get('forward_analysis', {})
        if not forward_analysis:
            return "**前瞻性分析数据**: 暂无数据"
        
        orderbook_imbalance = forward_analysis.get('orderbook_imbalance', {})
        orderflow = forward_analysis.get('orderflow', {})
        volume_profile = forward_analysis.get('volume_profile', {})
        
        text = []
        if orderbook_imbalance:
            text.append(f"""**订单簿不平衡（Order Book Imbalance）**：
- 不平衡比例: {orderbook_imbalance.get('imbalance_ratio', 'N/A')}
- 压力得分: {orderbook_imbalance.get('pressure_score', 'N/A')}
- 预测方向: {orderbook_imbalance.get('prediction', 'N/A')}
- 置信度: {orderbook_imbalance.get('confidence', 'N/A')}
- 解读: {orderbook_imbalance.get('reasoning', 'N/A')}""")
        
        if orderflow:
            text.append(f"""**订单流（Order Flow）**：
- 预测方向: {orderflow.get('prediction', 'N/A')}
- 置信度: {orderflow.get('confidence', 'N/A')}
- 解读: {orderflow.get('reasoning', 'N/A')}""")
        
        if volume_profile:
            text.append(f"""**成交量分布（Volume Profile）**：
- 预测方向: {volume_profile.get('prediction', 'N/A')}
- 置信度: {volume_profile.get('confidence', 'N/A')}
- VWAP: {volume_profile.get('vwap', 'N/A')}
- 解读: {volume_profile.get('reasoning', 'N/A')}""")
        
        return "\n\n".join(text) if text else "**前瞻性分析数据**: 暂无数据"
    
    def _format_orderbook_data(self, market_data: Dict[str, Any]) -> str:
        """
        格式化订单簿数据
        
        Args:
            market_data: 市场数据
            
        Returns:
            格式化后的文本
        """
        orderbook_data = market_data.get('orderbook', {})
        if not orderbook_data:
            return "**订单簿数据**: 暂无数据"
        
        bids = orderbook_data.get('bids', [])
        asks = orderbook_data.get('asks', [])
        
        if not bids or not asks:
            return "**订单簿数据**: 数据不完整"
        
        bid_volume_5 = sum([float(b[1]) for b in bids[:5]]) if bids else 0
        ask_volume_5 = sum([float(a[1]) for a in asks[:5]]) if asks else 0
        ratio = bid_volume_5 / ask_volume_5 if ask_volume_5 > 0 else 0
        
        # 在f-string外部序列化JSON，避免格式说明符问题
        bids_json = json.dumps(bids[:10], indent=2, ensure_ascii=False)
        asks_json = json.dumps(asks[:10], indent=2, ensure_ascii=False)
        
        return f"""**订单簿深度**：
- 买盘前5档总量: {bid_volume_5:.4f}
- 卖盘前5档总量: {ask_volume_5:.4f}
- 买卖盘比例: {ratio:.4f}
- 买盘前10档明细: {bids_json}
- 卖盘前10档明细: {asks_json}"""
    
    def _format_recent_trades(self, market_data: Dict[str, Any]) -> str:
        """
        格式化最近成交记录
        
        Args:
            market_data: 市场数据
            
        Returns:
            格式化后的文本
        """
        recent_trades = market_data.get('recent_trades', [])
        if not recent_trades:
            return "**最近成交记录**: 暂无数据"
        
        # 在f-string外部序列化JSON，避免格式说明符问题
        trades_json = json.dumps(recent_trades[:20], indent=2, ensure_ascii=False)
        
        return f"""**最近成交**（前20笔）：
{trades_json}"""
    
    def _request(self, messages: List[Dict[str, str]], retry: int = 0) -> Dict[str, Any]:
        """
        发送API请求
        
        Args:
            messages: 消息列表
            retry: 重试次数
            
        Returns:
            API响应数据
        """
        self._rate_limit()
        
        url = f"{self.base_url}/v1/chat/completions"
        headers = {
            'Authorization': f'Bearer {self.api_key}',
            'Content-Type': 'application/json'
        }
        
        data = {
            'model': self.model,
            'messages': messages,
            'temperature': self.temperature,
            'max_tokens': self.max_tokens
        }
        
        try:
            # 使用分别的连接超时和读取超时
            # 连接超时：建立连接的时间限制
            # 读取超时：等待响应的时间限制（AI响应可能需要较长时间）
            timeout_tuple = (self.connect_timeout, self.read_timeout)
            
            self.logger.debug(f"发送DeepSeek API请求，超时设置: 连接={self.connect_timeout}秒, 读取={self.read_timeout}秒")
            
            response = requests.post(
                url, 
                headers=headers, 
                json=data, 
                timeout=timeout_tuple,
                stream=False  # 不使用流式传输，避免超时问题
            )
            response.raise_for_status()
            result = response.json()
            
            return result.get('choices', [{}])[0].get('message', {}).get('content', '')
        
        except requests.exceptions.Timeout as e:
            # 超时错误：特别处理，增加重试延迟
            self.logger.warning(f"DeepSeek API请求超时 (第{retry + 1}次尝试): {e}")
            
            # 重试逻辑
            if retry < self.max_retries:
                # 超时错误使用更长的重试延迟（指数退避）
                delay = self.retry_delay * (2 ** retry) + 2  # 额外增加2秒
                self.logger.info(f"请求超时，重试请求 (第{retry + 2}次)，延迟{delay}秒...")
                time.sleep(delay)
                return self._request(messages, retry + 1)
            
            raise APIException(f"DeepSeek API请求超时，已重试{self.max_retries}次: {e}")
        
        except requests.exceptions.ConnectionError as e:
            # 连接错误：可能是网络问题
            self.logger.warning(f"DeepSeek API连接失败 (第{retry + 1}次尝试): {e}")
            
            # 重试逻辑
            if retry < self.max_retries:
                delay = self.retry_delay * (2 ** retry)
                self.logger.info(f"连接失败，重试请求 (第{retry + 2}次)，延迟{delay}秒...")
                time.sleep(delay)
                return self._request(messages, retry + 1)
            
            raise APIException(f"DeepSeek API连接失败，已重试{self.max_retries}次: {e}")
        
        except requests.exceptions.RequestException as e:
            # 其他请求错误
            self.logger.error(f"DeepSeek API请求失败 (第{retry + 1}次尝试): {e}")
            
            # 重试逻辑（对于某些错误不重试）
            # 4xx错误（客户端错误）通常不重试
            if hasattr(e, 'response') and e.response is not None:
                status_code = e.response.status_code
                if status_code == 402:
                    # 402 Payment Required - 账户需要付费，使用降级策略
                    # 导入 PaymentRequiredException（延迟导入避免循环依赖）
                    from ..core.exception import PaymentRequiredException
                    raise PaymentRequiredException(f"DeepSeek API需要付费 (402): {e}")
                elif 400 <= status_code < 500:
                    # 其他客户端错误，不重试
                    raise APIException(f"DeepSeek API客户端错误 ({status_code}): {e}")
            
            # 5xx错误或其他错误可以重试
            if retry < self.max_retries:
                delay = self.retry_delay * (2 ** retry)
                self.logger.info(f"请求失败，重试请求 (第{retry + 2}次)，延迟{delay}秒...")
                time.sleep(delay)
                return self._request(messages, retry + 1)
            
            raise APIException(f"DeepSeek API请求失败，已重试{self.max_retries}次: {e}")
    
    def _load_optimization_guidelines(self):
        """加载优化后的提示词指导原则"""
        # 确保属性已初始化
        if not hasattr(self, 'optimization_guidelines'):
            self.optimization_guidelines = []
        
        try:
            from ..learning.prompt_optimizer import PromptOptimizer
            optimizer = PromptOptimizer()
            guidelines = optimizer.get_current_guidelines()
            
            if guidelines:
                self.optimization_guidelines = guidelines
                self.logger.info(
                    f"[自学习] 加载了 {len(self.optimization_guidelines)} 条优化指导原则"
                )
                # 记录关键指导原则
                for guideline in self.optimization_guidelines[:5]:  # 只记录前5条
                    # 安全提取值，避免在f-string中使用.get()导致格式说明符错误
                    guideline_type = str(guideline.get('type', 'unknown'))
                    guideline_instruction = str(guideline.get('instruction', ''))[:100]
                    self.logger.debug(
                        f"[自学习指导原则] {guideline_type}: {guideline_instruction}"
                    )
            else:
                self.optimization_guidelines = []
        except Exception as e:
            self.logger.warning(f"加载优化指导原则失败: {e}")
            # 确保属性存在
            if not hasattr(self, 'optimization_guidelines'):
                self.optimization_guidelines = []
    
    def _apply_optimization_guidelines(self, prompt: str) -> str:
        """
        应用优化后的指导原则到提示词
        
        Args:
            prompt: 原始提示词
        
        Returns:
            应用优化后的提示词
        """
        # 确保属性存在
        if not hasattr(self, 'optimization_guidelines'):
            self.optimization_guidelines = []
            # 尝试加载一次
            try:
                self._load_optimization_guidelines()
            except Exception:
                pass
        
        if not self.optimization_guidelines:
            return prompt
        
        # 生成优化指导文本
        optimization_section = "\n## 历史交易经验总结（基于历史交易结果自动优化）\n\n"
        
        for guideline in self.optimization_guidelines:
            guideline_type = guideline.get('type', 'general')
            instruction = guideline.get('instruction', '')
            
            if guideline_type == 'confidence_threshold':
                optimization_section += f"**信心度要求**: {instruction}\n\n"
            elif guideline_type == 'emphasis':
                factors = guideline.get('factors', [])
                optimization_section += f"**重点考虑因素**: {instruction}\n\n"
            elif guideline_type == 'deemphasis':
                factors = guideline.get('factors', [])
                optimization_section += f"**谨慎因素**: {instruction}\n\n"
            elif guideline_type == 'recommendation_weight':
                rec = guideline.get('recommendation', '')
                optimization_section += f"**推荐类型调整**: {instruction}\n\n"
            else:
                optimization_section += f"**优化建议**: {instruction}\n\n"
        
        optimization_section += (
            "\n**重要**: 以上经验总结来自历史交易数据的统计分析，请在分析时综合考虑。\n\n"
        )
        
        # 在"分析要求"部分之前插入优化指导
        insert_position = prompt.find("## 分析要求")
        if insert_position > 0:
            prompt = prompt[:insert_position] + optimization_section + prompt[insert_position:]
        else:
            # 如果找不到位置，直接添加到末尾
            prompt += "\n\n" + optimization_section
        
        return prompt
    
    def _analyze_technical_indicators(self, indicators: Dict[str, Any], 
                                     kline_data: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
        """
        分析技术指标，生成信号解读
        
        Args:
            indicators: 技术指标数据
            kline_data: K线数据（可选）
        
        Returns:
            技术指标分析结果
        """
        analysis = {}
        
        # MACD信号解读
        macd = indicators.get('macd', 0)
        macd_signal = indicators.get('macd_signal', 0)
        macd_hist = indicators.get('macd_hist', 0)
        
        if macd and macd_signal:
            if macd > macd_signal and macd_hist > 0:
                if macd_hist > abs(macd) * 0.1:
                    analysis['macd_signal'] = '强烈看涨：MACD金叉且柱状图强劲'
                else:
                    analysis['macd_signal'] = '看涨：MACD金叉'
            elif macd < macd_signal and macd_hist < 0:
                if abs(macd_hist) > abs(macd) * 0.1:
                    analysis['macd_signal'] = '强烈看跌：MACD死叉且柱状图强劲'
                else:
                    analysis['macd_signal'] = '看跌：MACD死叉'
            else:
                analysis['macd_signal'] = '中性：MACD信号不明确'
        else:
            analysis['macd_signal'] = '数据不足'
        
        # RSI信号解读
        try:
            rsi = float(indicators.get('rsi', 50)) if indicators.get('rsi') is not None else 50.0
        except (ValueError, TypeError):
            rsi = 50.0
        
        if rsi < 30:
            analysis['rsi_signal'] = f'超卖：RSI={rsi:.2f}，可能出现反弹，买入机会'
            analysis['rsi_strength'] = '超卖'
        elif rsi > 70:
            analysis['rsi_signal'] = f'超买：RSI={rsi:.2f}，可能出现回调，卖出机会'
            analysis['rsi_strength'] = '超买'
        elif rsi < 40:
            analysis['rsi_signal'] = f'偏弱：RSI={rsi:.2f}，可能继续下跌或准备反弹'
            analysis['rsi_strength'] = '偏弱'
        elif rsi > 60:
            analysis['rsi_signal'] = f'偏强：RSI={rsi:.2f}，可能继续上涨或准备回调'
            analysis['rsi_strength'] = '偏强'
        else:
            analysis['rsi_signal'] = f'中性：RSI={rsi:.2f}，在正常区间'
            analysis['rsi_strength'] = '中性'
        
        # 布林带信号解读
        price = indicators.get('close', 0) or indicators.get('price', 0)
        bb_upper = indicators.get('bb_upper', 0)
        bb_middle = indicators.get('bb_middle', 0)
        bb_lower = indicators.get('bb_lower', 0)
        
        if price and bb_upper and bb_lower and bb_middle:
            try:
                price = float(price) if price is not None else 0.0
                bb_upper = float(bb_upper) if bb_upper is not None else 0.0
                bb_lower = float(bb_lower) if bb_lower is not None else 0.0
                bb_middle = float(bb_middle) if bb_middle is not None else 0.0
            except (ValueError, TypeError):
                price = 0.0
                bb_upper = 0.0
                bb_lower = 0.0
                bb_middle = 0.0
            
            bb_range = bb_upper - bb_lower
            if bb_range > 0:
                try:
                    bb_position = float((price - bb_lower) / bb_range) if bb_range > 0 else 0.0
                    bb_position_str = f'{bb_position:.2%}'
                    analysis['bb_position'] = f'{bb_position_str}（0%为下轨，100%为上轨）'
                except (ValueError, TypeError, ZeroDivisionError):
                    analysis['bb_position'] = 'N/A（0%为下轨，100%为上轨）'
                
                if bb_position < 0.1:
                    analysis['bb_signal'] = '触及下轨：可能超卖，关注反弹机会'
                elif bb_position > 0.9:
                    analysis['bb_signal'] = '触及上轨：可能超买，关注回调风险'
                elif bb_position < 0.3:
                    analysis['bb_signal'] = '下轨附近：偏弱，谨慎做多'
                elif bb_position > 0.7:
                    analysis['bb_signal'] = '上轨附近：偏强，谨慎做空'
                else:
                    analysis['bb_signal'] = '中轨附近：中性区域'
            else:
                analysis['bb_position'] = 'N/A'
                analysis['bb_signal'] = '数据不足'
        else:
            analysis['bb_position'] = 'N/A'
            analysis['bb_signal'] = '数据不足'
        
        # 均线关系
        ma_5 = indicators.get('ma_5', 0)
        ma_20 = indicators.get('ma_20', 0)
        
        if ma_5 and ma_20:
            if ma_5 > ma_20:
                ma_diff = (ma_5 - ma_20) / ma_20 * 100
                if ma_diff > 2:
                    analysis['ma_relationship'] = f'强烈看涨：5日均线明显高于20日均线({ma_diff:.2f}%)'
                else:
                    analysis['ma_relationship'] = f'看涨：5日均线高于20日均线({ma_diff:.2f}%)'
            elif ma_5 < ma_20:
                ma_diff = (ma_20 - ma_5) / ma_20 * 100
                if ma_diff > 2:
                    analysis['ma_relationship'] = f'强烈看跌：5日均线明显低于20日均线({ma_diff:.2f}%)'
                else:
                    analysis['ma_relationship'] = f'看跌：5日均线低于20日均线({ma_diff:.2f}%)'
            else:
                analysis['ma_relationship'] = '中性：均线接近'
        else:
            analysis['ma_relationship'] = '数据不足'
        
        return analysis
    
    def _extract_price_trend(self, kline_data: Optional[List[Dict[str, Any]]]) -> str:
        """
        提取价格趋势信息
        
        Args:
            kline_data: K线数据
        
        Returns:
            价格趋势分析文本
        """
        if not kline_data or len(kline_data) < 10:
            return "数据不足，无法分析价格趋势"
        
        try:
            # 获取最近10根K线
            recent_kline = kline_data[-10:]
            
            # 计算价格变化
            first_close = float(recent_kline[0].get('close', 0))
            last_close = float(recent_kline[-1].get('close', 0))
            
            if first_close > 0:
                price_change_pct = ((last_close - first_close) / first_close) * 100
                
                # 计算波动性
                highs = [float(k.get('high', 0)) for k in recent_kline]
                lows = [float(k.get('low', 0)) for k in recent_kline]
                volatility = (max(highs) - min(lows)) / first_close * 100 if max(highs) > min(lows) else 0
                
                # 确保值是数字类型，避免格式说明符错误
                try:
                    price_change_pct = float(price_change_pct) if price_change_pct is not None else 0.0
                    volatility = float(volatility) if volatility is not None else 0.0
                    max_high = float(max(highs)) if highs else 0.0
                    min_low = float(min(lows)) if lows else 0.0
                except (ValueError, TypeError):
                    price_change_pct = 0.0
                    volatility = 0.0
                    max_high = 0.0
                    min_low = 0.0
                
                # 判断趋势方向
                if price_change_pct > 2:
                    trend_direction = "明显上涨"
                elif price_change_pct > 0.5:
                    trend_direction = "小幅上涨"
                elif price_change_pct < -2:
                    trend_direction = "明显下跌"
                elif price_change_pct < -0.5:
                    trend_direction = "小幅下跌"
                else:
                    trend_direction = "震荡整理"
                
                # 格式化数值，避免在f-string中使用复杂表达式
                price_change_str = f"{price_change_pct:.2f}%"
                volatility_str = f"{volatility:.2f}%"
                max_high_str = f"{max_high:.2f}"
                min_low_str = f"{min_low:.2f}"
                
                # 判断趋势
                if price_change_pct > 1:
                    trend_judgment = "上涨趋势"
                elif price_change_pct < -1:
                    trend_judgment = "下跌趋势"
                else:
                    trend_judgment = "震荡整理"
                
                return f"""
**最近10根K线价格趋势**:
- 价格变化: {price_change_str} ({trend_direction})
- 波动范围: {max_high_str} - {min_low_str}
- 波动率: {volatility_str}
- 趋势判断: {trend_judgment}
"""
            else:
                return "价格数据无效"
        except Exception as e:
            self.logger.error(f"提取价格趋势失败: {e}")
            return "价格趋势分析失败"
    
    def _extract_volume_price_relationship(self, kline_data: Optional[List[Dict[str, Any]]]) -> str:
        """
        提取量价关系分析
        
        Args:
            kline_data: K线数据
        
        Returns:
            量价关系分析文本
        """
        if not kline_data or len(kline_data) < 10:
            return "数据不足，无法分析量价关系"
        
        try:
            # 获取最近10根K线
            recent_kline = kline_data[-10:]
            
            # 计算平均成交量
            volumes = [float(k.get('volume', 0)) for k in recent_kline]
            avg_volume = sum(volumes) / len(volumes) if volumes else 0
            
            # 计算最近5根和之前5根的平均成交量和价格变化
            recent_5_vol = sum(volumes[-5:]) / 5 if len(volumes) >= 5 else 0
            prev_5_vol = sum(volumes[:5]) / 5 if len(volumes) >= 5 else avg_volume
            
            recent_5_prices = [float(k.get('close', 0)) for k in recent_kline[-5:]]
            prev_5_prices = [float(k.get('close', 0)) for k in recent_kline[:5]]
            
            recent_5_change = ((recent_5_prices[-1] - recent_5_prices[0]) / recent_5_prices[0] * 100) if recent_5_prices[0] > 0 else 0
            volume_change_pct = ((recent_5_vol - prev_5_vol) / prev_5_vol * 100) if prev_5_vol > 0 else 0
            
            # 确保值是数字类型，避免格式说明符错误
            try:
                recent_5_change = float(recent_5_change) if recent_5_change is not None else 0.0
                volume_change_pct = float(volume_change_pct) if volume_change_pct is not None else 0.0
            except (ValueError, TypeError):
                recent_5_change = 0.0
                volume_change_pct = 0.0
            
            # 量价关系判断
            if volume_change_pct > 20 and recent_5_change > 0:
                relationship = "量价齐升：成交量放大且价格上涨，看涨信号强"
            elif volume_change_pct > 20 and recent_5_change < 0:
                relationship = "放量下跌：成交量放大但价格下跌，看跌信号强"
            elif volume_change_pct < -20 and recent_5_change > 0:
                relationship = "缩量上涨：成交量萎缩但价格上涨，可能乏力"
            elif volume_change_pct < -20 and recent_5_change < 0:
                relationship = "缩量下跌：成交量萎缩且价格下跌，可能企稳"
            elif recent_5_change > 0:
                relationship = "价涨量平：价格上涨但成交量变化不大"
            elif recent_5_change < 0:
                relationship = "价跌量平：价格下跌但成交量变化不大"
            else:
                relationship = "量价平衡：价格和成交量变化都不明显"
            
            # 格式化数值，避免在f-string中使用复杂表达式
            volume_change_str = f"{volume_change_pct:.2f}%"
            recent_5_change_str = f"{recent_5_change:.2f}%"
            
            return f"""
**量价关系分析（最关键的分析）**:
- 近期平均成交量变化: {volume_change_str}（>20%为放大，<-20%为萎缩）
- 近期价格变化: {recent_5_change_str}（>1%为明显上涨，<-1%为明显下跌）
- 量价关系: {relationship}

**量价关系详细解读（必须严格遵循）**:
1. **量价齐升（成交量放大+价格上涨）**：
   - 这是最健康的上涨信号，强烈看涨，适合做多
   - 成交量放大倍数越大，上涨信号越强
   - 如果成交量放大>50%且价格上涨>1%，这是强烈做多信号

2. **放量下跌（成交量放大+价格下跌）**：
   - 这是强烈的看跌信号，强烈看空，适合做空
   - 成交量放大倍数越大，下跌信号越强
   - 如果成交量放大>50%且价格下跌<-1%，这是强烈做空信号

3. **缩量上涨（成交量萎缩+价格上涨）**：
   - ⚠️ 这是危险的信号，可能是假上涨或诱多
   - 成交量萎缩<-20%但价格上涨，可能是乏力，不建议追高
   - 如果成交量萎缩<-30%且价格上涨>0.5%，强烈建议观望，不要做多

4. **缩量下跌（成交量萎缩+价格下跌）**：
   - 这可能是最后一跌或洗盘，可关注反弹机会
   - 成交量大幅萎缩<-30%且价格下跌，可能是空方力量衰竭，可关注反弹

5. **价涨量平/价跌量平**：
   - 价格变化明显但成交量不变，信号不够强烈
   - 需要配合其他指标确认，谨慎操作

**量价关系交易决策**：
- ✅ 量价齐升 + 技术指标看涨 = 强烈做多信号
- ✅ 放量下跌 + 技术指标看跌 = 强烈做空信号
- ❌ 缩量上涨 + 技术指标看涨 = 假信号，不建议做多，建议观望
- ❌ 量价背离 = 危险信号，必须建议观望或谨慎操作
- ⚠️ 量价关系必须与技术指标和多周期分析结合，不能孤立判断
"""
        except Exception as e:
            self.logger.error(f"提取量价关系失败: {e}")
            return "量价关系分析失败"
    
    def _analyze_market_maker_intent(self, orderbook_data: Dict[str, Any], 
                                     current_price: float) -> str:
        """
        分析做市商意图（基于订单簿数据）
        
        Args:
            orderbook_data: 订单簿数据
            current_price: 当前价格
        
        Returns:
            做市商意图分析文本
        """
        if not orderbook_data or not current_price or current_price <= 0:
            return "数据不足，无法分析做市商意图"
        
        try:
            bids = orderbook_data.get('bids', [])
            asks = orderbook_data.get('asks', [])
            
            if not bids or not asks:
                return "订单簿数据不足，无法分析做市商意图"
            
            # 分析买卖盘压力
            bid_volume = sum([float(bid[1]) for bid in bids if len(bid) >= 2])  # 买盘总量
            ask_volume = sum([float(ask[1]) for ask in asks if len(ask) >= 2])  # 卖盘总量
            
            bid_ask_ratio = bid_volume / ask_volume if ask_volume > 0 else 1.0
            
            # 分析大单分布（超过平均订单大小的2倍视为大单）
            avg_bid_size = bid_volume / len(bids) if bids else 0
            avg_ask_size = ask_volume / len(asks) if asks else 0
            
            large_bids = [bid for bid in bids if len(bid) >= 2 and float(bid[1]) > avg_bid_size * 2]
            large_asks = [ask for ask in asks if len(ask) >= 2 and float(ask[1]) > avg_ask_size * 2]
            
            large_bid_volume = sum([float(bid[1]) for bid in large_bids])
            large_ask_volume = sum([float(ask[1]) for ask in large_asks])
            
            # 计算价格距离（距离当前价格最近的订单）
            best_bid_price = float(bids[0][0]) if bids and len(bids[0]) >= 1 else current_price
            best_ask_price = float(asks[0][0]) if asks and len(asks[0]) >= 1 else current_price
            spread = best_ask_price - best_bid_price
            spread_pct = (spread / current_price * 100) if current_price > 0 else 0
            
            # 分析订单簿深度（价格区间内的订单分布）
            # 买盘：距离当前价格-1%到当前价格的订单
            # 卖盘：距离当前价格到当前价格+1%的订单
            bid_range_volume = sum([
                float(bid[1]) for bid in bids 
                if len(bid) >= 1 and (current_price - float(bid[0])) / current_price <= 0.01
            ])
            ask_range_volume = sum([
                float(ask[1]) for ask in asks 
                if len(ask) >= 1 and (float(ask[0]) - current_price) / current_price <= 0.01
            ])
            
            # 分析做市商挂单模式
            # 1. 买卖盘平衡性
            if bid_ask_ratio > 1.5:
                balance_signal = "买盘明显强于卖盘，可能上涨"
            elif bid_ask_ratio > 1.2:
                balance_signal = "买盘略强于卖盘，偏多"
            elif bid_ask_ratio < 0.67:
                balance_signal = "卖盘明显强于买盘，可能下跌"
            elif bid_ask_ratio < 0.83:
                balance_signal = "卖盘略强于买盘，偏空"
            else:
                balance_signal = "买卖盘相对平衡"
            
            # 2. 大单分析
            large_order_bias = ""
            if large_bid_volume > large_ask_volume * 1.5:
                large_order_bias = "大单集中在买盘，可能有大资金准备买入"
            elif large_ask_volume > large_bid_volume * 1.5:
                large_order_bias = "大单集中在卖盘，可能有大资金准备卖出"
            else:
                large_order_bias = "大单分布相对均衡"
            
            # 3. 价格附近压力分析
            near_pressure = ""
            if bid_range_volume > ask_range_volume * 1.3:
                near_pressure = "价格附近买盘支撑强，下跌阻力大"
            elif ask_range_volume > bid_range_volume * 1.3:
                near_pressure = "价格附近卖盘压力大，上涨阻力强"
            else:
                near_pressure = "价格附近买卖盘相对均衡"
            
            # 4. 价差分析（spread）
            spread_analysis = ""
            try:
                spread_pct_float = float(spread_pct) if spread_pct is not None else 0.0
            except (ValueError, TypeError):
                spread_pct_float = 0.0
            
            if spread_pct_float > 0.1:
                spread_pct_str = f"{spread_pct_float:.3f}%"
                spread_analysis = f"价差较大({spread_pct_str})，流动性较差，可能出现大幅波动"
            elif spread_pct_float < 0.01:
                spread_pct_str = f"{spread_pct_float:.3f}%"
                spread_analysis = f"价差很小({spread_pct_str})，流动性良好，价格稳定"
            else:
                spread_pct_str = f"{spread_pct_float:.3f}%"
                spread_analysis = f"价差正常({spread_pct_str})，流动性一般"
            
            # 5. 做市商意图综合判断
            intent = ""
            if bid_ask_ratio > 1.3 and large_bid_volume > large_ask_volume and bid_range_volume > ask_range_volume:
                intent = "做市商可能在看多：买盘强、大单买盘多、价格附近买盘支撑强"
            elif bid_ask_ratio < 0.77 and large_ask_volume > large_bid_volume and ask_range_volume > bid_range_volume:
                intent = "做市商可能在看空：卖盘强、大单卖盘多、价格附近卖盘压力大"
            elif bid_ask_ratio > 1.2 and bid_range_volume > ask_range_volume:
                intent = "做市商可能准备拉升：买盘略强且价格附近有买盘支撑"
            elif bid_ask_ratio < 0.83 and ask_range_volume > bid_range_volume:
                intent = "做市商可能准备打压：卖盘略强且价格附近有卖盘压力"
            else:
                intent = "做市商意图不明确，市场处于平衡状态"
            
            # 确保所有数值是数字类型，避免格式说明符错误
            try:
                best_bid_price = float(best_bid_price) if best_bid_price is not None else 0.0
                best_ask_price = float(best_ask_price) if best_ask_price is not None else 0.0
                spread = float(spread) if spread is not None else 0.0
                spread_pct = float(spread_pct) if spread_pct is not None else 0.0
                bid_volume = float(bid_volume) if bid_volume is not None else 0.0
                ask_volume = float(ask_volume) if ask_volume is not None else 0.0
                bid_ask_ratio = float(bid_ask_ratio) if bid_ask_ratio is not None else 1.0
                large_bid_volume = float(large_bid_volume) if large_bid_volume is not None else 0.0
                large_ask_volume = float(large_ask_volume) if large_ask_volume is not None else 0.0
                bid_range_volume = float(bid_range_volume) if bid_range_volume is not None else 0.0
                ask_range_volume = float(ask_range_volume) if ask_range_volume is not None else 0.0
            except (ValueError, TypeError):
                best_bid_price = 0.0
                best_ask_price = 0.0
                spread = 0.0
                spread_pct = 0.0
                bid_volume = 0.0
                ask_volume = 0.0
                bid_ask_ratio = 1.0
                large_bid_volume = 0.0
                large_ask_volume = 0.0
                bid_range_volume = 0.0
                ask_range_volume = 0.0
            
            # 格式化数值，避免在f-string中使用复杂表达式
            best_bid_price_str = f"{best_bid_price:.4f}"
            best_ask_price_str = f"{best_ask_price:.4f}"
            spread_str = f"{spread:.4f}"
            spread_pct_str = f"{spread_pct:.3f}%"
            bid_volume_str = f"{bid_volume:.2f}"
            ask_volume_str = f"{ask_volume:.2f}"
            bid_ask_ratio_str = f"{bid_ask_ratio:.2f}"
            large_bid_volume_str = f"{large_bid_volume:.2f}"
            large_ask_volume_str = f"{large_ask_volume:.2f}"
            bid_range_volume_str = f"{bid_range_volume:.2f}"
            ask_range_volume_str = f"{ask_range_volume:.2f}"
            
            return f"""
**订单簿数据**:
- 最佳买价: {best_bid_price_str} | 最佳卖价: {best_ask_price_str}
- 买卖价差: {spread_str} ({spread_pct_str})
- 买盘总量: {bid_volume_str} | 卖盘总量: {ask_volume_str}
- 买卖盘比例: {bid_ask_ratio_str}（>1表示买盘强，<1表示卖盘强）
- 大单买盘: {large_bid_volume_str} | 大单卖盘: {large_ask_volume_str}
- 价格附近买盘(-1%): {bid_range_volume_str} | 价格附近卖盘(+1%): {ask_range_volume_str}

**做市商意图分析**:
- 买卖盘平衡性: {balance_signal}
- 大单分布: {large_order_bias}
- 价格附近压力: {near_pressure}
- 价差分析: {spread_analysis}
- **综合判断**: {intent}

**做市商意图详细解读（关键参考依据）**:
1. **做市商看多（买盘强+大单买盘多+价格附近买盘支撑强）**：
   - 可能准备拉升价格，或防止价格下跌
   - 这是重要的看多信号，可以配合技术指标做多
   - 如果技术指标也看涨，这是强烈做多信号

2. **做市商看空（卖盘强+大单卖盘多+价格附近卖盘压力大）**：
   - 可能准备打压价格，或防止价格上涨
   - 这是重要的看空信号，可以配合技术指标做空
   - 如果技术指标也看跌，这是强烈做空信号

3. **买卖盘平衡 + 价差小**：
   - 市场稳定，做市商在维护流动性
   - 可能横盘整理，建议观望或小仓位试探

4. **价差大 + 订单稀疏**：
   - 流动性差，可能出现大幅波动
   - 风险较高，谨慎操作，建议小仓位或观望

**做市商意图交易决策**：
- ✅ 做市商看多 + 技术指标看涨 + 量价齐升 = 强烈做多信号
- ✅ 做市商看空 + 技术指标看跌 + 放量下跌 = 强烈做空信号
- ⚠️ 做市商看多但技术指标看跌 = 信号矛盾，建议观望
- ⚠️ 做市商看空但技术指标看涨 = 信号矛盾，建议观望
- ❌ 做市商意图与技术指标完全相反 = 危险信号，必须建议观望

**重要提醒**：
- 做市商意图是市场真实意图的重要体现，必须重视
- 如果技术指标看涨但做市商在看空，可能是诱多，必须警惕
- 如果技术指标看跌但做市商在看多，可能是诱空，必须警惕
"""
        except Exception as e:
            self.logger.error(f"分析做市商意图失败: {e}")
            return f"做市商意图分析失败: {e}"
    
    def analyze_market(self, market_data: Dict[str, Any], 
                       signal_context: Dict[str, Any] = None) -> Dict[str, Any]:
        """
        市场分析
        
        Args:
            market_data: 市场数据
            signal_context: 信号上下文
            
        Returns:
            分析结果
        """
        if signal_context is None:
            signal_context = {}
        
        # 记录分析请求
        symbol = market_data.get('symbol', 'UNKNOWN')
        price = market_data.get('price', 'N/A')
        change_24h_raw = market_data.get('change_24h', 'N/A')
        # 安全格式化change_24h，避免格式说明符错误
        try:
            if change_24h_raw != 'N/A' and change_24h_raw is not None:
                try:
                    change_24h_float = float(change_24h_raw)
                    change_24h_str = f"{change_24h_float:.2f}%"
                except (ValueError, TypeError):
                    # 如果不是数字，直接转换为字符串，确保安全
                    change_24h_safe = str(change_24h_raw).replace('{', '{{').replace('}', '}}')
                    change_24h_str = f"{change_24h_safe}%"
            else:
                change_24h_safe = str(change_24h_raw).replace('{', '{{').replace('}', '}}')
                change_24h_str = f"{change_24h_safe}%"
        except Exception:
            # 如果所有转换都失败，使用安全的默认值
            change_24h_str = "N/A"
        self.logger.info(f"[DeepSeek分析] 开始市场分析 - 交易对: {symbol}, 价格: {price}, 24h涨跌: {change_24h_str}")
        if signal_context:
            task = signal_context.get('task', 'market_analysis')
            self.logger.debug(f"[DeepSeek分析] 任务类型: {task}, 上下文: {signal_context}")
        
        prompt = self._build_prompt(market_data, signal_context)
        
        # 应用优化后的指导原则
        prompt = self._apply_optimization_guidelines(prompt)
        
        messages = [
            {
                'role': 'system',
                'content': '你是一位专业的加密货币交易分析师，擅长多维度分析和市场微观结构解读。'
            },
            {
                'role': 'user',
                'content': prompt
            }
        ]
        
        try:
            response_text = self._request(messages)
            
            # 尝试解析JSON响应
            try:
                # 提取JSON部分（如果响应包含其他文本）
                import re
                json_match = re.search(r'\{.*\}', response_text, re.DOTALL)
                if json_match:
                    response_text = json_match.group(0)
                
                result = json.loads(response_text)
                
                # 提取方向、开仓限价、平仓限价（添加类型检查和转换）
                def _safe_float(value, default=None):
                    if value is None:
                        return default
                    if isinstance(value, (int, float)):
                        return float(value)
                    if isinstance(value, dict):
                        inner_val = value.get('value')
                        return _safe_float(inner_val, default)
                    try:
                        return float(value)
                    except (TypeError, ValueError):
                        return default
                
                def _safe_int(value, default=None):
                    if value is None:
                        return default
                    if isinstance(value, int):
                        return value
                    try:
                        return int(float(value))
                    except (TypeError, ValueError):
                        return default
                
                def _safe_str(value, default=''):
                    if value is None:
                        return default
                    if isinstance(value, str):
                        return value
                    try:
                        return str(value)
                    except Exception:
                        return default
                
                direction_raw = result.get('direction', 'hold')
                # 确保direction是字符串类型，避免类型错误
                if isinstance(direction_raw, dict):
                    direction = str(direction_raw.get('value', direction_raw)).lower() if isinstance(direction_raw.get('value', None), str) else 'hold'
                elif not isinstance(direction_raw, str):
                    direction = str(direction_raw).lower() if direction_raw is not None else 'hold'
                else:
                    direction = direction_raw.lower()
                
                entry_limit_price = _safe_float(result.get('entry_limit_price'), None)
                exit_limit_price = _safe_float(result.get('exit_limit_price'), None)
                
                # 记录分析结果（添加类型检查和转换）
                recommendation = _safe_str(result.get('recommendation', 'unknown'), 'unknown')
                confidence = _safe_float(result.get('confidence', 0.0), 0.0) or 0.0
                trend = _safe_str(result.get('trend', 'N/A'), 'N/A')
                reasoning_raw = result.get('reasoning', '')
                reasoning = _safe_str(reasoning_raw, '')
                reasoning = reasoning[:200]  # 只记录前200字符，避免日志过长
                noise_risk = _safe_float(result.get('noise_risk'), None)
                avoid_reason = _safe_str(result.get('avoid_reason'))
                entry_delay_seconds = _safe_int(result.get('entry_delay_seconds'), None)
                strict_mode = bool(result.get('strict_mode', False))
                confidence_breakdown = result.get('confidence_breakdown') or {}
                
                # 确保所有数值都是数字类型，避免格式说明符错误
                entry_limit_price_float = entry_limit_price if entry_limit_price is not None else None
                exit_limit_price_float = exit_limit_price if exit_limit_price is not None else None
                confidence_float = confidence if confidence is not None else 0.0
                
                # 格式化数值，避免在f-string中使用格式说明符
                entry_limit_price_str = f"{entry_limit_price_float:.5f}" if entry_limit_price_float is not None else 'N/A'
                exit_limit_price_str = f"{exit_limit_price_float:.5f}" if exit_limit_price_float is not None else 'N/A'
                confidence_str_log = f"{confidence_float:.2f}"
                
                # 记录方向、限价信息
                if direction in ['long', 'short']:
                    self.logger.info(
                        f"[DeepSeek分析结果] 交易对: {symbol} | "
                        f"方向: {'做多' if direction == 'long' else '做空'} | "
                        f"开仓限价: {entry_limit_price_str} | "
                        f"平仓限价: {exit_limit_price_str} | "
                        f"建议: {recommendation} | "
                        f"趋势: {trend} | "
                        f"信心度: {confidence_str_log}"
                    )
                else:
                    self.logger.info(
                        f"[DeepSeek分析结果] 交易对: {symbol} | "
                        f"建议: {recommendation} | "
                        f"趋势: {trend} | "
                        f"信心度: {confidence_str_log} | "
                        f"原因: {avoid_reason or '未提供'}"
                    )
                
                # 更新result字典，确保所有字段都是正确的类型
                result['direction'] = direction
                result['entry_limit_price'] = entry_limit_price
                result['exit_limit_price'] = exit_limit_price
                result['recommendation'] = recommendation
                result['confidence'] = confidence
                result['trend'] = trend
                result['reasoning'] = reasoning
                result['noise_risk'] = noise_risk
                result['avoid_reason'] = avoid_reason
                result['entry_delay_seconds'] = entry_delay_seconds
                result['strict_mode'] = strict_mode
                result['confidence_breakdown'] = confidence_breakdown
                
                # 记录详细的分析结果（包含完整推理过程）
                self.logger.debug(f"[DeepSeek分析详情] 交易对: {symbol}")
                self.logger.debug(f"[DeepSeek分析详情] 完整结果: {json.dumps(self._serialize_for_json(result), indent=2, ensure_ascii=False)}")
                
                # 单独记录DeepSeek的返回结果
                self._record_deepseek_response(symbol, market_data, response_text, result)
                
                return result
            except json.JSONDecodeError:
                # 如果不是JSON格式，返回原始文本
                self.logger.warning(f"[DeepSeek分析] 交易对: {symbol} - DeepSeek返回非JSON格式，返回原始文本")
                self.logger.debug(f"[DeepSeek分析] 原始响应: {response_text[:500]}")  # 只记录前500字符
                
                # 即使解析失败，也记录原始响应
                error_result = {
                    'recommendation': 'unknown',
                    'reasoning': response_text
                }
                self._record_deepseek_response(symbol, market_data, response_text, error_result)
                
                return error_result
        
        except Exception as e:
            self.logger.error(f"[DeepSeek分析] 交易对: {symbol} - 市场分析失败: {e}")
            raise APIException(f"市场分析失败: {e}")
    
    def generate_signal(self, market_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        生成交易信号
        
        Args:
            market_data: 市场数据
            
        Returns:
            交易信号
        """
        symbol = market_data.get('symbol', 'UNKNOWN')
        self.logger.info(f"[DeepSeek信号生成] 开始生成交易信号 - 交易对: {symbol}")
        
        signal_context = {
            'task': 'signal_generation',
            'focus': '交易信号生成'
        }
        
        try:
            analysis = self.analyze_market(market_data, signal_context)
        except Exception as e:
            self.logger.error(f"[DeepSeek信号生成] 分析市场失败 {symbol}: {e}", exc_info=True)
            raise
        
        # 提取方向、开仓限价、平仓限价
        try:
            direction_raw = analysis.get('direction', 'hold')
            # 确保direction是字符串类型，避免类型错误
            if isinstance(direction_raw, dict):
                # 如果direction是字典，尝试提取其中的字符串值或转换为字符串
                direction = str(direction_raw.get('value', direction_raw)).lower() if isinstance(direction_raw.get('value', None), str) else 'hold'
            elif not isinstance(direction_raw, str):
                direction = str(direction_raw).lower() if direction_raw is not None else 'hold'
            else:
                direction = direction_raw.lower()
        except Exception as e:
            self.logger.error(f"[DeepSeek信号生成] 处理direction字段失败 {symbol}: {e}, direction_raw类型: {type(direction_raw)}, 值: {direction_raw}", exc_info=True)
            direction = 'hold'
        
        entry_limit_price = analysis.get('entry_limit_price', 0)
        exit_limit_price = analysis.get('exit_limit_price', 0)
        
        # 确保entry_limit_price和exit_limit_price是数字类型
        if isinstance(entry_limit_price, dict):
            entry_limit_price = float(entry_limit_price.get('value', 0)) if isinstance(entry_limit_price.get('value', None), (int, float)) else 0
        elif not isinstance(entry_limit_price, (int, float)):
            try:
                entry_limit_price = float(entry_limit_price) if entry_limit_price is not None else 0
            except (ValueError, TypeError):
                entry_limit_price = 0
        
        if isinstance(exit_limit_price, dict):
            exit_limit_price = float(exit_limit_price.get('value', 0)) if isinstance(exit_limit_price.get('value', None), (int, float)) else 0
        elif not isinstance(exit_limit_price, (int, float)):
            try:
                exit_limit_price = float(exit_limit_price) if exit_limit_price is not None else 0
            except (ValueError, TypeError):
                exit_limit_price = 0
        
        # 将分析结果转换为信号
        recommendation = analysis.get('recommendation', 'unknown')
        confidence = analysis.get('confidence', 0.5)
        
        # 确保recommendation是字符串类型，避免类型错误
        if isinstance(recommendation, dict):
            # 如果recommendation是字典，尝试转换为字符串
            recommendation = str(recommendation)
        elif not isinstance(recommendation, str):
            recommendation = str(recommendation) if recommendation is not None else 'unknown'
        
        # 确保confidence是数字类型
        if isinstance(confidence, dict):
            confidence = float(confidence.get('value', 0.5)) if isinstance(confidence.get('value', None), (int, float)) else 0.5
        elif not isinstance(confidence, (int, float)):
            try:
                confidence = float(confidence) if confidence is not None else 0.5
            except (ValueError, TypeError):
                confidence = 0.5
        
        # 优先使用direction字段，如果没有则从recommendation推断
        signal_type = 'hold'
        signal_strength = 0.0
        try:
            # 确保direction是字符串类型，避免类型错误
            if not isinstance(direction, str):
                direction = str(direction) if direction is not None else 'hold'
            
            if direction in ['long', 'short']:
                signal_type = 'buy' if direction == 'long' else 'sell'
                signal_strength = confidence
            else:
                # 识别各种买入/卖出建议（支持多种表述）
                # 确保recommendation是字符串类型
                if not isinstance(recommendation, str):
                    recommendation = str(recommendation) if recommendation is not None else 'unknown'
                
                recommendation_str = str(recommendation)  # 确保是字符串
                recommendation_lower = recommendation_str.lower()
                
                # 买入相关：买入、建议买入、谨慎买入、适度买入、小仓位买入、看涨等
                buy_keywords = ['买入', '看涨', '做多', '买入', '建议买入', '谨慎买入', '适度买入', '小仓位买入', '可以考虑买入']
                # 卖出相关：卖出、建议卖出、谨慎卖出、适度卖出、看跌、做空等
                sell_keywords = ['卖出', '看跌', '做空', '卖出', '建议卖出', '谨慎卖出', '适度卖出', '可以考虑卖出']
                
                # 检查是否包含买入关键词（使用字符串版本）
                # 确保recommendation_str是字符串类型
                if not isinstance(recommendation_str, str):
                    recommendation_str = str(recommendation_str)
                
                is_buy = any(keyword in recommendation_str for keyword in buy_keywords)
                # 检查是否包含卖出关键词（使用字符串版本）
                is_sell = any(keyword in recommendation_str for keyword in sell_keywords)
                
                if is_buy and not is_sell:
                    signal_type = 'buy'
                    # 如果是"谨慎买入"，降低信号强度
                    if '谨慎' in recommendation_str or '小仓位' in recommendation_str:
                        signal_strength = confidence * 0.7
                    else:
                        signal_strength = confidence
                elif is_sell and not is_buy:
                    signal_type = 'sell'
                    # 如果是"谨慎卖出"，降低信号强度
                    if '谨慎' in recommendation_str or '小仓位' in recommendation_str:
                        signal_strength = confidence * 0.7
                    else:
                        signal_strength = confidence
                else:
                    signal_type = 'hold'
                    signal_strength = 0.0
        except Exception as e:
            self.logger.error(f"[DeepSeek信号生成] 处理direction/recommendation字段失败 {symbol}: {e}, direction类型: {type(direction)}, recommendation类型: {type(recommendation)}", exc_info=True)
            signal_type = 'hold'
            signal_strength = 0.0
        
        signal_result = {
            'type': signal_type,
            'strength': signal_strength,
            'confidence': confidence,
            'reasoning': analysis.get('reasoning', ''),
            'analysis': analysis,
            'direction': direction,  # 方向：long/short/hold
            'entry_limit_price': entry_limit_price,  # 开仓最佳限价
            'exit_limit_price': exit_limit_price  # 平仓最优限价
        }
        
        # 确保所有数值都是数字类型，避免格式说明符错误
        try:
            signal_strength_float = float(signal_strength) if signal_strength is not None else 0.0
        except (ValueError, TypeError):
            signal_strength_float = 0.0
        
        try:
            confidence_float = float(confidence) if confidence is not None else 0.0
        except (ValueError, TypeError):
            confidence_float = 0.0
        
        # 格式化数值，避免在f-string中使用格式说明符
        signal_strength_str = f"{signal_strength_float:.2f}"
        confidence_str_log = f"{confidence_float:.2f}"
        
        # 记录生成的信号
        self.logger.info(
            f"[DeepSeek信号生成结果] 交易对: {symbol} | "
            f"信号类型: {signal_type} | "
            f"信号强度: {signal_strength_str} | "
            f"信心度: {confidence_str_log} | "
            f"建议: {recommendation}"
        )
        self.logger.debug(f"[DeepSeek信号详情] 交易对: {symbol} - 完整信号: {json.dumps(self._serialize_for_json(signal_result), indent=2, ensure_ascii=False)}")
        
        return signal_result
    
    def evaluate_risk(self, market_data: Dict[str, Any], 
                     position: Dict[str, Any]) -> Dict[str, Any]:
        """
        风险评估
        
        Args:
            market_data: 市场数据
            position: 持仓信息
            
        Returns:
            风险评估结果
        """
        symbol = market_data.get('symbol', 'UNKNOWN')
        position_size = position.get('size', 0)
        self.logger.info(f"[DeepSeek风险评估] 开始风险评估 - 交易对: {symbol}, 持仓量: {position_size}")
        
        signal_context = {
            'task': 'risk_evaluation',
            'focus': '持仓风险评估',
            'position': position
        }
        
        analysis = self.analyze_market(market_data, signal_context)
        
        risk_result = {
            'risk_level': analysis.get('risk_level', 'medium'),
            'recommendation': analysis.get('recommendation', 'hold'),
            'reasoning': analysis.get('reasoning', ''),
            'analysis': analysis
        }
        
        # 记录风险评估结果
        self.logger.info(
            f"[DeepSeek风险评估结果] 交易对: {symbol} | "
            f"风险等级: {risk_result['risk_level']} | "
            f"建议: {risk_result['recommendation']}"
        )
        self.logger.debug(f"[DeepSeek风险详情] 交易对: {symbol} - 完整风险评估: {json.dumps(self._serialize_for_json(risk_result), indent=2, ensure_ascii=False)}")
        
        return risk_result
    
    def analyze_position(self, position_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        AI分析持仓情况，给出仓位调整建议
        
        Args:
            position_data: 持仓数据，包含持仓信息、市场数据、技术指标等
        
        Returns:
            持仓分析结果（包含调整建议：加仓/减仓/平仓/持有）
        """
        symbol = position_data.get('symbol', 'UNKNOWN')
        position = position_data.get('position', {})
        
        # 确保数值是数字类型，避免格式说明符错误
        try:
            profit_pct = float(position.get('profit_pct', 0)) if position.get('profit_pct') is not None else 0.0
            holding_hours = float(position.get('holding_duration_hours', 0)) if position.get('holding_duration_hours') is not None else 0.0
        except (ValueError, TypeError):
            profit_pct = 0.0
            holding_hours = 0.0
        
        profit_pct_str = f"{profit_pct:.2f}%"
        holding_hours_str = f"{holding_hours:.2f}小时"
        
        # 安全提取值，避免在f-string中使用.get()导致格式说明符错误
        side_log = str(position.get('side', 'N/A'))
        size_log = str(position.get('size', 0))
        self.logger.info(
            f"[DeepSeek持仓分析] 开始分析持仓 - 交易对: {symbol}, "
            f"持仓方向: {side_log}, "
            f"持仓数量: {size_log}, "
            f"盈亏: {profit_pct_str}, "
            f"持仓时长: {holding_hours_str}"
        )
        
        position_context = {
            'task': 'position_analysis',
            'focus': '持仓分析和仓位调整建议'
        }
        
        # 构建分析提示词
        prompt = self._build_position_analysis_prompt(position_data)
        
        try:
            # 使用与analyze_market相同的方式调用API（使用_request方法）
            messages = [
                {
                    'role': 'system',
                    'content': '你是一位专业的加密货币交易分析师，擅长持仓分析和仓位调整建议。'
                },
                {
                    'role': 'user',
                    'content': prompt
                }
            ]
            
            # 使用_request方法调用API（与analyze_market一致）
            response_text = self._request(messages)
            
            # 解析JSON响应
            import json
            import re
            
            # 尝试提取JSON
            json_match = re.search(r'\{.*\}', response_text, re.DOTALL)
            if json_match:
                result = json.loads(json_match.group())
            else:
                # 如果不是JSON格式，尝试解析文本
                result = self._parse_position_analysis_text(response_text)
            
            # 验证结果
            if not result.get('recommendation'):
                result['recommendation'] = 'hold'
            
            if 'confidence' not in result:
                result['confidence'] = 0.5
            
            if 'reasoning' not in result:
                result['reasoning'] = response_text[:200]
            
            # 记录分析结果
            recommendation = result.get('recommendation', 'hold')
            confidence = result.get('confidence', 0.5)
            reasoning = result.get('reasoning', '')[:200]
            
            # 确保数值是数字类型，避免格式说明符错误
            try:
                profit_pct = float(position.get('profit_pct', 0)) if position.get('profit_pct') is not None else 0.0
            except (ValueError, TypeError):
                profit_pct = 0.0
            profit_pct_str = f"{profit_pct:.2f}%"
            
            # 确保confidence是数字类型，避免格式说明符错误
            try:
                confidence_float = float(confidence) if confidence is not None else 0.0
            except (ValueError, TypeError):
                confidence_float = 0.0
            
            confidence_str_log = f"{confidence_float:.2f}"
            
            self.logger.info(
                f"[DeepSeek持仓分析结果] 交易对: {symbol} | "
                f"建议: {recommendation} | "
                f"信心度: {confidence_str_log} | "
                f"盈亏: {profit_pct_str}"
            )
            
            return result
            
        except Exception as e:
            self.logger.error(f"[DeepSeek持仓分析] 交易对: {symbol} - 分析失败: {e}")
            return {
                'recommendation': 'hold',
                'confidence': 0.0,
                'reasoning': f'分析失败: {e}'
            }
    
    def _build_position_analysis_prompt(self, position_data: Dict[str, Any]) -> str:
        """构建持仓分析提示词"""
        symbol = position_data.get('symbol', 'UNKNOWN')
        position = position_data.get('position', {})
        market_data = position_data.get('market_data', {})
        indicators = market_data.get('indicators', {})
        multi_timeframe = market_data.get('multi_timeframe', {})
        
        # 确保数值是数字类型，避免格式说明符错误
        try:
            profit_pct = float(position.get('profit_pct', 0)) if position.get('profit_pct') is not None else 0.0
            holding_hours = float(position.get('holding_duration_hours', 0)) if position.get('holding_duration_hours') is not None else 0.0
            change_24h = float(market_data.get('change_24h', 0)) if market_data.get('change_24h') is not None else 0.0
        except (ValueError, TypeError):
            profit_pct = 0.0
            holding_hours = 0.0
            change_24h = 0.0
        
        profit_pct_str = f"{profit_pct:.2f}%"
        holding_hours_str = f"{holding_hours:.2f}小时"
        change_24h_str = f"{change_24h:.2f}%"
        
        # 预先提取所有在f-string中使用的值，避免在f-string中使用.get()导致格式说明符错误
        def safe_get_str(d, key, default='N/A'):
            """安全获取值并转换为字符串"""
            try:
                value = d.get(key, default)
                if value is None:
                    return str(default)
                return str(value)
            except Exception:
                return str(default)
        
        # 提取所有position中的值
        side_str = safe_get_str(position, 'side', 'N/A')
        size_str = safe_get_str(position, 'size', 0)
        entry_price_str = safe_get_str(position, 'entry_price', 0)
        current_price_str = safe_get_str(position, 'current_price', 0)
        
        # 提取所有market_data中的值
        price_market_str = safe_get_str(market_data, 'price', 0)
        volume_24h_str = safe_get_str(market_data, 'volume_24h', 0)
        
        # 提取所有indicators中的值
        rsi_str = safe_get_str(indicators, 'rsi', 'N/A')
        macd_str = safe_get_str(indicators, 'macd', 'N/A')
        macd_hist_str = safe_get_str(indicators, 'macd_hist', 'N/A')
        bb_upper_str = safe_get_str(indicators, 'bb_upper', 'N/A')
        bb_lower_str = safe_get_str(indicators, 'bb_lower', 'N/A')
        
        # 提取所有multi_timeframe中的值
        trend_24h_str = safe_get_str(multi_timeframe, 'trend_24H', 'N/A')
        trend_4h_str = safe_get_str(multi_timeframe, 'trend_4H', 'N/A')
        trend_1h_str = safe_get_str(multi_timeframe, 'trend_1H', 'N/A')
        overall_trend_str = safe_get_str(multi_timeframe, 'overall_trend', 'N/A')
        
        prompt = f"""你是一个专业的加密货币交易分析师。请分析以下持仓情况，并给出仓位调整建议。

## 持仓信息
- 交易对: {symbol}
- 持仓方向: {side_str}
- 持仓数量: {size_str}
- 开仓价格: {entry_price_str}
- 当前价格: {current_price_str}
- 当前盈亏: {profit_pct_str}
- 持仓时长: {holding_hours_str}

## 市场数据
- 当前价格: {price_market_str}
- 24小时涨跌: {change_24h_str}
- 24小时成交量: {volume_24h_str}

## 技术指标
- RSI: {rsi_str}
- MACD: {macd_str}
- MACD_Hist: {macd_hist_str}
- 布林带上轨: {bb_upper_str}
- 布林带下轨: {bb_lower_str}

## 多时间周期分析
- 24H趋势: {trend_24h_str}
- 4H趋势: {trend_4h_str}
- 1H趋势: {trend_1h_str}
- 综合趋势: {overall_trend_str}

## 分析要求
请综合考虑以下因素：
1. 当前盈亏情况（盈利时考虑止盈，亏损时考虑止损）
2. 持仓时长（长时间持仓需要重新评估）
3. 市场趋势变化（如果趋势反转，考虑平仓）
4. 技术指标信号（如果出现反向信号，考虑减仓或平仓）
5. 多时间周期分析（大周期趋势变化时调整仓位）

## 建议类型
请给出以下建议之一：
- **加仓**：市场趋势继续向好，可以增加仓位
- **减仓**：市场出现不确定性，减少部分仓位
- **平仓**：市场趋势反转或达到止盈止损点，全部平仓
- **持有**：当前持仓合理，继续持有

请以JSON格式返回分析结果：
{{
    "recommendation": "加仓/减仓/平仓/持有",
    "confidence": 0.0-1.0之间的浮点数,
    "reasoning": "详细的分析理由和建议",
    "suggested_action": "具体的操作建议",
    "risk_level": "低/中/高"
}}
"""
        return prompt
    
    def _parse_position_analysis_text(self, text: str) -> Dict[str, Any]:
        """解析非JSON格式的持仓分析文本"""
        result = {
            'recommendation': 'hold',
            'confidence': 0.5,
            'reasoning': text[:500]
        }
        
        text_lower = text.lower()
        
        # 识别建议类型
        if any(keyword in text_lower for keyword in ['加仓', '增加', '提高', '买入']):
            result['recommendation'] = '加仓'
        elif any(keyword in text_lower for keyword in ['减仓', '减少', '降低', '部分平仓']):
            result['recommendation'] = '减仓'
        elif any(keyword in text_lower for keyword in ['平仓', '全部平仓', '止盈', '止损']):
            result['recommendation'] = '平仓'
        else:
            result['recommendation'] = '持有'
        
        # 识别信心度（如果有数字）
        import re
        confidence_match = re.search(r'信心[度度]?[：:]\s*([0-9.]+)', text)
        if confidence_match:
            try:
                confidence = float(confidence_match.group(1))
                if confidence > 1:
                    confidence = confidence / 100
                result['confidence'] = min(1.0, max(0.0, confidence))
            except:
                pass
        
        return result
    
    def _record_deepseek_response(self, symbol: str, market_data: Dict[str, Any],
                                   raw_response: str, parsed_result: Dict[str, Any]):
        """
        记录DeepSeek的返回结果
        
        Args:
            symbol: 交易对符号
            market_data: 市场数据（用于记录上下文）
            raw_response: DeepSeek API的原始响应文本
            parsed_result: 解析后的结果
        """
        try:
            # 生成记录ID（基于时间戳）
            timestamp = datetime.now()
            record_id = f"{symbol}_{timestamp.strftime('%Y%m%d_%H%M%S_%f')}"
            
            # 构建记录数据
            record = {
                'record_id': record_id,
                'timestamp': timestamp.isoformat(),
                'symbol': symbol,
                'market_data': {
                    'price': market_data.get('price', 0),
                    'change_24h': market_data.get('change_24h', 0),
                    'volume_24h': market_data.get('volume_24h', 0),
                },
                'raw_response': raw_response,  # 原始API响应
                'parsed_result': parsed_result,  # 解析后的结果
                'key_fields': {
                    'direction': parsed_result.get('direction', 'unknown'),
                    'entry_limit_price': parsed_result.get('entry_limit_price', 0),
                    'exit_limit_price': parsed_result.get('exit_limit_price', 0),
                    'confidence': parsed_result.get('confidence', 0),
                    'recommendation': parsed_result.get('recommendation', 'unknown'),
                    'trend': parsed_result.get('trend', 'unknown'),
                }
            }
            
            # 保存到文件（JSON格式）
            filename = f"{record_id}.json"
            filepath = os.path.join(self.results_dir, filename)
            
            with open(filepath, 'w', encoding='utf-8') as f:
                json.dump(self._serialize_for_json(record), f, ensure_ascii=False, indent=2)
            
            # 同时保存到JSONL格式文件（追加模式，便于后续分析）
            jsonl_filepath = os.path.join(self.results_dir, 'deepseek_responses.jsonl')
            with open(jsonl_filepath, 'a', encoding='utf-8') as f:
                json.dump(self._serialize_for_json(record), f, ensure_ascii=False)
                f.write('\n')
            
            self.logger.info(
                f"[DeepSeek结果记录] 交易对: {symbol} | "
                f"记录ID: {record_id} | "
                f"方向: {parsed_result.get('direction', 'unknown')} | "
                f"信心度: {parsed_result.get('confidence', 0):.2f} | "
                f"已保存到: {filepath}"
            )
            
        except Exception as e:
            self.logger.error(f"[DeepSeek结果记录] 记录失败 {symbol}: {e}", exc_info=True)


if __name__ == "__main__":
    # 测试DeepSeek客户端
    client = DeepSeekClient()
    
    # 测试市场分析
    market_data = {
        'price': 50000,
        'change_24h': 2.5,
        'volume_24h': 1000000,
        'indicators': {
            'RSI': 65,
            'MACD': 'bullish'
        },
        'funding': {
            'large_order_flow': 'inflow',
            'funding_rate': 0.01
        },
        'chain': {
            'whale_activity': 'accumulating'
        },
        'sentiment': {
            'fear_greed_index': 55
        }
    }
    
    try:
        result = client.analyze_market(market_data)
        print("市场分析结果:", json.dumps(result, indent=2, ensure_ascii=False))
    except Exception as e:
        print(f"市场分析失败: {e}")

