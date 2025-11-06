#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
初始化数据库
创建数据库表结构
"""

import sys
from pathlib import Path

# 添加项目根目录到Python路径
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.core.config_manager import get_config_manager
from src.core.logger import get_logger
from src.storage.database import DatabaseManager
from src.storage.models import Base, create_tables


def init_database():
    """初始化数据库"""
    logger = get_logger("init_db")
    
    try:
        config_mgr = get_config_manager()
        db_manager = DatabaseManager()
        
        logger.info("开始初始化数据库...")
        
        # 检查PostgreSQL连接
        if hasattr(db_manager, 'postgres_engine'):
            logger.info("创建PostgreSQL表...")
            create_tables(db_manager.postgres_engine)
            logger.info("✓ PostgreSQL表创建完成")
        else:
            logger.warning("PostgreSQL未连接，跳过表创建")
        
        logger.info("数据库初始化完成！")
        
    except Exception as e:
        logger.error(f"数据库初始化失败: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    init_database()

