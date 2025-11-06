#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
预警系统
风险预警，告警规则引擎，告警聚合和去重
"""

from typing import Dict, List, Optional, Any
from datetime import datetime, timedelta
from enum import Enum
from dataclasses import dataclass
from ..core.config_manager import get_config_manager
from ..core.logger import get_logger


class AlertLevel(Enum):
    """告警级别"""
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


@dataclass
class Alert:
    """告警"""
    alert_id: str
    level: AlertLevel
    type: str
    message: str
    timestamp: datetime
    data: Optional[Dict] = None
    
    def __post_init__(self):
        if self.data is None:
            self.data = {}


class AlertSystem:
    """预警系统"""
    
    def __init__(self):
        """初始化预警系统"""
        self.config_mgr = get_config_manager()
        self.logger = get_logger("alert_system")
        
        # 告警存储
        self.alerts: List[Alert] = []
        self.alert_history: List[Alert] = []
        
        # 告警去重（相同类型的告警在1分钟内不重复发送）
        self.last_alert_time: Dict[str, datetime] = {}
        self.alert_cooldown = timedelta(minutes=1)
    
    def send_alert(self, alert_type: str, message: str, level: AlertLevel = AlertLevel.WARNING,
                  data: Optional[Dict] = None):
        """
        发送告警
        
        Args:
            alert_type: 告警类型
            message: 告警消息
            level: 告警级别
            data: 附加数据
        """
        try:
            # 检查告警去重
            if self._should_suppress_alert(alert_type):
                return
            
            # 创建告警
            alert = Alert(
                alert_id=f"{alert_type}_{int(datetime.now().timestamp() * 1000)}",
                level=level,
                type=alert_type,
                message=message,
                timestamp=datetime.now(),
                data=data
            )
            
            # 记录告警
            self.alerts.append(alert)
            self.alert_history.append(alert)
            
            # 更新最后告警时间
            self.last_alert_time[alert_type] = datetime.now()
            
            # 根据级别记录日志
            if level == AlertLevel.CRITICAL:
                self.logger.critical(f"[{alert_type}] {message}")
            elif level == AlertLevel.ERROR:
                self.logger.error(f"[{alert_type}] {message}")
            elif level == AlertLevel.WARNING:
                self.logger.warning(f"[{alert_type}] {message}")
            else:
                self.logger.info(f"[{alert_type}] {message}")
            
            # 保留最近1000条告警
            if len(self.alert_history) > 1000:
                self.alert_history = self.alert_history[-1000:]
        
        except Exception as e:
            self.logger.error(f"发送告警失败: {e}")
    
    def _should_suppress_alert(self, alert_type: str) -> bool:
        """
        检查是否应该抑制告警（去重）
        
        Args:
            alert_type: 告警类型
            
        Returns:
            是否应该抑制
        """
        if alert_type not in self.last_alert_time:
            return False
        
        last_time = self.last_alert_time[alert_type]
        if datetime.now() - last_time < self.alert_cooldown:
            return True
        
        return False
    
    def get_alerts(self, level: Optional[AlertLevel] = None,
                   alert_type: Optional[str] = None, limit: int = 100) -> List[Alert]:
        """
        获取告警列表
        
        Args:
            level: 告警级别过滤
            alert_type: 告警类型过滤
            limit: 返回数量限制
            
        Returns:
            告警列表
        """
        alerts = self.alert_history
        
        if level:
            alerts = [a for a in alerts if a.level == level]
        
        if alert_type:
            alerts = [a for a in alerts if a.type == alert_type]
        
        return alerts[-limit:]
    
    def get_alert_count(self, level: Optional[AlertLevel] = None,
                       alert_type: Optional[str] = None) -> int:
        """
        获取告警数量
        
        Args:
            level: 告警级别过滤
            alert_type: 告警类型过滤
            
        Returns:
            告警数量
        """
        return len(self.get_alerts(level, alert_type))
    
    def clear_alerts(self):
        """清除告警"""
        self.alerts.clear()
        self.logger.info("告警已清除")


if __name__ == "__main__":
    # 测试预警系统
    system = AlertSystem()
    
    # 发送测试告警
    system.send_alert('test', '这是一条测试告警', AlertLevel.WARNING)
    system.send_alert('risk_limit', '风险超限', AlertLevel.ERROR)
    
    print(f"告警数量: {system.get_alert_count()}")
    alerts = system.get_alerts(limit=10)
    for alert in alerts:
        print(f"{alert.level.value}: {alert.message}")

