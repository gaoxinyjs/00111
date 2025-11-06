#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
运行脚本 - 简化的启动脚本
用于诊断和运行量化交易系统
"""

import sys
import os
from pathlib import Path

# 添加项目根目录到Python路径
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

def check_dependencies():
    """检查依赖包"""
    required_packages = [
        'yaml',
        'dotenv',
        'cryptography',
        'requests',
        'pandas',
        'numpy',
        'aiohttp'
    ]
    
    missing_packages = []
    for package in required_packages:
        try:
            if package == 'yaml':
                import yaml
            elif package == 'dotenv':
                import dotenv
            else:
                __import__(package)
        except ImportError:
            missing_packages.append(package)
    
    if missing_packages:
        print("❌ 缺少以下依赖包:")
        for pkg in missing_packages:
            print(f"   - {pkg}")
        print("\n请运行以下命令安装依赖:")
        print("   pip install -r requirements.txt")
        return False
    
    print("✓ 所有依赖包已安装")
    return True

def check_config_files():
    """检查配置文件"""
    config_files = [
        'config/config.yaml',
        'config/trading_config.yaml',
        'config/risk_config.yaml',
        'config/api_config.yaml'
    ]
    
    missing_files = []
    for config_file in config_files:
        file_path = project_root / config_file
        if not file_path.exists():
            missing_files.append(config_file)
    
    if missing_files:
        print("❌ 缺少以下配置文件:")
        for file in missing_files:
            print(f"   - {file}")
        return False
    
    print("✓ 所有配置文件存在")
    return True

def check_env_file():
    """检查.env文件"""
    env_file = project_root / '.env'
    if not env_file.exists():
        print("⚠ .env文件不存在（可选，但建议创建）")
        print("  运行 'python create_env.py' 创建.env文件")
        return False
    
    print("✓ .env文件存在")
    return True

def main():
    """主函数"""
    print("=" * 60)
    print("量化交易系统 - 启动诊断")
    print("=" * 60)
    print()
    
    # 检查依赖
    print("[1/4] 检查依赖包...")
    if not check_dependencies():
        sys.exit(1)
    print()
    
    # 检查配置文件
    print("[2/4] 检查配置文件...")
    if not check_config_files():
        sys.exit(1)
    print()
    
    # 检查.env文件
    print("[3/4] 检查.env文件...")
    check_env_file()
    print()
    
    # 尝试启动系统
    print("[4/4] 启动系统...")
    try:
        from src.main import main as start_system
        print("✓ 系统模块加载成功")
        print()
        print("=" * 60)
        print("正在启动交易系统...")
        print("=" * 60)
        print()
        start_system()
    except ImportError as e:
        print(f"❌ 导入模块失败: {e}")
        print("   请检查Python路径和模块结构")
        sys.exit(1)
    except Exception as e:
        print(f"❌ 系统启动失败: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

if __name__ == "__main__":
    main()

