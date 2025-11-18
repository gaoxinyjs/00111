#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
日志管理器
统一的日志记录接口，分级日志，日志轮转和归档
"""

import sys
import logging
from pathlib import Path
from logging.handlers import RotatingFileHandler
from typing import Optional
from .config_manager import get_config_manager


class Logger:
    """日志管理器"""
    
    def __init__(self, name: str = "trading_system"):
        """
        初始化日志管理器
        
        Args:
            name: 日志记录器名称
        """
        self.name = name
        self.config = get_config_manager()
        self._logger = self._setup_logger()
    
    def _setup_logger(self) -> logging.Logger:
        """设置日志记录器"""
        logger = logging.getLogger(self.name)
        logger.setLevel(self._get_log_level())
        
        # 清除已有的处理器
        logger.handlers.clear()
        
        # 控制台处理器（过滤掉数据采集等噪声日志，只保留决策/交易核心信息）
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(self._get_log_level())
        console_handler.addFilter(self._build_console_filter())
        console_formatter = logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )
        console_handler.setFormatter(console_formatter)
        logger.addHandler(console_handler)
        
        # 文件处理器（交易日志）
        trading_log_path = self._get_log_path('trading')
        if trading_log_path:
            trading_handler = self._create_file_handler(
                trading_log_path,
                'trading'
            )
            logger.addHandler(trading_handler)
        
        # 文件处理器（系统日志）
        system_log_path = self._get_log_path('system')
        if system_log_path:
            system_handler = self._create_file_handler(
                system_log_path,
                'system'
            )
            logger.addHandler(system_handler)
        
        # 文件处理器（错误日志）
        error_log_path = self._get_log_path('error')
        if error_log_path:
            error_handler = self._create_file_handler(
                error_log_path,
                'error'
            )
            error_handler.setLevel(logging.ERROR)  # 只记录ERROR及以上级别
            logger.addHandler(error_handler)
        
        return logger
    
    def _get_log_level(self) -> int:
        """获取日志级别"""
        try:
            level_str = self.config.get_config('main', 'logging.level')
        except (KeyError, TypeError):
            level_str = 'INFO'
        level_map = {
            'DEBUG': logging.DEBUG,
            'INFO': logging.INFO,
            'WARNING': logging.WARNING,
            'ERROR': logging.ERROR,
            'CRITICAL': logging.CRITICAL,
        }
        return level_map.get(level_str.upper(), logging.INFO)
    
    def _get_log_path(self, log_type: str) -> Optional[Path]:
        """获取日志文件路径"""
        try:
            log_file = self.config.get_config('main', f'logging.file.{log_type}')
            if log_file:
                log_path = Path(log_file)
                # 创建日志目录
                log_path.parent.mkdir(parents=True, exist_ok=True)
                return log_path
        except (KeyError, TypeError):
            pass
        return None
    
    def _create_file_handler(self, log_path: Path, log_type: str) -> RotatingFileHandler:
        """创建文件处理器"""
        try:
            max_bytes = self.config.get_config('main', 'logging.rotation.max_bytes')
        except (KeyError, TypeError):
            max_bytes = 10485760  # 10MB
        
        try:
            backup_count = self.config.get_config('main', 'logging.rotation.backup_count')
        except (KeyError, TypeError):
            backup_count = 5
        
        handler = RotatingFileHandler(
            log_path,
            maxBytes=max_bytes,
            backupCount=backup_count,
            encoding='utf-8'
        )
        
        formatter = logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - %(funcName)s:%(lineno)d - %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )
        handler.setFormatter(formatter)
        return handler

    def _build_console_filter(self) -> logging.Filter:
        """构建控制台输出过滤器，屏蔽数据采集等噪声日志"""
        excluded_keywords = [
            "[行情数据]",
            "[K线数据]",
            "[技术指标]",
            "[指标汇总]",
            "[多周期分析]",
            "[综合前瞻分析]",
            "[情景识别]",
            "采集",
            "数据采集完成",
            "OKX API",
        ]

        class ConsoleFilter(logging.Filter):
            def filter(self, record: logging.LogRecord) -> bool:
                message = record.getMessage()
                return not any(keyword in message for keyword in excluded_keywords)

        return ConsoleFilter()
    
    def debug(self, message: str, *args, **kwargs):
        """记录DEBUG级别日志"""
        self._logger.debug(message, *args, **kwargs)
    
    def info(self, message: str, *args, **kwargs):
        """记录INFO级别日志"""
        self._logger.info(message, *args, **kwargs)
    
    def warning(self, message: str, *args, **kwargs):
        """记录WARNING级别日志"""
        self._logger.warning(message, *args, **kwargs)
    
    def error(self, message: str, *args, **kwargs):
        """记录ERROR级别日志"""
        self._logger.error(message, *args, **kwargs)
    
    def critical(self, message: str, *args, **kwargs):
        """记录CRITICAL级别日志"""
        self._logger.critical(message, *args, **kwargs)
    
    def exception(self, message: str, *args, **kwargs):
        """记录异常日志（包含堆栈跟踪）"""
        self._logger.exception(message, *args, **kwargs)


# 全局日志记录器实例
_logger: Optional[Logger] = None


def get_logger(name: str = "trading_system") -> Logger:
    """获取日志记录器实例"""
    global _logger
    if _logger is None:
        _logger = Logger(name)
    return _logger


if __name__ == "__main__":
    # 测试日志管理器
    logger = get_logger("test")
    
    logger.debug("这是一条DEBUG日志")
    logger.info("这是一条INFO日志")
    logger.warning("这是一条WARNING日志")
    logger.error("这是一条ERROR日志")
    
    try:
        1 / 0
    except Exception:
        logger.exception("捕获到异常")
