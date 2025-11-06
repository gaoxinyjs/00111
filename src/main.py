#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
量化交易系统主程序入口
"""

import sys
import asyncio
from pathlib import Path

# 添加项目根目录到Python路径
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.core.config_manager import get_config_manager
from src.core.logger import get_logger
from src.trading.trading_engine import TradingEngine


def main():
    """主函数"""
    # 初始化配置管理器
    try:
        config_mgr = get_config_manager()
        logger = get_logger("main")
        
        logger.info("=" * 60)
        logger.info("量化交易系统启动中...")
        logger.info("=" * 60)
        
        # 显示系统信息
        system_config = config_mgr.get_config('main', 'system')
        logger.info(f"系统名称: {system_config.get('name', 'Unknown')}")
        logger.info(f"系统版本: {system_config.get('version', 'Unknown')}")
        logger.info(f"运行环境: {system_config.get('environment', 'Unknown')}")
        
        # 检查关键配置
        logger.info("\n检查配置...")
        
        # 检查API配置
        try:
            okx_config = config_mgr.get_config('api', 'okx')
            logger.info(f"✓ OKX API配置已加载")
        except Exception as e:
            logger.warning(f"⚠ OKX API配置检查失败: {e}")
        
        try:
            deepseek_config = config_mgr.get_config('api', 'deepseek')
            logger.info(f"✓ DeepSeek API配置已加载")
        except Exception as e:
            logger.warning(f"⚠ DeepSeek API配置检查失败: {e}")
        
        # 检查交易配置
        try:
            trading_pairs = config_mgr.get_config('trading', 'trading_pairs')
            logger.info(f"✓ 交易对配置已加载，共{len(trading_pairs)}个交易对")
        except Exception as e:
            logger.warning(f"⚠ 交易配置检查失败: {e}")
        
        # 检查风险配置
        try:
            risk_config = config_mgr.get_config('risk', 'risk_limits')
            logger.info(f"✓ 风险配置已加载")
        except Exception as e:
            logger.warning(f"⚠ 风险配置检查失败: {e}")
        
        logger.info("\n" + "=" * 60)
        logger.info("系统初始化完成！")
        logger.info("=" * 60)
        
        # 启动交易引擎
        logger.info("\n启动交易引擎...")
        trading_engine = TradingEngine()
        
        # 运行交易引擎（异步）
        async def run_trading_engine():
            try:
                await trading_engine.start()
            except KeyboardInterrupt:
                logger.info("\n收到停止信号，正在停止交易引擎...")
                await trading_engine.stop()
            except Exception as e:
                logger.error(f"交易引擎运行出错: {e}")
                await trading_engine.stop()
        
        # 运行异步主循环
        try:
            asyncio.run(run_trading_engine())
        except KeyboardInterrupt:
            logger.info("\n程序已停止")
        
        logger.info("=" * 60)
        logger.info("系统已关闭")
        logger.info("=" * 60)
        
    except Exception as e:
        print(f"系统启动失败: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
