#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
安全模块
API密钥管理、敏感信息保护、权限控制
"""

import os
from typing import Optional
from cryptography.fernet import Fernet
from pathlib import Path
from .config_manager import get_config_manager
from .logger import get_logger


class SecurityManager:
    """安全管理器"""
    
    def __init__(self):
        """初始化安全管理器"""
        self.config = get_config_manager()
        self.logger = get_logger("security")
        self._encryption_key: Optional[bytes] = None
        self._cipher: Optional[Fernet] = None
        self._init_encryption()
    
    def _init_encryption(self):
        """初始化加密"""
        try:
            # 尝试从环境变量获取加密密钥
            key_file = Path.home() / ".trading_system_key"
            
            if key_file.exists():
                # 从文件读取密钥
                try:
                    with open(key_file, 'rb') as f:
                        self._encryption_key = f.read()
                    if not self._encryption_key:
                        # 文件为空，重新生成
                        raise ValueError("密钥文件为空")
                except (IOError, OSError, ValueError) as e:
                    self.logger.warning(f"读取密钥文件失败，将重新生成: {e}")
                    # 删除损坏的文件
                    try:
                        key_file.unlink()
                    except:
                        pass
                    # 继续创建新密钥
                    self._encryption_key = None
            else:
                self._encryption_key = None
            
            if self._encryption_key is None:
                # 生成新密钥并保存
                self._encryption_key = Fernet.generate_key()
                
                # 确保父目录存在
                try:
                    key_file.parent.mkdir(parents=True, exist_ok=True)
                except (OSError, PermissionError) as e:
                    self.logger.error(f"无法创建密钥文件目录: {e}")
                    raise RuntimeError(f"无法创建密钥文件目录: {e}")
                
                # 创建文件并写入密钥
                try:
                    with open(key_file, 'wb') as f:
                        f.write(self._encryption_key)
                    self.logger.debug(f"密钥文件已创建: {key_file}")
                except (IOError, OSError, PermissionError) as e:
                    self.logger.error(f"无法写入密钥文件: {e}")
                    raise RuntimeError(f"无法写入密钥文件: {e}")
                
                # Windows上chmod可能不可用，使用try-except处理
                try:
                    if hasattr(key_file, 'chmod'):
                        key_file.chmod(0o600)  # 仅所有者可读写
                except (AttributeError, OSError, FileNotFoundError):
                    # Windows上chmod可能失败，忽略错误
                    pass
            
            self._cipher = Fernet(self._encryption_key)
        except Exception as e:
            self.logger.error(f"初始化加密模块失败: {e}")
            # 如果加密初始化失败，仍然允许系统运行（但某些加密功能可能不可用）
            self._encryption_key = None
            self._cipher = None
            self.logger.warning("加密模块初始化失败，系统将以非加密模式运行")
    
    def encrypt(self, data: str) -> str:
        """
        加密数据
        
        Args:
            data: 要加密的字符串
            
        Returns:
            加密后的字符串（base64编码）
        """
        if not self._cipher:
            raise RuntimeError("加密器未初始化")
        
        encrypted = self._cipher.encrypt(data.encode())
        return encrypted.decode()
    
    def decrypt(self, encrypted_data: str) -> str:
        """
        解密数据
        
        Args:
            encrypted_data: 加密的字符串（base64编码）
            
        Returns:
            解密后的字符串
        """
        if not self._cipher:
            raise RuntimeError("加密器未初始化")
        
        decrypted = self._cipher.decrypt(encrypted_data.encode())
        return decrypted.decode()
    
    def get_api_key(self, api_name: str, key_name: str = "api_key") -> Optional[str]:
        """
        获取API密钥
        
        Args:
            api_name: API名称（如 'okx', 'deepseek'）
            key_name: 密钥名称（如 'api_key', 'secret_key'）
            
        Returns:
            API密钥值，如果不存在则返回None
        """
        try:
            # 先从环境变量获取
            env_key = f"{api_name.upper()}_{key_name.upper()}"
            value = os.getenv(env_key)
            if value:
                return value
            
            # 从配置文件获取
            config_key = f"api.{api_name}.{key_name}"
            value = self.config.get_config('api', config_key)
            if value and not value.startswith("${"):
                return value
        except (KeyError, TypeError):
            pass
        
        return None
    
    def mask_sensitive_info(self, data: str, mask_char: str = "*", visible_chars: int = 4) -> str:
        """
        遮挡敏感信息
        
        Args:
            data: 原始数据
            mask_char: 遮挡字符
            visible_chars: 保留可见字符数
            
        Returns:
            遮挡后的字符串
        """
        if not data or len(data) <= visible_chars:
            return mask_char * len(data) if data else ""
        
        visible = data[:visible_chars]
        masked = mask_char * (len(data) - visible_chars)
        return visible + masked


# 全局安全管理器实例
_security_manager: Optional[SecurityManager] = None


def get_security_manager() -> SecurityManager:
    """获取全局安全管理器实例"""
    global _security_manager
    if _security_manager is None:
        _security_manager = SecurityManager()
    return _security_manager


if __name__ == "__main__":
    # 测试安全管理器
    security = get_security_manager()
    
    # 测试加密解密
    original = "test_secret_key_12345"
    encrypted = security.encrypt(original)
    decrypted = security.decrypt(encrypted)
    
    print(f"原始: {original}")
    print(f"加密: {encrypted}")
    print(f"解密: {decrypted}")
    print(f"匹配: {original == decrypted}")
    
    # 测试遮挡
    masked = security.mask_sensitive_info(original)
    print(f"遮挡: {masked}")
    
    # 测试获取API密钥
    okx_key = security.get_api_key("okx", "api_key")
    print(f"OKX API Key: {security.mask_sensitive_info(okx_key or 'NOT_SET')}")
