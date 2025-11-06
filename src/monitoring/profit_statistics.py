#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
收益统计
实时收益计算和统计，多维度收益分析（按交易、小时、天、月）
"""

from typing import Dict, List, Optional, Any
from datetime import datetime, date, timedelta
from dataclasses import dataclass
from ..core.config_manager import get_config_manager
from ..core.logger import get_logger
from ..core.exception import TradingSystemException


@dataclass
class TradeProfit:
    """单笔交易收益"""
    trade_id: str
    symbol: str
    entry_time: datetime
    exit_time: datetime
    entry_price: float
    exit_price: float
    quantity: float
    gross_profit: float
    fees: float
    net_profit: float
    profit_pct: float
    holding_time: timedelta
    return_rate: float
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            'trade_id': self.trade_id,
            'symbol': self.symbol,
            'entry_time': self.entry_time.isoformat(),
            'exit_time': self.exit_time.isoformat(),
            'entry_price': self.entry_price,
            'exit_price': self.exit_price,
            'quantity': self.quantity,
            'gross_profit': self.gross_profit,
            'fees': self.fees,
            'net_profit': self.net_profit,
            'profit_pct': self.profit_pct,
            'holding_time_seconds': self.holding_time.total_seconds(),
            'return_rate': self.return_rate
        }


@dataclass
class HourlyProfit:
    """小时收益统计"""
    hour: int
    date: date
    symbol: Optional[str]
    total_trades: int
    winning_trades: int
    losing_trades: int
    win_rate: float
    total_profit: float
    total_profit_pct: float
    avg_profit_per_trade: float
    max_profit: float
    max_loss: float
    profit_loss_ratio: Optional[float]


@dataclass
class DailyProfit:
    """每日收益统计"""
    date: date
    total_trades: int
    winning_trades: int
    losing_trades: int
    win_rate: float
    total_profit: float
    total_profit_pct: float
    avg_profit_per_trade: float
    max_profit: float
    max_loss: float
    profit_loss_ratio: Optional[float]
    max_drawdown: float
    start_balance: float
    end_balance: float
    balance_change: float


@dataclass
class MonthlyProfit:
    """每月收益统计"""
    year: int
    month: int
    start_date: date
    end_date: date
    total_trading_days: int
    total_trades: int
    winning_trades: int
    losing_trades: int
    win_rate: float
    total_profit: float
    total_profit_pct: float
    avg_daily_profit: float
    avg_profit_per_trade: float
    max_profit: float
    max_loss: float
    profit_loss_ratio: Optional[float]
    max_drawdown: float
    sharpe_ratio: Optional[float]
    start_balance: float
    end_balance: float
    balance_change: float
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            'year': self.year,
            'month': self.month,
            'start_date': self.start_date.isoformat(),
            'end_date': self.end_date.isoformat(),
            'total_trading_days': self.total_trading_days,
            'total_trades': self.total_trades,
            'winning_trades': self.winning_trades,
            'losing_trades': self.losing_trades,
            'win_rate': self.win_rate,
            'total_profit': self.total_profit,
            'total_profit_pct': self.total_profit_pct,
            'avg_daily_profit': self.avg_daily_profit,
            'avg_profit_per_trade': self.avg_profit_per_trade,
            'max_profit': self.max_profit,
            'max_loss': self.max_loss,
            'profit_loss_ratio': self.profit_loss_ratio,
            'max_drawdown': self.max_drawdown,
            'sharpe_ratio': self.sharpe_ratio,
            'start_balance': self.start_balance,
            'end_balance': self.end_balance,
            'balance_change': self.balance_change
        }


class ProfitStatistics:
    """收益统计"""
    
    def __init__(self):
        """初始化收益统计"""
        self.config_mgr = get_config_manager()
        self.logger = get_logger("profit_statistics")
        
        # 交易收益存储
        self.trade_profits: List[TradeProfit] = []
        self.hourly_profits: Dict[str, HourlyProfit] = {}
        self.daily_profits: Dict[date, DailyProfit] = {}
        self.monthly_profits: Dict[tuple, MonthlyProfit] = {}
        
        # 账户余额历史
        self.balance_snapshots: List[Dict[str, Any]] = []
    
    def calculate_trade_profit(self, trade: Dict[str, Any]) -> TradeProfit:
        """
        计算单笔交易收益
        
        Args:
            trade: 交易记录（包含entry_time, exit_time, entry_price, exit_price, quantity, fees等）
            
        Returns:
            交易收益对象
        """
        try:
            entry_price = float(trade.get('entry_price', 0))
            exit_price = float(trade.get('exit_price', 0))
            quantity = float(trade.get('quantity', 0))
            fees = float(trade.get('fees', 0))
            
            # 计算收益
            gross_profit = (exit_price - entry_price) * quantity
            net_profit = gross_profit - fees
            
            # 计算百分比
            profit_pct = ((exit_price - entry_price) / entry_price) * 100 if entry_price > 0 else 0
            return_rate = (net_profit / (entry_price * quantity)) * 100 if entry_price * quantity > 0 else 0
            
            # 持仓时间
            entry_time = trade.get('entry_time')
            exit_time = trade.get('exit_time')
            if isinstance(entry_time, str):
                entry_time = datetime.fromisoformat(entry_time)
            if isinstance(exit_time, str):
                exit_time = datetime.fromisoformat(exit_time)
            
            holding_time = exit_time - entry_time if exit_time and entry_time else timedelta(0)
            
            trade_profit = TradeProfit(
                trade_id=trade.get('trade_id', ''),
                symbol=trade.get('symbol', ''),
                entry_time=entry_time or datetime.now(),
                exit_time=exit_time or datetime.now(),
                entry_price=entry_price,
                exit_price=exit_price,
                quantity=quantity,
                gross_profit=gross_profit,
                fees=fees,
                net_profit=net_profit,
                profit_pct=profit_pct,
                holding_time=holding_time,
                return_rate=return_rate
            )
            
            # 存储
            self.trade_profits.append(trade_profit)
            
            self.logger.info(
                f"计算交易收益: {trade_profit.symbol} {trade_profit.trade_id}, "
                f"收益={trade_profit.net_profit:.2f}, 收益率={trade_profit.return_rate:.2f}%"
            )
            
            return trade_profit
        
        except Exception as e:
            self.logger.error(f"计算交易收益失败: {e}")
            raise TradingSystemException(f"计算交易收益失败: {e}")
    
    def calculate_hourly_profit(self, target_date: date, hour: int) -> Optional[HourlyProfit]:
        """
        计算小时收益统计
        
        Args:
            target_date: 日期
            hour: 小时（0-23）
            
        Returns:
            小时收益统计
        """
        try:
            # 获取该小时的所有交易
            start_time = datetime.combine(target_date, datetime.min.time().replace(hour=hour))
            end_time = start_time + timedelta(hours=1)
            
            trades_in_hour = [
                tp for tp in self.trade_profits
                if start_time <= tp.exit_time < end_time
            ]
            
            if not trades_in_hour:
                return None
            
            # 计算统计指标
            total_trades = len(trades_in_hour)
            winning_trades = len([t for t in trades_in_hour if t.net_profit > 0])
            losing_trades = len([t for t in trades_in_hour if t.net_profit < 0])
            win_rate = winning_trades / total_trades if total_trades > 0 else 0
            
            total_profit = sum(t.net_profit for t in trades_in_hour)
            total_profit_pct = sum(t.profit_pct for t in trades_in_hour)
            avg_profit_per_trade = total_profit / total_trades if total_trades > 0 else 0
            
            max_profit = max((t.net_profit for t in trades_in_hour), default=0.0)
            max_loss = min((t.net_profit for t in trades_in_hour), default=0.0)
            
            # 计算盈亏比
            avg_profit = sum(t.net_profit for t in trades_in_hour if t.net_profit > 0) / winning_trades if winning_trades > 0 else 0
            avg_loss = sum(t.net_profit for t in trades_in_hour if t.net_profit < 0) / losing_trades if losing_trades < 0 else 0
            profit_loss_ratio = abs(avg_profit / avg_loss) if avg_loss != 0 else None
            
            hourly_profit = HourlyProfit(
                hour=hour,
                date=target_date,
                symbol=None,  # 可以按交易对细分
                total_trades=total_trades,
                winning_trades=winning_trades,
                losing_trades=losing_trades,
                win_rate=win_rate,
                total_profit=total_profit,
                total_profit_pct=total_profit_pct,
                avg_profit_per_trade=avg_profit_per_trade,
                max_profit=max_profit,
                max_loss=max_loss,
                profit_loss_ratio=profit_loss_ratio
            )
            
            # 存储
            key = f"{target_date}_{hour}"
            self.hourly_profits[key] = hourly_profit
            
            return hourly_profit
        
        except Exception as e:
            self.logger.error(f"计算小时收益失败: {e}")
            return None
    
    def calculate_daily_profit(self, target_date: date) -> Optional[DailyProfit]:
        """
        计算每日收益统计
        
        Args:
            target_date: 日期
            
        Returns:
            每日收益统计
        """
        try:
            # 获取该日的所有交易
            start_time = datetime.combine(target_date, datetime.min.time())
            end_time = start_time + timedelta(days=1)
            
            trades_on_date = [
                tp for tp in self.trade_profits
                if start_time <= tp.exit_time < end_time
            ]
            
            # 获取期初和期末余额
            start_balance = self._get_balance_snapshot(target_date, start_time)
            end_balance = self._get_balance_snapshot(target_date, end_time)
            
            if not trades_on_date and start_balance == end_balance:
                return None
            
            # 计算统计指标
            total_trades = len(trades_on_date)
            winning_trades = len([t for t in trades_on_date if t.net_profit > 0])
            losing_trades = len([t for t in trades_on_date if t.net_profit < 0])
            win_rate = winning_trades / total_trades if total_trades > 0 else 0
            
            total_profit = sum(t.net_profit for t in trades_on_date)
            total_profit_pct = ((end_balance - start_balance) / start_balance * 100) if start_balance > 0 else 0
            avg_profit_per_trade = total_profit / total_trades if total_trades > 0 else 0
            
            max_profit = max((t.net_profit for t in trades_on_date), default=0.0)
            max_loss = min((t.net_profit for t in trades_on_date), default=0.0)
            
            # 计算盈亏比
            avg_profit = sum(t.net_profit for t in trades_on_date if t.net_profit > 0) / winning_trades if winning_trades > 0 else 0
            avg_loss = sum(t.net_profit for t in trades_on_date if t.net_profit < 0) / losing_trades if losing_trades > 0 else 0
            profit_loss_ratio = abs(avg_profit / avg_loss) if avg_loss != 0 else None
            
            # 计算最大回撤（简化版）
            max_drawdown = self._calculate_max_drawdown_for_date(target_date)
            
            daily_profit = DailyProfit(
                date=target_date,
                total_trades=total_trades,
                winning_trades=winning_trades,
                losing_trades=losing_trades,
                win_rate=win_rate,
                total_profit=total_profit,
                total_profit_pct=total_profit_pct,
                avg_profit_per_trade=avg_profit_per_trade,
                max_profit=max_profit,
                max_loss=max_loss,
                profit_loss_ratio=profit_loss_ratio,
                max_drawdown=max_drawdown,
                start_balance=start_balance,
                end_balance=end_balance,
                balance_change=end_balance - start_balance
            )
            
            # 存储
            self.daily_profits[target_date] = daily_profit
            
            self.logger.info(
                f"计算每日收益: {target_date}, "
                f"收益={total_profit:.2f}, 收益率={total_profit_pct:.2f}%, "
                f"交易次数={total_trades}, 胜率={win_rate:.2%}"
            )
            
            return daily_profit
        
        except Exception as e:
            self.logger.error(f"计算每日收益失败: {e}")
            return None
    
    def calculate_monthly_profit(self, year: int, month: int) -> Optional[MonthlyProfit]:
        """
        计算每月收益统计
        
        Args:
            year: 年份
            month: 月份
            
        Returns:
            每月收益统计
        """
        try:
            start_date = date(year, month, 1)
            
            # 获取月末日期
            if month == 12:
                end_date = date(year + 1, 1, 1) - timedelta(days=1)
            else:
                end_date = date(year, month + 1, 1) - timedelta(days=1)
            
            # 获取该月的所有交易
            trades_in_month = [
                tp for tp in self.trade_profits
                if start_date <= tp.exit_time.date() <= end_date
            ]
            
            # 获取期初和期末余额
            start_balance = self._get_balance_snapshot(start_date, datetime.combine(start_date, datetime.min.time()))
            end_balance = self._get_balance_snapshot(end_date, datetime.combine(end_date, datetime.max.time()))
            
            # 计算每日收益序列
            daily_profits_list = []
            current_date = start_date
            trading_days = 0
            
            while current_date <= end_date:
                daily_profit = self.calculate_daily_profit(current_date)
                if daily_profit and daily_profit.total_trades > 0:
                    daily_profits_list.append(daily_profit)
                    trading_days += 1
                current_date += timedelta(days=1)
            
            # 计算统计指标
            total_trades = len(trades_in_month)
            winning_trades = len([t for t in trades_in_month if t.net_profit > 0])
            losing_trades = len([t for t in trades_in_month if t.net_profit < 0])
            win_rate = winning_trades / total_trades if total_trades > 0 else 0
            
            total_profit = sum(t.net_profit for t in trades_in_month)
            total_profit_pct = ((end_balance - start_balance) / start_balance * 100) if start_balance > 0 else 0
            avg_daily_profit = sum(d.total_profit for d in daily_profits_list) / len(daily_profits_list) if daily_profits_list else 0
            avg_profit_per_trade = total_profit / total_trades if total_trades > 0 else 0
            
            max_profit = max((t.net_profit for t in trades_in_month), default=0.0)
            max_loss = min((t.net_profit for t in trades_in_month), default=0.0)
            
            # 计算盈亏比
            avg_profit = sum(t.net_profit for t in trades_in_month if t.net_profit > 0) / winning_trades if winning_trades > 0 else 0
            avg_loss = sum(t.net_profit for t in trades_in_month if t.net_profit < 0) / losing_trades if losing_trades > 0 else 0
            profit_loss_ratio = abs(avg_profit / avg_loss) if avg_loss != 0 else None
            
            # 计算最大回撤
            max_drawdown = self._calculate_max_drawdown_for_period(start_date, end_date)
            
            # 计算夏普比率（简化版）
            sharpe_ratio = self._calculate_sharpe_ratio(daily_profits_list) if daily_profits_list else None
            
            monthly_profit = MonthlyProfit(
                year=year,
                month=month,
                start_date=start_date,
                end_date=end_date,
                total_trading_days=trading_days,
                total_trades=total_trades,
                winning_trades=winning_trades,
                losing_trades=losing_trades,
                win_rate=win_rate,
                total_profit=total_profit,
                total_profit_pct=total_profit_pct,
                avg_daily_profit=avg_daily_profit,
                avg_profit_per_trade=avg_profit_per_trade,
                max_profit=max_profit,
                max_loss=max_loss,
                profit_loss_ratio=profit_loss_ratio,
                max_drawdown=max_drawdown,
                sharpe_ratio=sharpe_ratio,
                start_balance=start_balance,
                end_balance=end_balance,
                balance_change=end_balance - start_balance
            )
            
            # 存储
            self.monthly_profits[(year, month)] = monthly_profit
            
            self.logger.info(
                f"计算每月收益: {year}-{month:02d}, "
                f"收益={total_profit:.2f}, 收益率={total_profit_pct:.2f}%, "
                f"交易次数={total_trades}, 胜率={win_rate:.2%}, "
                f"夏普比率={sharpe_ratio:.2f if sharpe_ratio else 'N/A'}"
            )
            
            return monthly_profit
        
        except Exception as e:
            self.logger.error(f"计算每月收益失败: {e}")
            return None
    
    def _get_balance_snapshot(self, target_date: date, timestamp: datetime) -> float:
        """
        获取账户余额快照
        
        Args:
            target_date: 日期
            timestamp: 时间戳
            
        Returns:
            余额
        """
        # 简化实现：从快照中查找
        for snapshot in reversed(self.balance_snapshots):
            snapshot_time = snapshot.get('timestamp')
            if isinstance(snapshot_time, str):
                snapshot_time = datetime.fromisoformat(snapshot_time)
            
            if snapshot_time <= timestamp:
                return float(snapshot.get('balance', 0))
        
        return 10000.0  # 默认余额
    
    def _calculate_max_drawdown_for_date(self, target_date: date) -> float:
        """计算单日最大回撤（简化版）"""
        # 简化实现：返回0
        return 0.0
    
    def _calculate_max_drawdown_for_period(self, start_date: date, end_date: date) -> float:
        """计算期间最大回撤"""
        # 简化实现：返回0
        return 0.0
    
    def _calculate_sharpe_ratio(self, daily_profits: List[DailyProfit]) -> Optional[float]:
        """
        计算夏普比率
        
        Args:
            daily_profits: 每日收益列表
            
        Returns:
            夏普比率
        """
        if not daily_profits or len(daily_profits) < 2:
            return None
        
        try:
            # 计算日收益率
            returns = [
                (dp.end_balance - dp.start_balance) / dp.start_balance
                if dp.start_balance > 0 else 0
                for dp in daily_profits
            ]
            
            if not returns:
                return None
            
            import numpy as np
            
            mean_return = np.mean(returns)
            std_return = np.std(returns)
            
            if std_return == 0:
                return None
            
            # 年化夏普比率（假设252个交易日）
            sharpe_ratio = (mean_return / std_return) * np.sqrt(252)
            
            return float(sharpe_ratio)
        
        except Exception as e:
            self.logger.warning(f"计算夏普比率失败: {e}")
            return None
    
    def save_balance_snapshot(self, balance: float, available_balance: float = None,
                             frozen_balance: float = None):
        """
        保存账户余额快照
        
        Args:
            balance: 总余额
            available_balance: 可用余额
            frozen_balance: 冻结余额
        """
        snapshot = {
            'timestamp': datetime.now(),
            'balance': balance,
            'available_balance': available_balance or balance,
            'frozen_balance': frozen_balance or 0.0
        }
        
        self.balance_snapshots.append(snapshot)
        
        # 保留最近10000条快照
        if len(self.balance_snapshots) > 10000:
            self.balance_snapshots = self.balance_snapshots[-10000:]
    
    def get_trade_profit(self, trade_id: str) -> Optional[TradeProfit]:
        """获取单笔交易收益"""
        for tp in self.trade_profits:
            if tp.trade_id == trade_id:
                return tp
        return None
    
    def get_trades_profit_on_date(self, target_date: date) -> List[TradeProfit]:
        """获取某日的所有交易收益"""
        start_time = datetime.combine(target_date, datetime.min.time())
        end_time = start_time + timedelta(days=1)
        
        return [
            tp for tp in self.trade_profits
            if start_time <= tp.exit_time < end_time
        ]
    
    def get_daily_profit(self, target_date: date) -> Optional[DailyProfit]:
        """获取每日收益"""
        if target_date in self.daily_profits:
            return self.daily_profits[target_date]
        
        # 如果不存在，计算并返回
        return self.calculate_daily_profit(target_date)
    
    def get_monthly_profit(self, year: int, month: int) -> Optional[MonthlyProfit]:
        """获取每月收益"""
        key = (year, month)
        if key in self.monthly_profits:
            return self.monthly_profits[key]
        
        # 如果不存在，计算并返回
        return self.calculate_monthly_profit(year, month)


if __name__ == "__main__":
    # 测试收益统计
    stats = ProfitStatistics()
    
    # 模拟交易
    trade = {
        'trade_id': 'test_001',
        'symbol': 'BTC-USDT',
        'entry_time': datetime.now() - timedelta(hours=2),
        'exit_time': datetime.now(),
        'entry_price': 50000,
        'exit_price': 50500,
        'quantity': 0.1,
        'fees': 10
    }
    
    trade_profit = stats.calculate_trade_profit(trade)
    print(f"交易收益: {trade_profit.net_profit:.2f}, 收益率: {trade_profit.return_rate:.2f}%")
    
    # 计算今日收益
    today = date.today()
    daily_profit = stats.calculate_daily_profit(today)
    if daily_profit:
        print(f"今日收益: {daily_profit.total_profit:.2f}, 收益率: {daily_profit.total_profit_pct:.2f}%")

