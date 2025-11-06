#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
检查配置
验证配置文件和环境变量是否正确
"""

import sys
from pathlib import Path

# 添加项目根目录到Python路径
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.core.config_manager import get_config_manager
from src.core.logger import get_logger
from src.core.security import get_security_manager


def check_config():
    """检查配置"""
    logger = get_logger("check_config")
    
    logger.info("=" * 60)
    logger.info("开始检查配置...")
    logger.info("=" * 60)
    
    try:
        config_mgr = get_config_manager()
        security = get_security_manager()
        
        # 检查主配置
        logger.info("\n[主配置]")
        try:
            system_config = config_mgr.get_config('main', 'system')
            logger.info(f"✓ 系统名称: {system_config.get('name')}")
            logger.info(f"✓ 系统版本: {system_config.get('version')}")
            logger.info(f"✓ 运行环境: {system_config.get('environment')}")
        except Exception as e:
            logger.error(f"✗ 主配置检查失败: {e}")
        
        # 检查API配置
        logger.info("\n[API配置]")
        
        # OKX API
        okx_key = security.get_api_key('okx', 'api_key')
        okx_secret = security.get_api_key('okx', 'secret_key')
        okx_passphrase = security.get_api_key('okx', 'passphrase')
        
        if okx_key:
            logger.info(f"✓ OKX API Key: {security.mask_sensitive_info(okx_key)}")
        else:
            logger.warning("✗ OKX API Key 未配置")
        
        if okx_secret:
            logger.info(f"✓ OKX Secret Key: {security.mask_sensitive_info(okx_secret)}")
        else:
            logger.warning("✗ OKX Secret Key 未配置")
        
        if okx_passphrase:
            logger.info(f"✓ OKX Passphrase: {security.mask_sensitive_info(okx_passphrase)}")
        else:
            logger.warning("✗ OKX Passphrase 未配置")
        
        # DeepSeek API
        deepseek_key = security.get_api_key('deepseek', 'api_key')
        if deepseek_key:
            logger.info(f"✓ DeepSeek API Key: {security.mask_sensitive_info(deepseek_key)}")
        else:
            logger.warning("✗ DeepSeek API Key 未配置")
        
        # 检查交易配置
        logger.info("\n[交易配置]")
        try:
            trading_pairs = config_mgr.get_config('trading', 'trading_pairs')
            logger.info(f"✓ 交易对数量: {len(trading_pairs)}")
            for pair in trading_pairs:
                enabled = "启用" if pair.get('enabled') else "禁用"
                logger.info(f"  - {pair.get('symbol')}: {enabled}")
        except Exception as e:
            logger.error(f"✗ 交易配置检查失败: {e}")
        
        # 检查风险配置
        logger.info("\n[风险配置]")
        try:
            risk_limits = config_mgr.get_config('risk', 'risk_limits')
            logger.info(f"✓ 单笔最大亏损: {risk_limits.get('max_loss_per_trade', 0):.2%}")
            logger.info(f"✓ 单日最大亏损: {risk_limits.get('max_loss_per_day', 0):.2%}")
            logger.info(f"✓ 单周最大亏损: {risk_limits.get('max_loss_per_week', 0):.2%}")
        except Exception as e:
            logger.error(f"✗ 风险配置检查失败: {e}")
        
        # 检查数据库配置
        logger.info("\n[数据库配置]")
        try:
            db_config = config_mgr.get_config('database', 'postgresql')
            if db_config.get('password'):
                logger.info(f"✓ PostgreSQL: {db_config.get('host')}:{db_config.get('port')}")
            else:
                logger.warning("✗ PostgreSQL 密码未配置")
        except Exception as e:
            logger.warning(f"✗ 数据库配置检查失败: {e}")
        
        logger.info("\n" + "=" * 60)
        logger.info("配置检查完成！")
        logger.info("=" * 60)
        
    except Exception as e:
        logger.error(f"配置检查失败: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    check_config()

