#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
数据模型定义
SQLAlchemy ORM模型
"""

from datetime import datetime
from sqlalchemy import Column, Integer, String, Float, DateTime, Boolean, Text, ForeignKey
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship

Base = declarative_base()


class Trade(Base):
    """交易记录模型"""
    __tablename__ = 'trades'
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    symbol = Column(String(50), nullable=False, index=True)
    side = Column(String(10), nullable=False)  # buy, sell
    order_id = Column(String(100), unique=True, nullable=False, index=True)
    price = Column(Float, nullable=False)
    size = Column(Float, nullable=False)
    fee = Column(Float, default=0.0)
    status = Column(String(20), default='filled')  # filled, cancelled, rejected
    timestamp = Column(DateTime, default=datetime.now, index=True)
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)
    
    # 关联收益记录
    profit = relationship("TradeProfit", back_populates="trade", uselist=False)
    
    def to_dict(self):
        """转换为字典"""
        return {
            'id': self.id,
            'symbol': self.symbol,
            'side': self.side,
            'order_id': self.order_id,
            'price': self.price,
            'size': self.size,
            'fee': self.fee,
            'status': self.status,
            'timestamp': self.timestamp.isoformat() if self.timestamp else None,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None
        }


class TradeProfit(Base):
    """交易收益模型"""
    __tablename__ = 'trade_profits'
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    trade_id = Column(Integer, ForeignKey('trades.id'), unique=True, nullable=False)
    symbol = Column(String(50), nullable=False, index=True)
    entry_time = Column(DateTime, nullable=False)
    exit_time = Column(DateTime, nullable=False)
    entry_price = Column(Float, nullable=False)
    exit_price = Column(Float, nullable=False)
    quantity = Column(Float, nullable=False)
    gross_profit = Column(Float, nullable=False)
    fees = Column(Float, default=0.0)
    net_profit = Column(Float, nullable=False)
    profit_pct = Column(Float, nullable=False)
    return_rate = Column(Float, nullable=False)
    holding_time_seconds = Column(Float, nullable=False)
    created_at = Column(DateTime, default=datetime.now)
    
    # 关联交易
    trade = relationship("Trade", back_populates="profit")
    
    def to_dict(self):
        """转换为字典"""
        return {
            'id': self.id,
            'trade_id': self.trade_id,
            'symbol': self.symbol,
            'entry_time': self.entry_time.isoformat() if self.entry_time else None,
            'exit_time': self.exit_time.isoformat() if self.exit_time else None,
            'entry_price': self.entry_price,
            'exit_price': self.exit_price,
            'quantity': self.quantity,
            'gross_profit': self.gross_profit,
            'fees': self.fees,
            'net_profit': self.net_profit,
            'profit_pct': self.profit_pct,
            'return_rate': self.return_rate,
            'holding_time_seconds': self.holding_time_seconds,
            'created_at': self.created_at.isoformat() if self.created_at else None
        }


class DailyProfit(Base):
    """每日收益模型"""
    __tablename__ = 'daily_profits'
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    date = Column(DateTime, unique=True, nullable=False, index=True)
    total_trades = Column(Integer, default=0)
    winning_trades = Column(Integer, default=0)
    losing_trades = Column(Integer, default=0)
    win_rate = Column(Float, default=0.0)
    total_profit = Column(Float, default=0.0)
    total_profit_pct = Column(Float, default=0.0)
    avg_profit_per_trade = Column(Float, default=0.0)
    max_profit = Column(Float, default=0.0)
    max_loss = Column(Float, default=0.0)
    profit_loss_ratio = Column(Float, nullable=True)
    max_drawdown = Column(Float, default=0.0)
    start_balance = Column(Float, nullable=False)
    end_balance = Column(Float, nullable=False)
    balance_change = Column(Float, default=0.0)
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)
    
    def to_dict(self):
        """转换为字典"""
        return {
            'id': self.id,
            'date': self.date.isoformat() if self.date else None,
            'total_trades': self.total_trades,
            'winning_trades': self.winning_trades,
            'losing_trades': self.losing_trades,
            'win_rate': self.win_rate,
            'total_profit': self.total_profit,
            'total_profit_pct': self.total_profit_pct,
            'avg_profit_per_trade': self.avg_profit_per_trade,
            'max_profit': self.max_profit,
            'max_loss': self.max_loss,
            'profit_loss_ratio': self.profit_loss_ratio,
            'max_drawdown': self.max_drawdown,
            'start_balance': self.start_balance,
            'end_balance': self.end_balance,
            'balance_change': self.balance_change,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None
        }


class MonthlyProfit(Base):
    """每月收益模型"""
    __tablename__ = 'monthly_profits'
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    year = Column(Integer, nullable=False, index=True)
    month = Column(Integer, nullable=False, index=True)
    start_date = Column(DateTime, nullable=False)
    end_date = Column(DateTime, nullable=False)
    total_trading_days = Column(Integer, default=0)
    total_trades = Column(Integer, default=0)
    winning_trades = Column(Integer, default=0)
    losing_trades = Column(Integer, default=0)
    win_rate = Column(Float, default=0.0)
    total_profit = Column(Float, default=0.0)
    total_profit_pct = Column(Float, default=0.0)
    avg_daily_profit = Column(Float, default=0.0)
    avg_profit_per_trade = Column(Float, default=0.0)
    max_profit = Column(Float, default=0.0)
    max_loss = Column(Float, default=0.0)
    profit_loss_ratio = Column(Float, nullable=True)
    max_drawdown = Column(Float, default=0.0)
    sharpe_ratio = Column(Float, nullable=True)
    start_balance = Column(Float, nullable=False)
    end_balance = Column(Float, nullable=False)
    balance_change = Column(Float, default=0.0)
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)
    
    def to_dict(self):
        """转换为字典"""
        return {
            'id': self.id,
            'year': self.year,
            'month': self.month,
            'start_date': self.start_date.isoformat() if self.start_date else None,
            'end_date': self.end_date.isoformat() if self.end_date else None,
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
            'balance_change': self.balance_change,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None
        }


class Signal(Base):
    """信号记录模型"""
    __tablename__ = 'signals'
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    symbol = Column(String(50), nullable=False, index=True)
    signal_type = Column(String(10), nullable=False)  # buy, sell, hold
    strength = Column(Float, nullable=False)
    source = Column(String(50), nullable=False)  # technical, funding, ai, combined
    data = Column(Text)  # JSON格式存储
    timestamp = Column(DateTime, default=datetime.now, index=True)
    created_at = Column(DateTime, default=datetime.now)
    
    def to_dict(self):
        """转换为字典"""
        return {
            'id': self.id,
            'symbol': self.symbol,
            'signal_type': self.signal_type,
            'strength': self.strength,
            'source': self.source,
            'data': self.data,
            'timestamp': self.timestamp.isoformat() if self.timestamp else None,
            'created_at': self.created_at.isoformat() if self.created_at else None
        }


class Decision(Base):
    """决策记录模型"""
    __tablename__ = 'decisions'
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    symbol = Column(String(50), nullable=False, index=True)
    action = Column(String(10), nullable=False)  # buy, sell, hold
    position_size = Column(Float, nullable=False)
    price = Column(Float, nullable=True)
    stop_loss = Column(Float, nullable=True)
    take_profit = Column(Float, nullable=True)
    confidence = Column(Float, nullable=False)
    reasoning = Column(Text)
    signals_data = Column(Text)  # JSON格式存储
    risk_assessment = Column(Text)  # JSON格式存储
    executed = Column(Boolean, default=False)
    timestamp = Column(DateTime, default=datetime.now, index=True)
    created_at = Column(DateTime, default=datetime.now)
    
    def to_dict(self):
        """转换为字典"""
        return {
            'id': self.id,
            'symbol': self.symbol,
            'action': self.action,
            'position_size': self.position_size,
            'price': self.price,
            'stop_loss': self.stop_loss,
            'take_profit': self.take_profit,
            'confidence': self.confidence,
            'reasoning': self.reasoning,
            'signals_data': self.signals_data,
            'risk_assessment': self.risk_assessment,
            'executed': self.executed,
            'timestamp': self.timestamp.isoformat() if self.timestamp else None,
            'created_at': self.created_at.isoformat() if self.created_at else None
        }


def create_tables(engine):
    """创建所有表"""
    Base.metadata.create_all(engine)


if __name__ == "__main__":
    # 测试数据模型
    from sqlalchemy import create_engine
    
    # 使用内存数据库测试
    engine = create_engine('sqlite:///:memory:', echo=True)
    create_tables(engine)
    
    print("数据模型测试完成，表已创建")

