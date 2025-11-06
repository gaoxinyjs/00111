#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
执行引擎
订单执行优化，滑点控制，执行算法选择，执行性能监控
"""

import time
from typing import Dict, Optional, Any, List
from datetime import datetime
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
        
        # 执行统计
        self.execution_stats = {
            'total_orders': 0,
            'successful_orders': 0,
            'failed_orders': 0,
            'total_slippage': 0.0,
            'avg_execution_time': 0.0
        }
    
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
                # 尝试从决策中获取当前市场价格（如果有market_data的话）
                if hasattr(decision, 'risk_assessment') and decision.risk_assessment:
                    # 尝试从其他地方获取当前价格
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
            
            # 计算实际交易数量（根据账户余额和仓位比例）
            # 对于合约交易，直接使用固定余额或配置值，避免API调用失败影响交易
            try:
                # 优先尝试获取账户余额，但如果失败则使用配置的默认值
                available_balance = 0.0
                
                try:
                    from ..data.okx_client import OKXClient
                    okx_client = OKXClient()
                    
                    # 获取账户余额（合约账户使用币种为USDT）
                    balance_data = okx_client.get_balance('USDT')
                    
                    # 计算可用余额
                    if balance_data:
                        # OKX API返回格式：{"code":"0","data":[{"details":[...]}]}
                        if isinstance(balance_data, dict):
                            # 检查返回码
                            if balance_data.get('code') == '0':
                                data = balance_data.get('data', [])
                                if data and isinstance(data, list) and len(data) > 0:
                                    for item in data:
                                        details = item.get('details', [])
                                        if details:
                                            for detail in details:
                                                if detail.get('ccy') == 'USDT' and detail.get('availBal'):
                                                    available_balance = float(detail.get('availBal', 0))
                                                    break
                        elif isinstance(balance_data, list) and len(balance_data) > 0:
                            for item in balance_data:
                                details = item.get('details', [])
                                if details:
                                    for detail in details:
                                        if detail.get('ccy') == 'USDT' and detail.get('availBal'):
                                            available_balance = float(detail.get('availBal', 0))
                                            break
                    
                    if available_balance > 0:
                        self.logger.info(f"获取账户余额成功: {available_balance} USDT")
                    
                except Exception as api_error:
                    self.logger.warning(f"获取账户余额失败: {api_error}，使用默认配置")
                
                # 如果没有余额信息或获取失败，使用默认值或从配置读取
                if available_balance == 0:
                    # 从配置读取默认余额，如果没有则使用10000 USDT
                    default_balance = self.config_mgr.get_config('trading', 'auto_trading', {}).get('default_balance', 10000.0)
                    available_balance = default_balance
                    self.logger.info(f"使用默认余额: {available_balance} USDT")
                
                # 计算交易数量（仓位比例 * 可用余额 / 价格）
                # 合约交易：size是合约数量，不是USDT数量
                if price and price > 0:
                    # 获取合约信息，确定lot size（合约面值）
                    try:
                        from ..data.okx_client import OKXClient
                        okx_client_temp = OKXClient()
                        instruments = okx_client_temp.get_instruments("SWAP", symbol)
                        
                        lot_size = 1.0  # 默认lot size
                        min_size = 0.001  # 默认最小订单数量
                        ct_val = 1.0  # 合约面值
                        
                        if instruments and isinstance(instruments, list) and len(instruments) > 0:
                            instrument_info = instruments[0]
                            lot_size = float(instrument_info.get('lotSz', 1.0))  # 最小下单单位
                            min_size = float(instrument_info.get('minSz', 0.001))  # 最小订单数量
                            ct_val = float(instrument_info.get('ctVal', 1.0))  # 合约面值
                            
                            self.logger.info(
                                f"[合约信息] {symbol}: lotSize={lot_size}, minSize={min_size}, ctVal={ct_val}"
                            )
                    except Exception as e:
                        self.logger.warning(f"获取合约信息失败: {e}，使用默认值")
                    
                    # 计算合约数量（根据仓位比例）
                    position_value = available_balance * decision.position_size
                    size = position_value / (price * ct_val)  # 合约数量（考虑合约面值）
                    
                    # 将数量调整为lot_size的倍数
                    if lot_size > 0:
                        size = int(size / lot_size) * lot_size
                    
                    # 确保最小订单数量
                    if size < min_size:
                        self.logger.warning(f"计算出的数量({size})小于最小订单数量({min_size})，调整到最小值")
                        size = min_size
                        # 确保是最小值的倍数
                        if lot_size > 0:
                            size = int(size / lot_size + 0.5) * lot_size
                else:
                    self.logger.warning(f"价格无效，无法计算数量")
                    return None
                
                self.logger.info(
                    f"[执行决策] {symbol}: {action_desc}({position_side}) | "
                    f"仓位比例: {decision.position_size:.2%} | "
                    f"价格: {price} | "
                    f"数量: {size:.4f} | "
                    f"价值: {position_value:.2f} USDT"
                )
                
            except Exception as e:
                self.logger.error(f"计算交易数量失败: {e}")
                return None
            
            
            # 3. 创建订单（合约交易：设置持仓方向和是否平仓）
            is_closing = decision.action in ['close_long', 'close_short']
            
            # 确保数量精度（根据合约信息）
            try:
                # 获取合约信息以确定lotSz和minSz
                from ..data.okx_client import OKXClient
                okx_client_temp = OKXClient()
                instruments = okx_client_temp.get_instruments("SWAP", symbol)
                
                lot_size = 0.1  # 默认值
                min_size = 0.1  # 默认值
                
                if instruments and isinstance(instruments, list) and len(instruments) > 0:
                    instrument_info = instruments[0]
                    lot_size = float(instrument_info.get('lotSz', 0.1))  # 最小下单单位
                    min_size = float(instrument_info.get('minSz', 0.1))  # 最小订单数量
                    
                    # 将数量调整为lot_size的精确倍数（使用Decimal确保精度）
                    if lot_size > 0:
                        from decimal import Decimal, ROUND_DOWN, ROUND_UP
                        
                        lot_decimal = Decimal(str(lot_size))
                        size_decimal = Decimal(str(size))
                        
                        # 计算应该是lot_size的多少倍（向下取整）
                        lots = int(size_decimal / lot_decimal)
                        size_decimal = Decimal(str(lots)) * lot_decimal
                        
                        # 如果数量小于最小订单数量，向上取整到lot_size的倍数
                        min_decimal = Decimal(str(min_size))
                        if size_decimal < min_decimal:
                            lots = int((min_decimal / lot_decimal).quantize(Decimal('1'), rounding=ROUND_UP))
                            size_decimal = Decimal(str(lots)) * lot_decimal
                        
                        # 转换为float（但确保是精确倍数）
                        size = float(size_decimal)
                        
                        # 最终验证：确保是lot_size的精确倍数
                        lots_final = round(size / lot_size)
                        size = lots_final * lot_size
                        
                        # 确保不小于最小订单数量
                        if size < min_size:
                            lots_final = math.ceil(min_size / lot_size)
                            size = lots_final * lot_size
                    
                    self.logger.info(
                        f"[订单数量] {symbol}: lotSize={lot_size}, minSize={min_size}, 调整后数量={size} (验证倍数: {size % lot_size if lot_size > 0 else 0})"
                    )
                else:
                    # 如果没有获取到合约信息，使用配置值
                    trading_pairs = self.config_mgr.get_config('trading', 'trading_pairs')
                    pair_config = next((p for p in trading_pairs if p.get('symbol') == symbol), {})
                    size_precision = pair_config.get('size_precision', 4)
                    size = round(size, size_precision)
                    min_order_size = pair_config.get('min_order_size', 0.001)
                    if size < min_order_size:
                        size = min_order_size
                        
            except Exception as e:
                self.logger.warning(f"格式化订单数量失败: {e}，使用原始值")
            
            # 合约交易：对于单向持仓模式，使用"net"而不是具体的long/short
            # 只有在平仓或明确需要双向持仓时才使用long/short
            pos_side_for_order = None  # None表示使用"net"模式（单向持仓）
            if is_closing:
                # 平仓时使用具体的posSide
                pos_side_for_order = position_side
            
            # 确保数量是精确的lotSize倍数（使用Decimal格式化）
            from decimal import Decimal
            try:
                # 获取合约信息以确定lotSz
                from ..data.okx_client import OKXClient
                okx_client_temp = OKXClient()
                instruments = okx_client_temp.get_instruments("SWAP", symbol)
                if instruments and isinstance(instruments, list) and len(instruments) > 0:
                    instrument_info = instruments[0]
                    lot_size = float(instrument_info.get('lotSz', 0.1))
                    
                    # 使用Decimal确保数量是lotSize的精确倍数
                    lot_decimal = Decimal(str(lot_size))
                    size_decimal = Decimal(str(size))
                    lots = round(float(size_decimal / lot_decimal))
                    size_decimal = Decimal(str(lots)) * lot_decimal
                    size = float(size_decimal)
            except Exception as e:
                self.logger.warning(f"最终数量验证失败: {e}，使用原始值")
            
            # 3.1. 准备止盈止损价格（在创建订单时设置）
            stop_loss_price = None
            take_profit_price = None
            
            # 只在开仓时设置止盈止损（不是平仓时）
            if not is_closing and decision.stop_loss and decision.take_profit:
                stop_loss_price = decision.stop_loss
                take_profit_price = decision.take_profit
                
                # ⚠️ 重要：在设置新的止盈止损之前，先取消同方向的旧订单，避免重复
                try:
                    await self._cancel_existing_sl_tp_orders(symbol, pos_side_for_order)
                except Exception as e:
                    self.logger.warning(f"取消旧止盈止损订单失败 {symbol}: {e}")
                
                self.logger.info(
                    f"📌 [订单止盈止损] {symbol}: 在创建订单时同时设置 | "
                    f"止损={stop_loss_price:.5f}, 止盈={take_profit_price:.5f}"
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
            
            # 将止盈止损价格设置到订单对象中
            if stop_loss_price:
                order.stop_loss_price = stop_loss_price
            if take_profit_price:
                order.take_profit_price = take_profit_price
            
            # 4. 提交订单（止盈止损已在创建订单时通过 attachAlgoOrds 一次性设置）
            # 这样可以在一个订单中同时设置开仓、止盈、止损，避免后续多次设置
            order = self.order_manager.submit_order(order)
            
            # 重要：止盈止损已在创建订单时通过 attachAlgoOrds 一次性设置
            # 不需要在订单成交后再次设置，避免重复创建多个止盈止损订单
            
            # 5. 监控订单执行
            if order.status == OrderStatus.SUBMITTED:
                # 等待订单成交
                order = self._wait_for_execution(order, timeout=30)
            
            # 6. 计算滑点
            if order.status == OrderStatus.FILLED:
                slippage = self._calculate_slippage(order, decision.price)
                self.execution_stats['total_slippage'] += slippage
                
                # 重要：基于实际成交价格重新计算止盈止损（止损账户盈亏2%，止盈账户盈亏5%，考虑杠杆倍数）
                # 因为止盈止损应该基于开仓价格（实际成交价格），而不是当前市场价格
                filled_price = order.average_price or order.filled_price or order.price
                if filled_price and filled_price > 0:
                    # 获取杠杆倍数
                    leverage = 1  # 默认1倍杠杆
                    try:
                        trading_config = self.config_mgr.get_config('trading', 'trading_pairs')
                        for pair in trading_config:
                            if pair.get('symbol') == symbol:
                                leverage = pair.get('leverage', 1)
                                leverage = int(leverage) if leverage else 1
                                break
                    except Exception as e:
                        self.logger.warning(f"获取杠杆倍数失败 {symbol}: {e}，使用默认值1")
                    
                    # 计算考虑杠杆倍数的止盈止损（止损账户盈亏2%，止盈账户盈亏5%）
                    # 在杠杆交易中，账户盈亏 = 价格变动百分比 × 杠杆倍数
                    # 所以：价格变动百分比 = 账户盈亏 / 杠杆倍数
                    stop_loss_pnl_pct = 0.02  # 止损：账户盈亏2%
                    take_profit_pnl_pct = 0.05  # 止盈：账户盈亏5%
                    stop_loss_price_change_pct = stop_loss_pnl_pct / leverage
                    take_profit_price_change_pct = take_profit_pnl_pct / leverage
                    
                    # 重新计算止盈止损（基于实际成交价格）
                    actual_stop_loss = None
                    actual_take_profit = None
                    
                    if decision.action == 'long':
                        # 做多：止损在下方，止盈在上方
                        actual_stop_loss = filled_price * (1 - stop_loss_price_change_pct)
                        actual_take_profit = filled_price * (1 + take_profit_price_change_pct)
                    elif decision.action == 'short':
                        # 做空：止损在上方，止盈在下方
                        actual_stop_loss = filled_price * (1 + stop_loss_price_change_pct)
                        actual_take_profit = filled_price * (1 - take_profit_price_change_pct)
                    
                    if actual_stop_loss and actual_take_profit:
                        self.logger.info(
                            f"✅ {symbol}: 订单已成交，基于实际成交价格重新计算止盈止损 | "
                            f"成交价格={filled_price:.5f} | "
                            f"杠杆倍数={leverage}x | "
                            f"止损价格变动={stop_loss_price_change_pct*100:.3f}% (账户盈亏2%) | "
                            f"止盈价格变动={take_profit_price_change_pct*100:.3f}% (账户盈亏5%) | "
                            f"止损={actual_stop_loss:.5f} | "
                            f"止盈={actual_take_profit:.5f}"
                        )
                        
                        # 更新订单的止盈止损价格（用于后续设置）
                        order.stop_loss_price = actual_stop_loss
                        order.take_profit_price = actual_take_profit
                        
                        # ⚠️ 重要：如果之前设置的止盈止损与重新计算的不一致，需要实际更新到交易所
                        if stop_loss_price and abs(stop_loss_price - actual_stop_loss) > 0.0001:
                            self.logger.warning(
                                f"⚠️ {symbol}: 止盈止损价格需要更新 | "
                                f"原止损={stop_loss_price:.5f}, 新止损={actual_stop_loss:.5f} | "
                                f"原止盈={take_profit_price:.5f}, 新止盈={actual_take_profit:.5f} | "
                                f"正在更新到交易所..."
                            )
                            
                            # 实际更新止盈止损到交易所
                            try:
                                await self._update_stop_loss_take_profit(
                                    symbol, order, actual_stop_loss, actual_take_profit, decision.action
                                )
                            except Exception as e:
                                self.logger.error(f"❌ {symbol}: 更新止盈止损到交易所失败: {e}")
                        elif not stop_loss_price or not take_profit_price:
                            # 如果之前没有设置止盈止损，现在需要设置
                            self.logger.warning(
                                f"⚠️ {symbol}: 订单成交前未设置止盈止损，现在基于实际成交价格设置 | "
                                f"杠杆倍数={leverage}x | "
                                f"止损价格变动={stop_loss_price_change_pct*100:.3f}% (账户盈亏2%) | "
                                f"止盈价格变动={take_profit_price_change_pct*100:.3f}% (账户盈亏5%) | "
                                f"止损={actual_stop_loss:.5f} | "
                                f"止盈={actual_take_profit:.5f} | "
                                f"正在设置到交易所..."
                            )
                            
                            # 实际设置止盈止损到交易所
                            try:
                                await self._update_stop_loss_take_profit(
                                    symbol, order, actual_stop_loss, actual_take_profit, decision.action
                                )
                            except Exception as e:
                                self.logger.error(f"❌ {symbol}: 设置止盈止损到交易所失败: {e}")
                else:
                    self.logger.warning(
                        f"⚠️ {symbol}: 订单已成交，但未在开仓时设置止盈止损，请检查配置"
                    )
            
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
            from ..data.okx_client import OKXClient
            okx_client = OKXClient()
            
            # 查询现有的算法订单（止盈止损订单）
            # 查询算法订单（不传递ordType参数，让API返回所有类型的算法订单）
            # 注意：对于通过attachAlgoOrds创建的止盈止损订单，查询时不需要传递ordType参数
            algo_orders = okx_client.get_algo_orders(symbol=symbol, state='live', order_type=None)
            
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
                    cancel_result = okx_client.cancel_algo_order(symbol, algo_id)
                    
                    if cancel_result and isinstance(cancel_result, dict):
                        if cancel_result.get('code') == '0':
                            self.logger.info(
                                f"✅ [取消旧止盈止损] {symbol}: 已取消算法订单 {algo_id} "
                                f"(持仓方向={algo_pos_side})"
                            )
                            canceled_count += 1
                        else:
                            self.logger.warning(
                                f"⚠️ [取消旧止盈止损] {symbol}: 取消算法订单失败 {algo_id} | "
                                f"错误={cancel_result.get('msg', '未知错误')}"
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
            from ..data.okx_client import OKXClient
            okx_client = OKXClient()
            
            # 1. 检查是否有持仓
            positions_result = okx_client.get_positions(symbol)
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
                orders_result = okx_client.get_pending_orders(symbol)
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
                            cancel_result = okx_client.cancel_order(symbol, order_id)
                            if cancel_result and isinstance(cancel_result, dict):
                                if cancel_result.get('code') == '0':
                                    self.logger.info(
                                        f"✅ [撤销委托] {symbol}: 已撤销订单 {order_id}"
                                    )
                                    canceled_count += 1
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
            from decimal import Decimal
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
                return
            
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
                return
            
            # 设置止损订单（条件单）
            try:
                # 格式化数量字符串
                from decimal import Decimal
                size_str = str(Decimal(str(order_size)).normalize())
                
                # 格式化价格字符串
                stop_loss_price_str = str(Decimal(str(stop_loss_price)).normalize())
                take_profit_price_str = str(Decimal(str(take_profit_price)).normalize())
                
                if position_side == 'long' or side == 'buy':
                    # 做多：止损是卖出，止盈是卖出
                    # 止损：当价格 <= 止损价格时，卖出（市价）
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
                            
                            if stop_loss_result and stop_loss_result.get('code') == '0':
                                self.logger.info(
                                    f"✅ [止损订单设置成功] {symbol}: 做多 | "
                                    f"止损价={stop_loss_price:.5f} (低于开仓价{current_price:.5f}) | "
                                    f"数量={order_size:.4f}"
                                )
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
                            
                            if take_profit_result and take_profit_result.get('code') == '0':
                                self.logger.info(
                                    f"✅ [止盈订单设置成功] {symbol}: 做多 | "
                                    f"止盈价={take_profit_price:.5f} (高于开仓价{current_price:.5f}) | "
                                    f"数量={order_size:.4f}"
                                )
                            else:
                                self.logger.warning(
                                    f"❌ [止盈订单设置失败] {symbol}: {take_profit_result}"
                                )
                        except Exception as e:
                            self.logger.error(f"设置止盈订单失败 {symbol}: {e}")
                
                else:  # short or sell
                    # 做空：止损是买入，止盈是买入
                    # 止损：当价格 >= 止损价格时，买入（市价）
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
                            
                            if stop_loss_result and stop_loss_result.get('code') == '0':
                                self.logger.info(
                                    f"✅ [止损订单设置成功] {symbol}: 做空 | "
                                    f"止损价={stop_loss_price:.5f} (高于开仓价{current_price:.5f}) | "
                                    f"数量={order_size:.4f}"
                                )
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
                            
                            if take_profit_result and take_profit_result.get('code') == '0':
                                self.logger.info(
                                    f"✅ [止盈订单设置成功] {symbol}: 做空 | "
                                    f"止盈价={take_profit_price:.5f} (低于开仓价{current_price:.5f}) | "
                                    f"数量={order_size:.4f}"
                                )
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
        
        slippage = abs(order.average_price - expected_price) / expected_price
        return slippage
    
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

