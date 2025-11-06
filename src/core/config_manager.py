#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
配置管理器
统一管理所有配置文件，支持环境变量覆盖，配置热更新
"""

import os
import yaml
from pathlib import Path
from typing import Dict, Any, Optional
from dotenv import load_dotenv


class ConfigManager:
    """配置管理器"""
    
    def __init__(self, config_dir: Optional[str] = None):
        """
        初始化配置管理器
        
        Args:
            config_dir: 配置文件目录，默认为项目根目录下的config目录
        """
        if config_dir is None:
            # 获取项目根目录
            current_dir = Path(__file__).parent.parent.parent
            config_dir = current_dir / "config"
        
        self.config_dir = Path(config_dir)
        self._configs: Dict[str, Any] = {}
        self._load_env()
        self._load_all_configs()
    
    def _load_env(self):
        """加载环境变量"""
        # 从项目根目录加载.env文件
        env_file = self.config_dir.parent / ".env"
        if env_file.exists():
            load_dotenv(env_file)
    
    def _substitute_env_vars(self, value: Any) -> Any:
        """递归替换环境变量"""
        if isinstance(value, dict):
            return {k: self._substitute_env_vars(v) for k, v in value.items()}
        elif isinstance(value, list):
            return [self._substitute_env_vars(item) for item in value]
        elif isinstance(value, str) and value.startswith("${") and value.endswith("}"):
            # 提取环境变量名
            env_var = value[2:-1]
            return os.getenv(env_var, value)
        else:
            return value
    
    def _load_config_file(self, filename: str) -> Dict[str, Any]:
        """
        加载单个配置文件
        
        Args:
            filename: 配置文件名
            
        Returns:
            配置字典
        """
        config_path = self.config_dir / filename
        if not config_path.exists():
            raise FileNotFoundError(f"配置文件不存在: {config_path}")
        
        with open(config_path, 'r', encoding='utf-8') as f:
            config = yaml.safe_load(f)
        
        # 替换环境变量
        config = self._substitute_env_vars(config)
        return config
    
    def _load_all_configs(self):
        """加载所有配置文件"""
        config_files = {
            'main': 'config.yaml',
            'trading': 'trading_config.yaml',
            'risk': 'risk_config.yaml',
            'api': 'api_config.yaml',
        }
        
        for key, filename in config_files.items():
            try:
                self._configs[key] = self._load_config_file(filename)
            except FileNotFoundError:
                print(f"警告: 配置文件 {filename} 不存在，跳过加载")
                self._configs[key] = {}
    
    def get_config(self, section: Optional[str] = None, key: Optional[str] = None, default: Any = None) -> Any:
        """
        获取配置
        
        Args:
            section: 配置节名称（main, trading, risk, api）
            key: 配置键，支持点号分隔的嵌套键（如 'system.name'）
            default: 默认值，如果配置不存在则返回此值
            
        Returns:
            配置值，如果不存在则返回默认值
        """
        if section is None:
            # 返回所有配置
            return self._configs
        
        if section not in self._configs:
            if default is not None:
                return default
            raise KeyError(f"配置节不存在: {section}")
        
        config = self._configs[section]
        
        if key is None:
            # 返回整个配置节
            return config
        
        # 支持点号分隔的嵌套键
        keys = key.split('.')
        value = config
        for k in keys:
            if isinstance(value, dict):
                value = value.get(k)
                if value is None:
                    if default is not None:
                        return default
                    raise KeyError(f"配置键不存在: {section}.{key}")
            else:
                if default is not None:
                    return default
                raise KeyError(f"配置键不存在: {section}.{key}")
        
        return value
    
    def update_config(self, section: str, key: str, value: Any):
        """
        更新配置（仅在内存中，不保存到文件）
        
        Args:
            section: 配置节名称
            key: 配置键，支持点号分隔的嵌套键
            value: 新值
        """
        if section not in self._configs:
            self._configs[section] = {}
        
        config = self._configs[section]
        keys = key.split('.')
        
        # 导航到目标字典
        for k in keys[:-1]:
            if k not in config:
                config[k] = {}
            config = config[k]
        
        # 设置值
        config[keys[-1]] = value
    
    def reload_config(self, section: Optional[str] = None):
        """
        重新加载配置
        
        Args:
            section: 配置节名称，如果为None则重新加载所有配置
        """
        if section is None:
            self._load_all_configs()
        else:
            config_files = {
                'main': 'config.yaml',
                'trading': 'trading_config.yaml',
                'risk': 'risk_config.yaml',
                'api': 'api_config.yaml',
            }
            
            if section in config_files:
                self._configs[section] = self._load_config_file(config_files[section])


# 全局配置管理器实例
_config_manager: Optional[ConfigManager] = None


def get_config_manager() -> ConfigManager:
    """获取全局配置管理器实例"""
    global _config_manager
    if _config_manager is None:
        _config_manager = ConfigManager()
    return _config_manager


if __name__ == "__main__":
    # 测试配置管理器
    config_mgr = ConfigManager()
    
    # 测试获取配置
    print("系统名称:", config_mgr.get_config('main', 'system.name'))
    print("日志级别:", config_mgr.get_config('main', 'logging.level'))
    print("交易对:", config_mgr.get_config('trading', 'trading_pairs'))
    print("基础仓位:", config_mgr.get_config('risk', 'position_management.base_position_size'))
