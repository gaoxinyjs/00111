#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
时间工具
时间转换、格式化、时区处理等
"""

from datetime import datetime, timezone, timedelta
from typing import Optional
import time


def get_timestamp() -> int:
    """
    获取当前时间戳（秒）
    
    Returns:
        时间戳
    """
    return int(time.time())


def get_timestamp_ms() -> int:
    """
    获取当前时间戳（毫秒）
    
    Returns:
        时间戳（毫秒）
    """
    return int(time.time() * 1000)


def timestamp_to_datetime(timestamp: int, ms: bool = False) -> datetime:
    """
    时间戳转datetime
    
    Args:
        timestamp: 时间戳
        ms: 是否为毫秒时间戳
        
    Returns:
        datetime对象
    """
    if ms:
        return datetime.fromtimestamp(timestamp / 1000, tz=timezone.utc)
    else:
        return datetime.fromtimestamp(timestamp, tz=timezone.utc)


def datetime_to_timestamp(dt: datetime, ms: bool = False) -> int:
    """
    datetime转时间戳
    
    Args:
        dt: datetime对象
        ms: 是否返回毫秒时间戳
        
    Returns:
        时间戳
    """
    timestamp = dt.timestamp()
    return int(timestamp * 1000) if ms else int(timestamp)


def format_datetime(dt: datetime, format_str: str = "%Y-%m-%d %H:%M:%S") -> str:
    """
    格式化datetime
    
    Args:
        dt: datetime对象
        format_str: 格式字符串
        
    Returns:
        格式化后的字符串
    """
    return dt.strftime(format_str)


def parse_datetime(date_string: str, format_str: str = "%Y-%m-%d %H:%M:%S") -> datetime:
    """
    解析日期字符串
    
    Args:
        date_string: 日期字符串
        format_str: 格式字符串
        
    Returns:
        datetime对象
    """
    return datetime.strptime(date_string, format_str)


def get_utc_now() -> datetime:
    """
    获取当前UTC时间
    
    Returns:
        UTC datetime对象
    """
    return datetime.now(timezone.utc)


def get_beijing_time() -> datetime:
    """
    获取当前北京时间（UTC+8）
    
    Returns:
        北京时间datetime对象
    """
    beijing_tz = timezone(timedelta(hours=8))
    return datetime.now(beijing_tz)


def get_today_start() -> datetime:
    """
    获取今天开始时间（00:00:00）
    
    Returns:
        datetime对象
    """
    today = datetime.now().date()
    return datetime.combine(today, datetime.min.time())


def get_today_end() -> datetime:
    """
    获取今天结束时间（23:59:59）
    
    Returns:
        datetime对象
    """
    today = datetime.now().date()
    return datetime.combine(today, datetime.max.time())


def get_week_start(date: Optional[datetime] = None) -> datetime:
    """
    获取周开始时间（周一00:00:00）
    
    Args:
        date: 参考日期，如果为None则使用今天
        
    Returns:
        datetime对象
    """
    if date is None:
        date = datetime.now()
    
    days_since_monday = date.weekday()
    week_start = date - timedelta(days=days_since_monday)
    return datetime.combine(week_start.date(), datetime.min.time())


def get_month_start(date: Optional[datetime] = None) -> datetime:
    """
    获取月开始时间（1号00:00:00）
    
    Args:
        date: 参考日期，如果为None则使用今天
        
    Returns:
        datetime对象
    """
    if date is None:
        date = datetime.now()
    
    month_start = date.replace(day=1)
    return datetime.combine(month_start.date(), datetime.min.time())


def get_month_end(date: Optional[datetime] = None) -> datetime:
    """
    获取月结束时间
    
    Args:
        date: 参考日期，如果为None则使用今天
        
    Returns:
        datetime对象
    """
    if date is None:
        date = datetime.now()
    
    if date.month == 12:
        next_month = date.replace(year=date.year + 1, month=1, day=1)
    else:
        next_month = date.replace(month=date.month + 1, day=1)
    
    month_end = next_month - timedelta(days=1)
    return datetime.combine(month_end.date(), datetime.max.time())


def format_duration(seconds: float) -> str:
    """
    格式化时长
    
    Args:
        seconds: 秒数
        
    Returns:
        格式化后的字符串（如 "1h 30m 45s"）
    """
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    
    parts = []
    if hours > 0:
        parts.append(f"{hours}h")
    if minutes > 0:
        parts.append(f"{minutes}m")
    if secs > 0 or not parts:
        parts.append(f"{secs}s")
    
    return " ".join(parts)


def get_time_ago(dt: datetime) -> str:
    """
    获取相对时间（如 "5分钟前"）
    
    Args:
        dt: datetime对象
        
    Returns:
        相对时间字符串
    """
    now = datetime.now(dt.tzinfo) if dt.tzinfo else datetime.now()
    delta = now - dt
    
    if delta.days > 0:
        return f"{delta.days}天前"
    elif delta.seconds >= 3600:
        hours = delta.seconds // 3600
        return f"{hours}小时前"
    elif delta.seconds >= 60:
        minutes = delta.seconds // 60
        return f"{minutes}分钟前"
    else:
        return "刚刚"


if __name__ == "__main__":
    # 测试时间工具
    print(f"当前时间戳: {get_timestamp()}")
    print(f"当前UTC时间: {get_utc_now()}")
    print(f"当前北京时间: {get_beijing_time()}")
    print(f"今天开始: {get_today_start()}")
    print(f"周开始: {get_week_start()}")
    print(f"月开始: {get_month_start()}")
    print(f"月结束: {get_month_end()}")
    print(f"格式化时长: {format_duration(3665)}")
    print(f"相对时间: {get_time_ago(datetime.now() - timedelta(minutes=30))}")

