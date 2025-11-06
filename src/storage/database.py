#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
数据库管理
PostgreSQL、InfluxDB、Redis的连接管理和操作封装
"""

from typing import Dict, List, Optional, Any
from ..core.config_manager import get_config_manager
from ..core.logger import get_logger
from ..core.exception import DataException


class DatabaseManager:
    """数据库管理器"""
    
    def __init__(self):
        """初始化数据库管理器"""
        self.config_mgr = get_config_manager()
        self.logger = get_logger("database")
        
        # 数据库连接
        self.postgres_client = None
        self.influx_client = None
        self.redis_client = None
        
        # 初始化连接
        self._init_connections()
    
    def _init_connections(self):
        """初始化数据库连接"""
        try:
            # PostgreSQL连接
            self._init_postgres()
            
            # InfluxDB连接
            self._init_influxdb()
            
            # Redis连接
            self._init_redis()
        
        except Exception as e:
            self.logger.error(f"数据库初始化失败: {e}")
    
    def _init_postgres(self):
        """初始化PostgreSQL连接"""
        try:
            from sqlalchemy import create_engine
            from sqlalchemy.orm import sessionmaker
            
            db_config = self.config_mgr.get_config('database', 'postgresql')
            host = db_config.get('host', 'localhost')
            port = db_config.get('port', 5432)
            database = db_config.get('database', 'trading_db')
            user = db_config.get('user', 'trading_user')
            password = db_config.get('password', '')
            
            if not password:
                self.logger.warning("PostgreSQL密码未配置，跳过连接")
                return
            
            connection_string = f"postgresql://{user}:{password}@{host}:{port}/{database}"
            self.postgres_engine = create_engine(connection_string, pool_pre_ping=True)
            self.PostgresSession = sessionmaker(bind=self.postgres_engine)
            
            self.logger.info(f"PostgreSQL连接成功: {host}:{port}/{database}")
        
        except ImportError:
            self.logger.warning("PostgreSQL驱动未安装（psycopg2-binary），跳过连接")
        except Exception as e:
            self.logger.warning(f"PostgreSQL连接失败: {e}")
    
    def _init_influxdb(self):
        """初始化InfluxDB连接"""
        try:
            from influxdb_client import InfluxDBClient, Point
            from influxdb_client.client.write_api import SYNCHRONOUS
            
            db_config = self.config_mgr.get_config('database', 'influxdb')
            host = db_config.get('host', 'localhost')
            port = db_config.get('port', 8086)
            database = db_config.get('database', 'trading_data')
            username = db_config.get('username', '')
            password = db_config.get('password', '')
            
            if not username or not password:
                self.logger.warning("InfluxDB认证信息未配置，跳过连接")
                return
            
            self.influx_client = InfluxDBClient(
                url=f"http://{host}:{port}",
                token=f"{username}:{password}",
                org="-"
            )
            self.influx_write_api = self.influx_client.write_api(write_options=SYNCHRONOUS)
            self.influx_query_api = self.influx_client.query_api()
            
            self.logger.info(f"InfluxDB连接成功: {host}:{port}/{database}")
        
        except ImportError:
            self.logger.warning("InfluxDB驱动未安装（influxdb-client），跳过连接")
        except Exception as e:
            self.logger.warning(f"InfluxDB连接失败: {e}")
    
    def _init_redis(self):
        """初始化Redis连接"""
        try:
            import redis
            
            db_config = self.config_mgr.get_config('database', 'redis')
            host = db_config.get('host', 'localhost')
            port = db_config.get('port', 6379)
            password = db_config.get('password', '')
            
            if password:
                self.redis_client = redis.Redis(
                    host=host,
                    port=port,
                    password=password,
                    decode_responses=True
                )
            else:
                self.redis_client = redis.Redis(
                    host=host,
                    port=port,
                    decode_responses=True
                )
            
            # 测试连接
            self.redis_client.ping()
            self.logger.info(f"Redis连接成功: {host}:{port}")
        
        except ImportError:
            self.logger.warning("Redis驱动未安装（redis），跳过连接")
        except Exception as e:
            self.logger.warning(f"Redis连接失败: {e}")
    
    def get_postgres_session(self):
        """获取PostgreSQL会话"""
        if not hasattr(self, 'PostgresSession'):
            raise DataException("PostgreSQL未初始化")
        return self.PostgresSession()
    
    def save_trade_to_postgres(self, trade_data: Dict[str, Any]):
        """
        保存交易到PostgreSQL
        
        Args:
            trade_data: 交易数据
        """
        if not hasattr(self, 'PostgresSession'):
            self.logger.warning("PostgreSQL未初始化，跳过保存")
            return
        
        try:
            from .models import Trade
            session = self.get_postgres_session()
            
            trade = Trade(
                symbol=trade_data.get('symbol'),
                side=trade_data.get('side'),
                order_id=trade_data.get('order_id'),
                price=trade_data.get('price'),
                size=trade_data.get('size'),
                fee=trade_data.get('fee', 0),
                timestamp=trade_data.get('timestamp')
            )
            
            session.add(trade)
            session.commit()
            session.close()
            
            self.logger.debug(f"交易已保存到PostgreSQL: {trade_data.get('order_id')}")
        
        except Exception as e:
            self.logger.error(f"保存交易到PostgreSQL失败: {e}")
    
    def save_market_data_to_influx(self, measurement: str, tags: Dict[str, str],
                                   fields: Dict[str, Any], timestamp: Any):
        """
        保存市场数据到InfluxDB
        
        Args:
            measurement: 测量名称
            tags: 标签字典
            fields: 字段字典
            timestamp: 时间戳
        """
        if not self.influx_client:
            self.logger.warning("InfluxDB未初始化，跳过保存")
            return
        
        try:
            from influxdb_client import Point
            
            point = Point(measurement)
            
            # 添加标签
            for key, value in tags.items():
                point = point.tag(key, value)
            
            # 添加字段
            for key, value in fields.items():
                point = point.field(key, value)
            
            # 设置时间戳
            point = point.time(timestamp)
            
            # 写入数据
            self.influx_write_api.write(
                bucket=self.config_mgr.get_config('database', 'influxdb.database'),
                record=point
            )
            
            self.logger.debug(f"市场数据已保存到InfluxDB: {measurement}")
        
        except Exception as e:
            self.logger.error(f"保存市场数据到InfluxDB失败: {e}")
    
    def get_from_redis(self, key: str) -> Optional[str]:
        """
        从Redis获取数据
        
        Args:
            key: 键名
            
        Returns:
            值
        """
        if not self.redis_client:
            return None
        
        try:
            return self.redis_client.get(key)
        except Exception as e:
            self.logger.error(f"从Redis获取数据失败: {e}")
            return None
    
    def set_to_redis(self, key: str, value: str, ex: Optional[int] = None):
        """
        设置数据到Redis
        
        Args:
            key: 键名
            value: 值
            ex: 过期时间（秒）
        """
        if not self.redis_client:
            return
        
        try:
            self.redis_client.set(key, value, ex=ex)
        except Exception as e:
            self.logger.error(f"设置数据到Redis失败: {e}")
    
    def close(self):
        """关闭所有数据库连接"""
        try:
            if hasattr(self, 'postgres_engine'):
                self.postgres_engine.dispose()
            
            if self.influx_client:
                self.influx_client.close()
            
            if self.redis_client:
                self.redis_client.close()
            
            self.logger.info("所有数据库连接已关闭")
        
        except Exception as e:
            self.logger.error(f"关闭数据库连接失败: {e}")


if __name__ == "__main__":
    # 测试数据库管理器
    db_manager = DatabaseManager()
    
    # 测试Redis
    db_manager.set_to_redis("test_key", "test_value", ex=60)
    value = db_manager.get_from_redis("test_key")
    print(f"Redis测试: {value}")

