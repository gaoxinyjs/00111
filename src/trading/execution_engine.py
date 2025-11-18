#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
执行引擎
订单执行优化，滑点控制，执行算法选择，执行性能监控
"""

import time
from typing import Dict, Optional, Any, List
from datetime import datetime
from decimal import Decimal, ROUND_FLOOR, ROUND_CEILING
from ..core.config_manager import get_config_manager
from ..core.logger import get_logger
from ..trading.order_manager import OrderManager, Order, OrderStatus
from ..decision.decision_engine import TradingDecision
from ..core.exception import TradingException


class ExecutionEngine:
    """执行引擎"""
    
    def __init__(self):
        """初始化执行引擎"""
        self.config_mgr = get_config_manager()
        self.logger = get_logger("execution_engine")
        self.order_manager = OrderManager()
        
        # 风险与趋势控制默认配置（可通过配置文件覆盖）
        default_risk_config = {
            'per_trade_risk_pct': 0.005,  # 单笔风险占账户余额比例
            'atr_period': 14,
            'atr_stop_multiplier': 1.2,
            'atr_take_profit_multiplier': 2.5,
            'take_profit_to_stop_ratio': 2.0,
            'min_stop_ticks': 6,
            'volatility_interval': '15m',
            'trend_interval': '30m',
            'trend_window': 10,
            'trend_min_slope': 0.0
        }
        try:
            risk_config_override = self.config_mgr.get_config('trading', 'risk_management', {}) or {}
            if isinstance(risk_config_override, dict):
                default_risk_config.update(risk_config_override)
        except Exception as err:
            self.logger.warning(f"加载风险管理配置失败，使用默认配置: {err}")
        self.risk_config = default_risk_config
        
        # 执行统计
        self.execution_stats = {
            'total_orders': 0,
            'successful_orders': 0,
            'failed_orders': 0,
            'total_slippage': 0.0,
            'avg_execution_time': 0.0
        }
    
    @staticmethod
    def _align_price_to_tick(price: float, tick_size: float, direction: str = 'nearest') -> float:
        """按照交易所要求将价格对齐到最小变动单位"""
        if price is None:
            return price
        if not tick_size or tick_size <= 0:
            return float(price)
        dec_price = Decimal(str(price))
        quantum = Decimal(str(tick_size))
        if direction == 'up':
            aligned = (dec_price / quantum).to_integral_value(rounding=ROUND_CEILING) * quantum
        elif direction == 'down':
            aligned = (dec_price / quantum).to_integral_value(rounding=ROUND_FLOOR) * quantum
        else:
            aligned = dec_price.quantize(quantum)
        return float(aligned)
    
    def _adjust_sl_tp_prices(
        self,
        side: str,
        entry_price: Optional[float],
        stop_loss: Optional[float],
        take_profit: Optional[float],
        tick_size: float,
    ) -> tuple:
        """根据方向对止损止盈做安全调整，避免违反交易所约束"""
        if entry_price is None:
            return stop_loss, take_profit
        entry_price = float(entry_price)
        tick = tick_size if tick_size and tick_size > 0 else 0.0001
        stop = float(stop_loss) if stop_loss is not None else None
        take = float(take_profit) if take_profit is not None else None
        if side == 'buy':
            if stop is not None:
                if stop >= entry_price:
                    stop = entry_price - tick
                stop = self._align_price_to_tick(stop, tick, 'down')
                while stop >= entry_price:
                    stop -= tick
            if take is not None:
                if take <= entry_price:
                    take = entry_price + tick
                take = self._align_price_to_tick(take, tick, 'up')
                while take <= entry_price:
                    take += tick
        else:  # sell / short
            if stop is not None:
                if stop <= entry_price:
                    stop = entry_price + tick
                stop = self._align_price_to_tick(stop, tick, 'up')
                while stop <= entry_price:
                    stop += tick
            if take is not None:
                if take >= entry_price:
                    take = entry_price - tick
                take = self._align_price_to_tick(take, tick, 'down')
                while take >= entry_price:
                    take -= tick
        if stop is not None and stop <= 0:
            stop = self._align_price_to_tick(entry_price - tick, tick, 'down')
        if take is not None and take <= 0:
            take = self._align_price_to_tick(entry_price - tick, tick, 'down')
        return stop, take

    @staticmethod
    def _align_size_to_lot(size: float, lot_size: float, min_size: float) -> tuple[float, bool]:
        """对齐下单数量到交易所要求的最小变动单位"""
        if size <= 0:
            return 0.0, False
        size_dec = Decimal(str(size))
        min_size_dec = Decimal(str(min_size)) if min_size and min_size > 0 else Decimal('0')
        if not lot_size or lot_size <= 0:
            aligned = max(size_dec, min_size_dec)
            aligned_float = float(aligned)
            return aligned_float, abs(aligned_float - size) > 1e-9
        lot_dec = Decimal(str(lot_size))
        lots = (size_dec / lot_dec).to_integral_value(rounding=ROUND_FLOOR)
        if lots <= 0:
            lots = Decimal(1)
        aligned = lots * lot_dec
        if aligned < min_size_dec:
            lots = (min_size_dec / lot_dec).to_integral_value(rounding=ROUND_CEILING)
            aligned = lots * lot_dec
        aligned_float = float(aligned)
        adjusted = abs(aligned_float - size) > 1e-9
        return aligned_float, adjusted

    @staticmethod
    def _extract_okx_items(response: Any) -> List[Dict[str, Any]]:
        if isinstance(response, list):
            return [item for item in response if isinstance(item, dict)]
        if isinstance(response, dict):
            data_field = response.get('data')
            if isinstance(data_field, list):
                return [item for item in data_field if isinstance(item, dict)]
            return [response]
        return []

    @classmethod
    def _okx_response_success(cls, response: Any) -> bool:
        items = cls._extract_okx_items(response)
        if not items:
            return False
        for item in items:
            s_code = str(item.get('sCode', '0')).strip()
            if s_code and s_code not in ('0', '00000'):
                return False
        return True
    
    async def execute_decision(self, decision: TradingDecision) -> Optional[Order]:
        """
        执行交易决策
        
        Args:
            decision: 交易决策
            
        Returns:
            执行的订单对象
        """
        try:
            start_time = time.time()
            self.logger.info(f"开始执行决策: {decision.symbol} {decision.action} {decision.position_size:.2%}")
            
            # 1. 验证决策
            if decision.action == 'hold' or decision.position_size <= 0:
                self.logger.info(f"决策为hold或仓位为0，不执行交易")
                return None
            
            # 2. 确定订单参数（支持合约交易）
            symbol = decision.symbol
            position_side = decision.position_side  # long或short
            
            # ⚠️ 重要：开仓前检查（只在开仓时检查，平仓时不检查）
            if decision.action in ['long', 'short']:
                # 检查持仓和委托
                check_result = await self._check_before_open_position(symbol, decision.action, position_side)
                if check_result == 'skip':
                    # 方向相同，不做任何处理
                    self.logger.info(f"✅ {symbol}: 已有同方向持仓，跳过开仓")
                    return None
                elif check_result == 'closed':
                    # 方向不同，已平仓，继续执行开仓
                    self.logger.info(f"✅ {symbol}: 已平仓相反方向持仓，继续开仓")
                elif check_result == 'error':
                    # 检查失败，终止执行
                    self.logger.error(f"❌ {symbol}: 开仓前检查失败，终止执行")
                    return None
                # check_result == 'ok' 表示没有持仓，继续执行
            
            instrument_info: Optional[Dict[str, Any]] = None

            # 合约交易：转换action为side
            # long做多 -> buy
            # short做空 -> sell
            # close_long平多 -> sell（卖出平仓）
            # close_short平空 -> buy（买入平仓）
            if decision.action == 'long':
                side = 'buy'
                action_desc = '做多'
            elif decision.action == 'short':
                side = 'sell'
                action_desc = '做空'
            elif decision.action == 'close_long':
                side = 'sell'  # 卖出平多仓
                action_desc = '平多'
            elif decision.action == 'close_short':
                side = 'buy'  # 买入平空仓
                action_desc = '平空'
            elif decision.action == 'buy':
                side = 'buy'
                action_desc = '买入'
            elif decision.action == 'sell':
                side = 'sell'
                action_desc = '卖出'
            else:
                self.logger.warning(f"未知的交易动作: {decision.action}")
                return None
            
            # 确定订单类型和价格
            # 如果决策中提供了价格（最佳入场价格），使用限价单；否则使用市价单
            # 优先使用决策中计算的最佳入场价格
            price = decision.price
            current_market_price = None
            try:
                from ..data.okx_client import OKXClient
                okx_client_temp = OKXClient()
                ticker = okx_client_temp.get_ticker(symbol)
                if ticker and isinstance(ticker, dict):
                    if ticker.get('code') == '0':
                        data = ticker.get('data', [])
                        if data and len(data) > 0:
                            current_market_price = float(data[0].get('last', 0))
            except Exception:
                pass
            
            if price and price > 0:
                order_type = 'limit'  # 使用限价单
                self.logger.info(
                    f"[订单类型] {symbol}: {action_desc} | "
                    f"✅ 使用限价单 | "
                    f"最佳入场价={price:.5f}, "
                    f"当前市价={current_market_price:.5f if current_market_price else 'N/A'}, "
                    f"差价={(price - current_market_price) / current_market_price * 100:.2f}%" if current_market_price and current_market_price > 0 else ""
                )
            else:
                order_type = 'market'  # 使用市价单
                price = None  # 市价单不需要价格
                self.logger.info(f"[订单类型] {symbol}: {action_desc} | 使用市价单（未计算最佳价格）")
            
            # 获取市场波动和趋势信息
            market_context = await self._fetch_market_context(symbol)
            atr_value = market_context.get('atr')
            trend_slope = market_context.get('trend_slope')
            trend_min_slope = float(self.risk_config.get('trend_min_slope', 0.0) or 0.0)
            if decision.action == 'long' and trend_slope is not None and trend_slope < -trend_min_slope:
                self.logger.info(
                    f"❌ {symbol}: 30分钟趋势向下(斜率={trend_slope:.5f})，拒绝做多以避免逆势"  # noqa: E501
                )
                return None
            if decision.action == 'short' and trend_slope is not None and trend_slope > trend_min_slope:
                self.logger.info(
                    f"❌ {symbol}: 30分钟趋势向上(斜率={trend_slope:.5f})，拒绝做空以避免逆势"  # noqa: E501
                )
                return None
            if atr_value is not None:
                self.logger.info(
                    f"[波动率] {symbol}: {self.risk_config.get('volatility_interval', '15m')} ATR≈{atr_value:.5f}"
                )
            
            # 0. 设置杠杆倍数（合约交易需要先设置杠杆）
            try:
                # 获取交易对配置中的杠杆倍数
                trading_config = self.config_mgr.get_config('trading', 'trading_pairs')
                leverage = 1  # 默认1倍杠杆
                for pair in trading_config:
                    if pair.get('symbol') == symbol:
                        leverage = pair.get('leverage', 1)
                        break
                
                # 如果是合约交易且杠杆大于1，设置杠杆
                if symbol.endswith('-SWAP') and leverage > 1:
                    from ..data.okx_client import OKXClient
                    okx_client = OKXClient()
                    
                    # 获取交易模式（全仓或逐仓）
                    api_config = self.config_mgr.get_config('api', 'okx')
                    margin_mode = api_config.get('trade_mode', 'cross')  # 默认全仓
                    
                    # 设置杠杆
                    okx_client.set_leverage(symbol, leverage, margin_mode)
                    self.logger.info(f"已设置杠杆: {symbol}, 杠杆倍数={leverage}x, 保证金模式={margin_mode}")
            except Exception as e:
                self.logger.warning(f"设置杠杆失败: {e}，继续执行交易")
            
            # 计算实际交易数量（根据账户余额、仓位比例与风险参数）
            available_balance = 0.0
            position_value = 0.0
            base_size_by_value = 0.0
            price_for_calc = price if price and price > 0 else current_market_price
            if not price_for_calc or price_for_calc <= 0:
                self.logger.warning(f"价格数据无效，无法计算下单数量: price={price}, market={current_market_price}")
                return None
            lot_size = 1.0
            min_size = 0.001
            ct_val = 1.0
            tick_size = 0.01
            try:
                try:
                    from ..data.okx_client import get_okx_client
                    okx_client = await get_okx_client()
                    balance_data = await okx_client.async_get_balance('USDT')
                    if balance_data:
                        if isinstance(balance_data, dict) and balance_data.get('code') == '0':
                            for item in balance_data.get('data', []) or []:
                                for detail in item.get('details', []) or []:
                                    if detail.get('ccy') == 'USDT' and detail.get('availBal'):
                                        available_balance = float(detail.get('availBal', 0))
                                        break
                        elif isinstance(balance_data, list):
                            for item in balance_data:
                                for detail in item.get('details', []) or []:
                                    if detail.get('ccy') == 'USDT' and detail.get('availBal'):
                                        available_balance = float(detail.get('availBal', 0))
                                        break
                    if available_balance > 0:
                        self.logger.info(f"获取账户余额成功: {available_balance:.2f} USDT")
                except Exception as api_error:
                    self.logger.warning(f"获取账户余额失败: {api_error}，改用配置默认值")
                if available_balance == 0:
                    default_balance = self.config_mgr.get_config('trading', 'auto_trading', {}).get('default_balance', 10000.0)
                    available_balance = float(default_balance)
                    self.logger.info(f"使用默认余额: {available_balance:.2f} USDT")
                position_value = available_balance * decision.position_size
                # 获取合约信息，确定lot size / tick size等
                try:
                    from ..data.okx_client import OKXClient
                    okx_client_temp = OKXClient()
                    instruments = okx_client_temp.get_instruments("SWAP", symbol)
                    if instruments and isinstance(instruments, list):
                        instrument_info = instruments[0]
                        lot_size = float(instrument_info.get('lotSz', lot_size))
                        min_size = float(instrument_info.get('minSz', min_size))
                        ct_val = float(instrument_info.get('ctVal', ct_val))
                        tick_size = float(instrument_info.get('tickSz', tick_size)) if instrument_info.get('tickSz') else tick_size
                        self.logger.info(
                            f"[合约信息] {symbol}: lotSize={lot_size}, minSize={min_size}, ctVal={ct_val}, tickSz={tick_size}"
                        )
                except Exception as e:
                    self.logger.warning(f"获取合约信息失败: {e}，使用默认合约参数")
                if ct_val <= 0:
                    ct_val = 1.0
                base_size_by_value = position_value / (price_for_calc * ct_val)
                if base_size_by_value <= 0:
                    self.logger.warning(f"根据仓位比例计算的名义合约数量无效: {base_size_by_value}")
                    return None
            except Exception as e:
                self.logger.error(f"计算基础仓位失败: {e}")
                return None
            
            # 3. 创建订单（合约交易：设置持仓方向和是否平仓）
            is_closing = decision.action in ['close_long', 'close_short']
            
            # 合约交易：对于单向持仓模式，使用"net"而不是具体的long/short
            # 只有在平仓或明确需要双向持仓时才使用long/short
            pos_side_for_order = None  # None表示使用"net"模式（单向持仓）
            if is_closing:
                # 平仓时使用具体的posSide
                pos_side_for_order = position_side
            
            # 3.1. 准备止盈止损价格（在创建订单时设置）
            size = base_size_by_value
            stop_loss_price = float(decision.stop_loss) if getattr(decision, 'stop_loss', None) else None
            take_profit_price = float(decision.take_profit) if getattr(decision, 'take_profit', None) else None
            entry_price_for_sl = float(price_for_calc)
            tick_size = tick_size if tick_size and tick_size > 0 else 0.0001
            if not is_closing:
                min_stop_ticks = max(1, int(self.risk_config.get('min_stop_ticks', 6) or 6))
                min_stop_distance = tick_size * min_stop_ticks
                atr_stop_multiplier = float(self.risk_config.get('atr_stop_multiplier', 1.2) or 1.2)
                atr_tp_multiplier = float(self.risk_config.get('atr_take_profit_multiplier', 2.5) or 2.5)
                tp_stop_ratio = float(self.risk_config.get('take_profit_to_stop_ratio', 2.0) or 2.0)
                if stop_loss_price is None or take_profit_price is None:
                    base_stop_distance = (atr_value or 0.0) * atr_stop_multiplier
                    base_tp_distance = (atr_value or 0.0) * atr_tp_multiplier
                    stop_distance = max(base_stop_distance, min_stop_distance)
                    take_profit_distance = max(base_tp_distance, stop_distance * tp_stop_ratio)
                    if stop_loss_price is None:
                        if decision.action in ['long', 'buy']:
                            stop_loss_price = entry_price_for_sl - stop_distance
                        elif decision.action in ['short', 'sell']:
                            stop_loss_price = entry_price_for_sl + stop_distance
                    if take_profit_price is None:
                        if decision.action in ['long', 'buy']:
                            take_profit_price = entry_price_for_sl + take_profit_distance
                        elif decision.action in ['short', 'sell']:
                            take_profit_price = entry_price_for_sl - take_profit_distance
                stop_loss_price, take_profit_price = self._adjust_sl_tp_prices(
                    side=side,
                    entry_price=entry_price_for_sl,
                    stop_loss=stop_loss_price,
                    take_profit=take_profit_price,
                    tick_size=tick_size,
                )
                risk_pct = float(self.risk_config.get('per_trade_risk_pct', 0.005) or 0.005)
                risk_amount = available_balance * risk_pct
                stop_distance_abs = abs(stop_loss_price - entry_price_for_sl) if stop_loss_price is not None else 0.0
                if stop_distance_abs > 0:
                    risk_based_size = risk_amount / (stop_distance_abs * ct_val)
                    if risk_based_size <= 0:
                        self.logger.warning(f"风险控制计算出的下单数量无效: {risk_based_size}")
                        return None
                    size = min(base_size_by_value, risk_based_size)
                else:
                    self.logger.warning("风险控制：无法计算有效的止损距离，使用仓位限制进行下单")
                    size = base_size_by_value
                if size <= 0:
                    self.logger.warning(f"最终下单数量无效，停止执行: size={size}")
                    return None
            # 调整数量至交易所允许的精度
            aligned_size, adjusted = self._align_size_to_lot(size, lot_size, min_size)
            if aligned_size <= 0:
                self.logger.warning(f"{symbol}: 数量对齐后无效，停止执行 | 原始={size:.6f}, lotSz={lot_size}, minSz={min_size}")
                return None
            if adjusted:
                self.logger.debug(
                    f"[数量对齐] {symbol}: 原始={size:.6f}, 调整后={aligned_size:.6f}, lotSz={lot_size}, minSz={min_size}"
                )
            size = aligned_size
            position_value = size * entry_price_for_sl * ct_val
            self.logger.info(
                f"[执行决策] {symbol}: {action_desc}({position_side}) | 仓位比例={decision.position_size:.2%} | "
                f"风险限额={self.risk_config.get('per_trade_risk_pct', 0.005):.3%} | 数量={size:.4f} | 名义价值≈{position_value:.2f} USDT"
            )
            
            if not is_closing and stop_loss_price is not None and take_profit_price is not None:
                try:
                    await self._cancel_existing_sl_tp_orders(symbol, pos_side_for_order)
                except Exception as e:
                    self.logger.warning(f"取消旧止盈止损订单失败 {symbol}: {e}")
                self.logger.info(
                    f"📌 [风险控制止盈止损] {symbol}: 止损={stop_loss_price:.5f}, 止盈={take_profit_price:.5f} "
                    f"(距离={abs(stop_loss_price - entry_price_for_sl):.5f})"
                )
            
            order = self.order_manager.create_order(
                symbol=symbol,
                side=side,
                order_type=order_type,
                size=size,
                price=price,
                position_side=pos_side_for_order,  # None表示"net"模式
                is_closing=is_closing  # 合约交易：是否平仓
            )
            order.attach_sl_tp_on_submit = False
            order.decision_price = entry_price_for_sl
            
            # 将止盈止损价格设置到订单对象中（用于成交后设置）
            if stop_loss_price:
                order.stop_loss_price = stop_loss_price
            if take_profit_price:
                order.take_profit_price = take_profit_price
            
            # 4. 提交订单
            order = self.order_manager.submit_order(order)
            
            # 5. 监控订单执行
            if order.status == OrderStatus.SUBMITTED:
                order = self._wait_for_execution(order, timeout=30)
            
            # 6. 计算滑点（止盈止损已经在开仓时通过attachAlgoOrds设置，无需重复设置）
            if order.status == OrderStatus.FILLED:
                reference_price = decision.price if decision.price else entry_price_for_sl
                slippage = self._calculate_slippage(order, reference_price)
                self.execution_stats['total_slippage'] += slippage
                filled_price = order.average_price or order.filled_price or reference_price
            
            # 7. 更新统计
            execution_time = time.time() - start_time
            self._update_stats(order, execution_time)
            
            self.logger.info(f"决策执行完成: {order.order_id}, 状态={order.status.value}, 耗时={execution_time:.2f}秒")
            
            return order
        
        except Exception as e:
            self.logger.error(f"执行决策失败: {e}")
            self.execution_stats['failed_orders'] += 1
            raise TradingException(f"执行决策失败: {e}")
    
    def _wait_for_execution(self, order: Order, timeout: int = 30) -> Order:
        """
        等待订单执行
        
        Args:
            order: 订单对象
            timeout: 超时时间（秒）
            
        Returns:
            更新后的订单对象
        """
        start_time = time.time()
        
        while time.time() - start_time < timeout:
            try:
                # 更新订单状态
                order = self.order_manager.update_order_status(order)
                
                # 如果已成交或取消，退出循环
                if order.status in [OrderStatus.FILLED, OrderStatus.CANCELLED, OrderStatus.REJECTED]:
                    break
                
                # 等待1秒后再次查询
                time.sleep(1)
            
            except Exception as e:
                self.logger.warning(f"查询订单状态失败: {e}")
                time.sleep(1)
        
        # 如果超时仍未成交，标记为过期
        if order.status not in [OrderStatus.FILLED, OrderStatus.CANCELLED, OrderStatus.REJECTED]:
            order.status = OrderStatus.EXPIRED
            order.updated_at = datetime.now()
            self.logger.warning(f"订单执行超时: {order.order_id}")
        
        return order
    
    async def _cancel_existing_sl_tp_orders(self, symbol: str, position_side: Optional[str] = None):
        """
        取消现有的止盈止损订单（同方向的）
        
        Args:
            symbol: 交易对符号
            position_side: 持仓方向（long, short），如果为None则取消所有
        """
        try:
            from ..data.okx_client import get_okx_client
            okx_client = await get_okx_client()
            
            # 查询现有的算法订单（止盈止损订单）
            algo_orders = await okx_client.async_get_algo_orders(symbol=symbol, state='live', order_type='conditional')
            
            if not algo_orders:
                self.logger.debug(f"没有找到现有的止盈止损订单 {symbol}")
                return
            
            # 取消同方向的止盈止损订单
            canceled_count = 0
            for algo_order in algo_orders:
                try:
                    # 获取算法订单信息
                    algo_id = algo_order.get('algoId', '')
                    algo_pos_side = algo_order.get('posSide', '')
                    order_type = algo_order.get('ordType', '')
                    
                    # 只取消条件单（止盈止损订单）
                    if order_type != 'conditional':
                        continue
                    
                    # 如果指定了持仓方向，只取消同方向的订单
                    if position_side:
                        if algo_pos_side != position_side:
                            continue
                    
                    # 取消算法订单
                    cancel_result = await okx_client.async_cancel_algo_order(symbol, algo_id)
                    
                    success = False
                    error_msg = None
                    if cancel_result:
                        if isinstance(cancel_result, dict):
                            data_list = cancel_result.get('data', [])
                        elif isinstance(cancel_result, list):
                            data_list = cancel_result
                        else:
                            data_list = []
                        
                        for item in data_list:
                            if item.get('sCode') == '0':
                                success = True
                                break
                            if not error_msg and item.get('sMsg'):
                                error_msg = item.get('sMsg')
                    
                    if success:
                        self.logger.info(
                            f"✅ [取消旧止盈止损] {symbol}: 已取消算法订单 {algo_id} "
                            f"(持仓方向={algo_pos_side})"
                        )
                        canceled_count += 1
                    else:
                        self.logger.warning(
                            f"⚠️ [取消旧止盈止损] {symbol}: 取消算法订单失败 {algo_id} | "
                            f"错误={error_msg or '未知错误'}"
                        )
                
                except Exception as e:
                    self.logger.debug(f"取消算法订单失败 {symbol}: {e}")
            
            if canceled_count > 0:
                self.logger.info(
                    f"✅ [取消旧止盈止损] {symbol}: 已取消 {canceled_count} 个同方向的止盈止损订单"
                )
        
        except Exception as e:
            self.logger.warning(f"查询并取消旧止盈止损订单失败 {symbol}: {e}")
    
    async def _check_before_open_position(self, symbol: str, action: str, position_side: str) -> str:
        """
        开仓前检查：检查持仓和委托
        
        Args:
            symbol: 交易对符号
            action: 交易动作（long/short）
            position_side: 持仓方向（long/short）
            
        Returns:
            'skip': 方向相同，跳过
            'closed': 方向不同，已平仓
            'ok': 没有持仓，继续
            'error': 检查失败
        """
        try:
            from ..data.okx_client import get_okx_client
            okx_client = await get_okx_client()
            
            # 1. 检查是否有持仓
            positions_result = await okx_client.async_get_positions(symbol)
            current_position = None
            
            if positions_result:
                # OKX API返回格式：{"code":"0","data":[...]}
                if isinstance(positions_result, dict):
                    if positions_result.get('code') == '0':
                        positions = positions_result.get('data', [])
                    else:
                        positions = []
                elif isinstance(positions_result, list):
                    positions = positions_result
                else:
                    positions = []
                
                # 查找有效的持仓（持仓量>0）
                for pos in positions:
                    pos_size = float(pos.get('pos', 0) or pos.get('posSz', 0) or 0)
                    if pos_size > 0:
                        current_position = pos
                        break
            
            # 2. 检查是否有待处理的订单（委托）
            pending_orders = []
            try:
                # 获取待处理的订单
                orders_result = await okx_client.async_get_pending_orders(symbol)
                if orders_result:
                    if isinstance(orders_result, dict):
                        if orders_result.get('code') == '0':
                            pending_orders = orders_result.get('data', [])
                    elif isinstance(orders_result, list):
                        pending_orders = orders_result
            except Exception as e:
                self.logger.debug(f"获取待处理订单失败 {symbol}: {e}")
            
            # 3. 如果有委托，先撤销
            if pending_orders:
                canceled_count = 0
                for order in pending_orders:
                    try:
                        order_id = order.get('ordId', '')
                        if order_id:
                            cancel_result = await okx_client.async_cancel_order(symbol, order_id)
                            success = False
                            error_msg = None
                            if cancel_result:
                                if isinstance(cancel_result, dict):
                                    data_list = cancel_result.get('data', [])
                                elif isinstance(cancel_result, list):
                                    data_list = cancel_result
                                else:
                                    data_list = []
                                
                                for item in data_list:
                                    if item.get('sCode') == '0':
                                        success = True
                                        break
                                    if not error_msg and item.get('sMsg'):
                                        error_msg = item.get('sMsg')
                            
                            if success:
                                self.logger.info(
                                    f"✅ [撤销委托] {symbol}: 已撤销订单 {order_id}"
                                )
                                canceled_count += 1
                            else:
                                self.logger.warning(
                                    f"⚠️ [撤销委托] {symbol}: 撤销订单失败 {order_id} | "
                                    f"错误={error_msg or '未知错误'}"
                                )
                    except Exception as e:
                        self.logger.debug(f"撤销订单失败 {symbol}: {e}")
                
                if canceled_count > 0:
                    self.logger.info(
                        f"✅ [撤销委托] {symbol}: 已撤销 {canceled_count} 个待处理订单"
                    )
            
            # 4. 检查持仓
            if current_position:
                current_pos_side = current_position.get('posSide', '')
                current_pos_size = float(current_position.get('pos', 0) or current_position.get('posSz', 0) or 0)
                
                # 规范化持仓方向
                if current_pos_side == 'net':
                    # 如果是net模式，根据持仓数量判断方向
                    if current_pos_size > 0:
                        current_pos_side = 'long'
                    elif current_pos_size < 0:
                        current_pos_side = 'short'
                    else:
                        current_pos_side = None
                
                # 如果方向相同，不做任何处理
                if current_pos_side == position_side:
                    self.logger.info(
                        f"ℹ️ {symbol}: 已有同方向持仓 | "
                        f"当前持仓方向={current_pos_side}, 持仓量={current_pos_size:.4f} | "
                        f"新开仓方向={position_side} | 跳过开仓"
                    )
                    return 'skip'
                
                # 如果方向不同，先平仓
                if current_pos_side and current_pos_side != position_side:
                    self.logger.warning(
                        f"⚠️ {symbol}: 持仓方向相反 | "
                        f"当前持仓方向={current_pos_side}, 持仓量={current_pos_size:.4f} | "
                        f"新开仓方向={position_side} | 先平仓"
                    )
                    
                    # 平仓
                    try:
                        close_result = await self._close_opposite_position(
                            symbol, current_position, current_pos_side
                        )
                        if close_result:
                            self.logger.info(
                                f"✅ {symbol}: 已平仓相反方向持仓 | "
                                f"原持仓方向={current_pos_side}, 持仓量={current_pos_size:.4f}"
                            )
                            return 'closed'
                        else:
                            self.logger.error(
                                f"❌ {symbol}: 平仓失败，终止开仓"
                            )
                            return 'error'
                    except Exception as e:
                        self.logger.error(
                            f"❌ {symbol}: 平仓异常，终止开仓: {e}"
                        )
                        return 'error'
            
            # 5. 没有持仓，继续执行
            return 'ok'
        
        except Exception as e:
            self.logger.error(f"开仓前检查失败 {symbol}: {e}")
            return 'error'
    
    async def _close_opposite_position(self, symbol: str, position: Dict[str, Any], position_side: str) -> bool:
        """
        平仓相反方向的持仓
        
        Args:
            symbol: 交易对符号
            position: 持仓信息
            position_side: 持仓方向（long/short）
            
        Returns:
            是否成功平仓
        """
        try:
            from ..data.okx_client import OKXClient
            okx_client = OKXClient()
            
            # 获取持仓数量
            pos_size = float(position.get('pos', 0) or position.get('posSz', 0) or 0)
            if pos_size == 0:
                return True
            
            # 确定平仓方向
            if position_side == 'long':
                # 平多仓：卖出
                close_side = 'sell'
            elif position_side == 'short':
                # 平空仓：买入
                close_side = 'buy'
            else:
                # 根据持仓数量判断
                if pos_size > 0:
                    close_side = 'sell'
                else:
                    close_side = 'buy'
                    pos_size = abs(pos_size)
            
            # 获取持仓方向（用于合约交易）
            pos_side_for_close = position_side if position_side in ['long', 'short'] else None
            
            # 使用市价单平仓（快速平仓）
            size_str = str(Decimal(str(abs(pos_size))).normalize())
            
            # 创建平仓订单
            close_order = self.order_manager.create_order(
                symbol=symbol,
                side=close_side,
                order_type='market',  # 市价单，快速平仓
                size=abs(pos_size),
                price=None,
                position_side=pos_side_for_close,
                is_closing=True  # 平仓
            )
            
            # 提交平仓订单
            close_order = self.order_manager.submit_order(close_order)
            
            if close_order.status == OrderStatus.SUBMITTED:
                # 等待平仓订单成交
                close_order = self._wait_for_execution(close_order, timeout=10)
            
            if close_order.status == OrderStatus.FILLED:
                self.logger.info(
                    f"✅ [平仓成功] {symbol}: {position_side} 持仓已平仓 | "
                    f"平仓数量={abs(pos_size):.4f}"
                )
                return True
            else:
                self.logger.warning(
                    f"⚠️ [平仓失败] {symbol}: 平仓订单状态={close_order.status.value}"
                )
                return False
        
        except Exception as e:
            self.logger.error(f"平仓失败 {symbol}: {e}")
            return False
    
    async def _set_stop_loss_take_profit(self, symbol: str, side: str, position_side: str,
                                        stop_loss_price: float, take_profit_price: float,
                                        main_order: Order):
        """
        设置止盈止损订单（在开仓订单成交后）
        
        ⚠️ 注意：此方法已废弃，不再使用。止盈止损现在在开仓时通过 attachAlgoOrds 一次性设置，
        避免重复设置多个止盈止损订单。如果需要单独设置止盈止损，请使用此方法，但不推荐。
        
        Args:
            symbol: 交易对符号
            side: 主订单方向（buy, sell）
            position_side: 持仓方向（long, short）
            stop_loss_price: 止损价格
            take_profit_price: 止盈价格
            main_order: 主订单对象
        """
        try:
            from ..data.okx_client import OKXClient
            okx_client = OKXClient()
            
            # 合约交易：根据持仓方向设置止盈止损
            # 做多：止损是卖出（sell），止盈是卖出（sell）
            # 做空：止损是买入（buy），止盈是买入（buy）
            
            if position_side == 'long' or side == 'buy':
                # 做多持仓：止损和止盈都是卖出
                stop_loss_side = 'sell'
                take_profit_side = 'sell'
                stop_loss_desc = '止损（卖出）'
                take_profit_desc = '止盈（卖出）'
            else:  # short or sell
                # 做空持仓：止损和止盈都是买入
                stop_loss_side = 'buy'
                take_profit_side = 'buy'
                stop_loss_desc = '止损（买入）'
                take_profit_desc = '止盈（买入）'
            
            # 获取订单数量（用于设置止盈止损订单的数量）
            # 如果订单还未成交，使用订单数量；如果已成交，使用成交数量
            order_size = main_order.filled_size if main_order.filled_size > 0 else main_order.size
            
            # 获取当前价格
            # 如果订单已成交，使用成交均价；如果未成交，使用委托价格或当前市价
            if main_order.average_price > 0:
                current_price = main_order.average_price
            elif main_order.price and main_order.price > 0:
                current_price = main_order.price
            elif hasattr(main_order, 'decision_price') and main_order.decision_price:
                # 如果都没有，使用保存的决策价格
                current_price = main_order.decision_price
            else:
                current_price = 0
            
            if order_size <= 0:
                self.logger.warning(f"无法设置止盈止损：订单数量={order_size}")
                return False
            
            # 如果当前价格为0，尝试从市场数据获取
            if current_price <= 0:
                try:
                    from ..data.okx_client import OKXClient
                    okx_client_temp = OKXClient()
                    ticker = okx_client_temp.get_ticker(symbol)
                    if ticker and isinstance(ticker, dict):
                        if ticker.get('code') == '0':
                            data = ticker.get('data', [])
                            if data and len(data) > 0:
                                current_price = float(data[0].get('last', 0))
                except Exception as e:
                    self.logger.warning(f"获取当前价格失败 {symbol}: {e}")
            
            if current_price <= 0:
                self.logger.warning(f"无法设置止盈止损：无法获取当前价格")
                return False
            
            overall_success = False
            # 设置止损订单（条件单）
            try:
                # 格式化数量字符串
                size_str = str(Decimal(str(order_size)).normalize())
                
                # 格式化价格字符串
                stop_loss_price_str = str(Decimal(str(stop_loss_price)).normalize())
                take_profit_price_str = str(Decimal(str(take_profit_price)).normalize())
                
                if position_side == 'long' or side == 'buy':
                    # 做多：止损是卖出，止盈是卖出
                    # 止损：当价格 <= 止损价格时，卖出（市价）
                    stop_loss_success = False
                    take_profit_success = False
                    if stop_loss_price < current_price:
                        try:
                            stop_loss_result = okx_client.place_stop_loss_order(
                                symbol=symbol,
                                side='sell',  # 止损是卖出
                                size=size_str,
                                trigger_price=stop_loss_price_str,
                                order_price=stop_loss_price_str,  # 限价：使用触发价格作为限价
                                pos_side='long' if position_side == 'long' else None
                            )
                            
                            stop_loss_success = self._okx_response_success(stop_loss_result)
                            if stop_loss_success:
                                self.logger.info(
                                    f"✅ [止损订单设置成功] {symbol}: 做多 | "
                                    f"止损价={stop_loss_price:.5f} (低于开仓价{current_price:.5f}) | "
                                    f"数量={order_size:.4f}"
                                )
                                overall_success = True
                            else:
                                self.logger.warning(
                                    f"❌ [止损订单设置失败] {symbol}: {stop_loss_result}"
                                )
                        except Exception as e:
                            self.logger.error(f"设置止损订单失败 {symbol}: {e}")
                    
                    # 止盈：当价格 >= 止盈价格时，卖出（市价）
                    if take_profit_price > current_price:
                        try:
                            take_profit_result = okx_client.place_take_profit_order(
                                symbol=symbol,
                                side='sell',  # 止盈是卖出
                                size=size_str,
                                trigger_price=take_profit_price_str,
                                order_price=take_profit_price_str,  # 限价：使用触发价格作为限价
                                pos_side='long' if position_side == 'long' else None
                            )
                            
                            take_profit_success = self._okx_response_success(take_profit_result)
                            if take_profit_success:
                                self.logger.info(
                                    f"✅ [止盈订单设置成功] {symbol}: 做多 | "
                                    f"止盈价={take_profit_price:.5f} (高于开仓价{current_price:.5f}) | "
                                    f"数量={order_size:.4f}"
                                )
                                overall_success = True
                            else:
                                self.logger.warning(
                                    f"❌ [止盈订单设置失败] {symbol}: {take_profit_result}"
                                )
                        except Exception as e:
                            self.logger.error(f"设置止盈订单失败 {symbol}: {e}")
                
                else:  # short or sell
                    # 做空：止损是买入，止盈是买入
                    # 止损：当价格 >= 止损价格时，买入（市价）
                    stop_loss_success = False
                    take_profit_success = False
                    if stop_loss_price > current_price:
                        try:
                            stop_loss_result = okx_client.place_stop_loss_order(
                                symbol=symbol,
                                side='buy',  # 止损是买入
                                size=size_str,
                                trigger_price=stop_loss_price_str,
                                order_price=stop_loss_price_str,  # 限价：使用触发价格作为限价
                                pos_side='short' if position_side == 'short' else None
                            )
                            
                            stop_loss_success = self._okx_response_success(stop_loss_result)
                            if stop_loss_success:
                                self.logger.info(
                                    f"✅ [止损订单设置成功] {symbol}: 做空 | "
                                    f"止损价={stop_loss_price:.5f} (高于开仓价{current_price:.5f}) | "
                                    f"数量={order_size:.4f}"
                                )
                                overall_success = True
                            else:
                                self.logger.warning(
                                    f"❌ [止损订单设置失败] {symbol}: {stop_loss_result}"
                                )
                        except Exception as e:
                            self.logger.error(f"设置止损订单失败 {symbol}: {e}")
                    
                    # 止盈：当价格 <= 止盈价格时，买入（市价）
                    if take_profit_price < current_price:
                        try:
                            take_profit_result = okx_client.place_take_profit_order(
                                symbol=symbol,
                                side='buy',  # 止盈是买入
                                size=size_str,
                                trigger_price=take_profit_price_str,
                                order_price=take_profit_price_str,  # 限价：使用触发价格作为限价
                                pos_side='short' if position_side == 'short' else None
                            )
                            
                            take_profit_success = self._okx_response_success(take_profit_result)
                            if take_profit_success:
                                self.logger.info(
                                    f"✅ [止盈订单设置成功] {symbol}: 做空 | "
                                    f"止盈价={take_profit_price:.5f} (低于开仓价{current_price:.5f}) | "
                                    f"数量={order_size:.4f}"
                                )
                                overall_success = True
                            else:
                                self.logger.warning(
                                    f"❌ [止盈订单设置失败] {symbol}: {take_profit_result}"
                                )
                        except Exception as e:
                            self.logger.error(f"设置止盈订单失败 {symbol}: {e}")
                
            except Exception as e:
                self.logger.warning(f"设置止盈止损订单失败 {symbol}: {e}")
                
        except Exception as e:
            self.logger.error(f"设置止盈止损失败 {symbol}: {e}")
            return False
        
        return overall_success
    
    async def _update_stop_loss_take_profit(self, symbol: str, order: Order,
                                             stop_loss_price: float, take_profit_price: float,
                                             action: str):
        """
        更新止盈止损订单（先取消旧的，再创建新的）
        
        Args:
            symbol: 交易对符号
            order: 订单对象
            stop_loss_price: 新的止损价格
            take_profit_price: 新的止盈价格
            action: 操作方向（long, short）
        """
        try:
            from ..data.okx_client import OKXClient
            okx_client = OKXClient()
            
            # 1. 先取消旧的止盈止损订单
            position_side = 'long' if action == 'long' else 'short'
            await self._cancel_existing_sl_tp_orders(symbol, position_side)
            
            # 2. 获取订单数量（用于设置止盈止损订单的数量）
            order_size = order.filled_size if order.filled_size > 0 else order.size
            
            # 3. 获取当前价格（使用成交均价）
            current_price = order.average_price or order.filled_price or order.price
            
            if order_size <= 0:
                self.logger.warning(f"无法更新止盈止损：订单数量={order_size}")
                return
            
            if current_price <= 0:
                self.logger.warning(f"无法更新止盈止损：无法获取当前价格")
                return
            
            # 4. 调用现有的设置止盈止损方法
            # 注意：side参数是原始开仓的side，不是止损止盈的side
            # 做多（long）开仓时side='buy'，做空（short）开仓时side='sell'
            # 但止损止盈的side会在_set_stop_loss_take_profit方法内部根据position_side计算
            side = 'buy' if action == 'long' else 'sell'
            
            await self._set_stop_loss_take_profit(
                symbol=symbol,
                side=side,  # 原始开仓的side（用于判断position_side）
                position_side=position_side,
                stop_loss_price=stop_loss_price,
                take_profit_price=take_profit_price,
                main_order=order
            )
            
            self.logger.info(
                f"✅ [更新止盈止损] {symbol}: {action} | "
                f"止损={stop_loss_price:.5f}, 止盈={take_profit_price:.5f} | "
                f"数量={order_size:.4f}"
            )
            
        except Exception as e:
            self.logger.error(f"更新止盈止损失败 {symbol}: {e}", exc_info=True)
    
    def _calculate_slippage(self, order: Order, expected_price: Optional[float]) -> float:
        """
        计算滑点
        
        Args:
            order: 订单对象
            expected_price: 预期价格
            
        Returns:
            滑点（比例）
        """
        if not expected_price or not order.average_price:
            return 0.0
        return (order.average_price - expected_price) / expected_price

    def _parse_kline(self, raw_kline: Any) -> List[Dict[str, float]]:
        """解析OKX返回的K线数据为按时间升序的字典列表"""
        candles: List[Dict[str, float]] = []
        if not raw_kline or not isinstance(raw_kline, list):
            return candles
        try:
            sorted_raw = sorted(raw_kline, key=lambda item: int(item[0]))
        except Exception:
            sorted_raw = raw_kline
        for item in sorted_raw:
            try:
                ts = int(item[0])
                open_price = float(item[1])
                high_price = float(item[2])
                low_price = float(item[3])
                close_price = float(item[4])
                candles.append({
                    'ts': ts,
                    'open': open_price,
                    'high': high_price,
                    'low': low_price,
                    'close': close_price
                })
            except (ValueError, TypeError, IndexError):
                continue
        return candles

    def _calculate_atr_value(self, candles: List[Dict[str, float]], period: int) -> Optional[float]:
        """根据K线数据计算简单ATR"""
        if not candles or len(candles) < max(period + 1, 2):
            return None
        true_ranges: List[float] = []
        for idx in range(1, len(candles)):
            current = candles[idx]
            previous = candles[idx - 1]
            high_low = current['high'] - current['low']
            high_close = abs(current['high'] - previous['close'])
            low_close = abs(current['low'] - previous['close'])
            true_ranges.append(max(high_low, high_close, low_close))
        if not true_ranges:
            return None
        relevant = true_ranges[-period:]
        if not relevant:
            return None
        return sum(relevant) / len(relevant)

    def _calculate_trend_slope(self, closes: List[float], window: int) -> Optional[float]:
        """通过两段均值差计算趋势斜率"""
        if not closes or window <= 0 or len(closes) < window * 2:
            return None
        recent = closes[-window:]
        previous = closes[-2 * window:-window]
        recent_avg = sum(recent) / window
        previous_avg = sum(previous) / window
        return recent_avg - previous_avg

    async def _fetch_market_context(self, symbol: str) -> Dict[str, Any]:
        """获取用于风险控制的市场波动与趋势信息"""
        context: Dict[str, Any] = {}
        try:
            from ..data.okx_client import get_okx_client
            okx_client = await get_okx_client()
        except Exception as e:
            self.logger.warning(f"获取OKX客户端失败，无法加载市场数据 {symbol}: {e}")
            return context
        atr_period = int(self.risk_config.get('atr_period', 14))
        volatility_interval = self.risk_config.get('volatility_interval', '15m')
        trend_interval = self.risk_config.get('trend_interval', '30m')
        trend_window = int(self.risk_config.get('trend_window', 10))
        try:
            limit_for_atr = max(atr_period * 3, atr_period + 2)
            raw_volatility = await okx_client.async_get_kline(symbol, volatility_interval, limit_for_atr)
            vol_candles = self._parse_kline(raw_volatility)
            atr_value = self._calculate_atr_value(vol_candles, atr_period)
            if atr_value is not None:
                context['atr'] = atr_value
                last_close = vol_candles[-1]['close'] if vol_candles else None
                if last_close and last_close != 0:
                    context['atr_pct'] = (atr_value / last_close) * 100
            if vol_candles:
                context['volatility_closes'] = [c['close'] for c in vol_candles]
        except Exception as e:
            self.logger.warning(f"获取波动率数据失败 {symbol}: {e}")
        try:
            limit_for_trend = max(trend_window * 4, trend_window * 2 + 2)
            raw_trend = await okx_client.async_get_kline(symbol, trend_interval, limit_for_trend)
            trend_candles = self._parse_kline(raw_trend)
            closes = [c['close'] for c in trend_candles]
            slope = self._calculate_trend_slope(closes, trend_window)
            if slope is not None:
                context['trend_slope'] = slope
                if slope > 0:
                    context['trend_direction'] = 'up'
                elif slope < 0:
                    context['trend_direction'] = 'down'
                else:
                    context['trend_direction'] = 'flat'
            if trend_candles:
                context['trend_closes'] = closes
        except Exception as e:
            self.logger.warning(f"获取趋势数据失败 {symbol}: {e}")
        return context
    
    def _update_stats(self, order: Order, execution_time: float):
        """更新执行统计"""
        self.execution_stats['total_orders'] += 1
        
        if order.status == OrderStatus.FILLED:
            self.execution_stats['successful_orders'] += 1
        else:
            self.execution_stats['failed_orders'] += 1
        
        # 更新平均执行时间
        total = self.execution_stats['total_orders']
        current_avg = self.execution_stats['avg_execution_time']
        self.execution_stats['avg_execution_time'] = (current_avg * (total - 1) + execution_time) / total
    
    def get_execution_stats(self) -> Dict[str, Any]:
        """获取执行统计"""
        stats = self.execution_stats.copy()
        
        if stats['total_orders'] > 0:
            stats['success_rate'] = stats['successful_orders'] / stats['total_orders']
            stats['avg_slippage'] = stats['total_slippage'] / stats['successful_orders'] if stats['successful_orders'] > 0 else 0.0
        else:
            stats['success_rate'] = 0.0
            stats['avg_slippage'] = 0.0
        
        return stats


if __name__ == "__main__":
    # 测试执行引擎
    engine = ExecutionEngine()
    
    # 创建测试决策
    from ..decision.decision_engine import TradingDecision
    
    decision = TradingDecision(
        symbol="BTC-USDT",
        action="buy",
        position_size=0.1,
        price=50000,
        confidence=0.7,
        reasoning="测试决策"
    )
    
    print("执行决策...")
    # order = engine.execute_decision(decision)
    # if order:
    #     print(f"订单ID: {order.order_id}")
    #     print(f"订单状态: {order.status.value}")
    
    print("执行统计:", engine.get_execution_stats())

