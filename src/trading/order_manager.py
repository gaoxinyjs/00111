#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
订单管理器
订单生命周期管理，订单状态跟踪，订单执行监控，订单历史记录
"""

from typing import Dict, List, Optional, Any
from datetime import datetime
from dataclasses import dataclass
from enum import Enum
from ..core.config_manager import get_config_manager
from ..core.logger import get_logger
from ..data.okx_client import OKXClient
from ..core.exception import OrderException


class OrderStatus(Enum):
    """订单状态"""

    PENDING = "pending"  # 待提交
    SUBMITTED = "submitted"  # 已提交
    PARTIAL_FILLED = "partial_filled"  # 部分成交
    FILLED = "filled"  # 完全成交
    CANCELLED = "cancelled"  # 已取消
    REJECTED = "rejected"  # 已拒绝
    EXPIRED = "expired"  # 已过期


@dataclass
class Order:
    """订单"""

    order_id: str
    symbol: str
    side: str  # buy, sell
    order_type: str  # market, limit
    size: float
    price: Optional[float] = None
    status: OrderStatus = OrderStatus.PENDING
    filled_size: float = 0.0
    filled_price: float = 0.0
    average_price: float = 0.0
    created_at: datetime = None
    updated_at: datetime = None
    executed_at: Optional[datetime] = None
    # 合约交易相关字段
    position_side: Optional[str] = None  # long或short（合约交易）
    is_closing: bool = False  # 是否平仓（合约交易）
    # 止盈止损价格（在创建订单时设置）
    stop_loss_price: Optional[float] = None  # 止损触发价格
    take_profit_price: Optional[float] = None  # 止盈触发价格

    def __post_init__(self):
        if self.created_at is None:
            self.created_at = datetime.now()
        if self.updated_at is None:
            self.updated_at = datetime.now()

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "order_id": self.order_id,
            "symbol": self.symbol,
            "side": self.side,
            "order_type": self.order_type,
            "size": self.size,
            "price": self.price,
            "status": self.status.value,
            "filled_size": self.filled_size,
            "filled_price": self.filled_price,
            "average_price": self.average_price,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            "executed_at": self.executed_at.isoformat() if self.executed_at else None,
        }


class OrderManager:
    """订单管理器"""

    def __init__(self):
        """初始化订单管理器"""
        self.config_mgr = get_config_manager()
        self.logger = get_logger("order_manager")
        self.okx_client = OKXClient.get_instance()

        # 订单存储
        self.orders: Dict[str, Order] = {}
        self.order_history: List[Order] = []

    def create_order(
        self,
        symbol: str,
        side: str,
        order_type: str,
        size: float,
        price: Optional[float] = None,
        position_side: Optional[str] = None,
        is_closing: bool = False,
    ) -> Order:
        """
        创建订单（支持合约交易）

        Args:
            symbol: 交易对符号
            side: 方向（buy, sell）
            order_type: 订单类型（market, limit）
            size: 数量
            price: 价格（限价单必填）
            position_side: 持仓方向（long, short）- 合约交易使用
            is_closing: 是否平仓 - 合约交易使用

        Returns:
            订单对象
        """
        try:
            # 验证订单
            if order_type == "limit" and price is None:
                raise OrderException("限价单必须指定价格")

            if size <= 0:
                raise OrderException("订单数量必须大于0")

            # 生成订单ID
            order_id = f"{symbol}_{side}_{int(datetime.now().timestamp() * 1000)}"

            # 创建订单对象
            order = Order(
                order_id=order_id,
                symbol=symbol,
                side=side,
                order_type=order_type,
                size=size,
                price=price,
                position_side=position_side,  # 合约交易：持仓方向
                is_closing=is_closing,  # 合约交易：是否平仓
            )

            # 存储订单
            self.orders[order_id] = order

            self.logger.info(
                f"创建订单: {order_id}, {symbol} {side} {size} @ {price or '市价'}"
            )

            return order

        except Exception as e:
            self.logger.error(f"创建订单失败: {e}")
            raise OrderException(f"创建订单失败: {e}")

    def submit_order(self, order: Order) -> Order:
        """
        提交订单到交易所

        Args:
            order: 订单对象

        Returns:
            更新后的订单对象
        """
        try:
            if order.status != OrderStatus.PENDING:
                raise OrderException(f"订单状态不正确，无法提交: {order.status}")

            # 调用OKX API下单（支持合约交易，支持同时设置止盈止损）
            # 从订单对象中获取止盈止损价格（如果之前已设置）
            stop_loss_price = getattr(order, "stop_loss_price", None)
            take_profit_price = getattr(order, "take_profit_price", None)

            result = self.okx_client.place_order(
                symbol=order.symbol,
                side=order.side,
                order_type=order.order_type,
                size=str(order.size),
                price=str(order.price) if order.price else None,
                pos_side=order.position_side,  # 合约交易：持仓方向（long或short）
                reduce_only=order.is_closing,  # 合约交易：是否平仓
                stop_loss_price=(
                    str(stop_loss_price) if stop_loss_price else None
                ),  # 止损触发价格
                take_profit_price=(
                    str(take_profit_price) if take_profit_price else None
                ),  # 止盈触发价格
            )

            # 更新订单状态
            if result:
                # OKX API返回格式可能是数组或字典
                # 如果是数组，取第一个元素
                okx_order_data = None
                if isinstance(result, list) and len(result) > 0:
                    okx_order_data = result[0]
                elif isinstance(result, dict):
                    okx_order_data = result

                # 提取OKX返回的真实订单ID
                if okx_order_data:
                    okx_ord_id = okx_order_data.get("ordId", "")
                    s_code = okx_order_data.get("sCode", "")
                    s_msg = okx_order_data.get("sMsg", "")

                    if s_code == "0" and okx_ord_id:
                        # 订单提交成功，更新为OKX返回的真实订单ID
                        old_order_id = order.order_id  # 保存原订单ID用于日志
                        order.order_id = okx_ord_id
                        order.status = OrderStatus.SUBMITTED
                        order.updated_at = datetime.now()
                        self.logger.info(
                            f"订单已提交成功: OKX订单ID={okx_ord_id} (原ID={old_order_id})"
                        )
                    else:
                        # 订单提交失败
                        order.status = OrderStatus.REJECTED
                        order.updated_at = datetime.now()
                        self.logger.error(f"订单提交失败: sCode={s_code}, sMsg={s_msg}")
                else:
                    # 结果格式不正确
                    order.status = OrderStatus.REJECTED
                    order.updated_at = datetime.now()
                    self.logger.warning(f"订单提交失败: API返回格式不正确")
            else:
                order.status = OrderStatus.REJECTED
                order.updated_at = datetime.now()

                self.logger.warning(f"订单被拒绝: {order.order_id}")

            return order

        except Exception as e:
            order.status = OrderStatus.REJECTED
            order.updated_at = datetime.now()
            self.logger.error(f"提交订单失败 {order.order_id}: {e}")
            raise OrderException(f"提交订单失败: {e}")

    def cancel_order(self, order: Order) -> Order:
        """
        取消订单

        Args:
            order: 订单对象

        Returns:
            更新后的订单对象
        """
        try:
            if order.status not in [OrderStatus.SUBMITTED, OrderStatus.PARTIAL_FILLED]:
                raise OrderException(f"订单状态不正确，无法取消: {order.status}")

            # 调用OKX API撤单
            result = self.okx_client.cancel_order(order.symbol, order.order_id)

            if result:
                order.status = OrderStatus.CANCELLED
                order.updated_at = datetime.now()

                self.logger.info(f"订单已取消: {order.order_id}")
            else:
                self.logger.warning(f"取消订单失败: {order.order_id}")

            return order

        except Exception as e:
            self.logger.error(f"取消订单失败 {order.order_id}: {e}")
            raise OrderException(f"取消订单失败: {e}")

    def update_order_status(self, order: Order) -> Order:
        """
        更新订单状态（从交易所查询）

        Args:
            order: 订单对象

        Returns:
            更新后的订单对象
        """
        try:
            # 检查订单ID：必须是OKX返回的真实订单ID（纯数字），而不是内部生成的ID
            if not order.order_id:
                self.logger.debug(f"订单ID为空，无法查询状态")
                return order

            # 检查是否是内部生成的订单ID（格式：symbol_side_timestamp）
            # 如果是内部ID，说明订单还没有提交成功或订单ID未更新
            if (
                order.order_id.startswith(order.symbol + "_")
                or not order.order_id.isdigit()
            ):
                self.logger.debug(
                    f"订单ID是内部生成的，尚未提交到交易所: {order.order_id}"
                )
                # 如果订单状态是SUBMITTED但没有真实订单ID，可能是提交失败
                if order.status == OrderStatus.SUBMITTED:
                    self.logger.warning(
                        f"订单状态为SUBMITTED但订单ID是内部ID，可能提交失败或未更新"
                    )
                    # 尝试重新提交或标记为失败
                    order.status = OrderStatus.REJECTED
                return order

            # 调用OKX API查询订单状态（使用OKX返回的真实订单ID）
            result = self.okx_client.get_order_status(order.symbol, order.order_id)

            if result:
                # OKX API返回格式可能是数组或字典
                okx_order_data = None
                if isinstance(result, list) and len(result) > 0:
                    okx_order_data = result[0]
                elif isinstance(result, dict):
                    okx_order_data = result

                if not okx_order_data:
                    self.logger.warning(f"查询订单状态失败: API返回格式不正确")
                    return order

                # 解析订单状态
                okx_state = okx_order_data.get("state", "")
                # 安全转换：处理空字符串和None
                acc_fill_sz = okx_order_data.get("accFillSz", "0")
                if acc_fill_sz == "" or acc_fill_sz is None:
                    acc_fill_sz = "0"
                filled_size = float(acc_fill_sz) if acc_fill_sz else 0.0

                avg_px = okx_order_data.get("avgPx", "0")
                if avg_px == "" or avg_px is None:
                    avg_px = "0"
                filled_price = float(avg_px) if avg_px else 0.0

                # 更新订单
                order.filled_size = filled_size
                order.filled_price = filled_price
                order.average_price = filled_price
                order.updated_at = datetime.now()

                # 更新状态
                if okx_state == "filled":
                    order.status = OrderStatus.FILLED
                    if not order.executed_at:
                        order.executed_at = datetime.now()
                elif okx_state == "partially_filled":
                    order.status = OrderStatus.PARTIAL_FILLED
                elif okx_state == "canceled":
                    order.status = OrderStatus.CANCELLED
                elif okx_state == "live":
                    order.status = OrderStatus.SUBMITTED

                self.logger.debug(
                    f"订单状态已更新: {order.order_id} = {order.status.value}"
                )

            return order

        except Exception as e:
            self.logger.error(f"更新订单状态失败 {order.order_id}: {e}")
            return order

    def get_order(self, order_id: str) -> Optional[Order]:
        """获取订单"""
        return self.orders.get(order_id)

    def get_active_orders(self, symbol: Optional[str] = None) -> List[Order]:
        """
        获取活跃订单

        Args:
            symbol: 交易对符号，如果为None则返回所有

        Returns:
            活跃订单列表
        """
        active_statuses = [
            OrderStatus.PENDING,
            OrderStatus.SUBMITTED,
            OrderStatus.PARTIAL_FILLED,
        ]

        active_orders = [
            order for order in self.orders.values() if order.status in active_statuses
        ]

        if symbol:
            active_orders = [order for order in active_orders if order.symbol == symbol]

        return active_orders

    def archive_order(self, order: Order):
        """
        归档订单（从活跃订单移到历史）

        Args:
            order: 订单对象
        """
        if order.order_id in self.orders:
            # 移到历史
            self.order_history.append(order)

            # 保留最近1000条历史
            if len(self.order_history) > 1000:
                self.order_history = self.order_history[-1000:]

            # 从活跃订单移除（如果已完成或取消）
            if order.status in [
                OrderStatus.FILLED,
                OrderStatus.CANCELLED,
                OrderStatus.REJECTED,
                OrderStatus.EXPIRED,
            ]:
                del self.orders[order.order_id]


if __name__ == "__main__":
    # 测试订单管理器
    manager = OrderManager()

    # 创建测试订单
    order = manager.create_order(
        symbol="BTC-USDT", side="buy", order_type="limit", size=0.001, price=50000
    )

    print(f"订单ID: {order.order_id}")
    print(f"订单状态: {order.status.value}")
    print(f"订单信息: {order.to_dict()}")
