#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
验证配置脚本
快速验证配置是否正确
"""

import sys
import os
from pathlib import Path

# 添加项目根目录到Python路径
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

def main():
    """主函数"""
    print("=" * 60)
    print("开始验证配置...")
    print("=" * 60)
    print()
    
    # 1. 检查.env文件
    env_file = project_root / ".env"
    if env_file.exists():
        print("✓ .env 文件存在")
        
        # 读取.env文件内容（不显示完整密钥）
        with open(env_file, 'r', encoding='utf-8') as f:
            lines = f.readlines()
            for line in lines:
                if line.strip() and not line.startswith('#'):
                    key = line.split('=')[0].strip()
                    value = line.split('=', 1)[1].strip() if '=' in line else ''
                    if value:
                        # 只显示前4个字符
                        masked = value[:4] + '*' * (len(value) - 4) if len(value) > 4 else '*' * len(value)
                        print(f"  - {key}: {masked}")
    else:
        print("✗ .env 文件不存在")
        print("  请运行 快速配置.bat 或手动创建 .env 文件")
        return False
    
    print()
    
    # 2. 检查配置文件
    config_files = [
        "config/config.yaml",
        "config/api_config.yaml",
        "config/trading_config.yaml",
        "config/risk_config.yaml"
    ]
    
    all_config_exists = True
    for config_file in config_files:
        file_path = project_root / config_file
        if file_path.exists():
            print(f"✓ {config_file} 存在")
        else:
            print(f"✗ {config_file} 不存在")
            all_config_exists = False
    
    print()
    
    # 3. 尝试导入模块
    try:
        print("正在检查Python模块...")
        import yaml
        print("✓ PyYAML 已安装")
    except ImportError:
        print("✗ PyYAML 未安装")
        print("  请运行: pip install PyYAML")
        return False
    
    try:
        from dotenv import load_dotenv
        print("✓ python-dotenv 已安装")
    except ImportError:
        print("✗ python-dotenv 未安装")
        print("  请运行: pip install python-dotenv")
        return False
    
    try:
        from cryptography.fernet import Fernet
        print("✓ cryptography 已安装")
    except ImportError:
        print("✗ cryptography 未安装")
        print("  请运行: pip install cryptography")
        return False
    
    print()
    
    # 4. 尝试加载配置
    try:
        print("正在加载配置管理器...")
        from src.core.config_manager import get_config_manager
        
        config_mgr = get_config_manager()
        print("✓ 配置管理器加载成功")
        
        # 检查主配置
        try:
            system_config = config_mgr.get_config('main', 'system')
            print(f"  - 系统名称: {system_config.get('name', 'Unknown')}")
            print(f"  - 系统版本: {system_config.get('version', 'Unknown')}")
        except Exception as e:
            print(f"  ✗ 主配置加载失败: {e}")
        
        # 检查API配置
        try:
            okx_config = config_mgr.get_config('api', 'okx')
            api_key = okx_config.get('api_key', '')
            
            if api_key and not api_key.startswith('${'):
                print(f"✓ OKX API Key 已配置: {api_key[:4]}****")
            else:
                print("✗ OKX API Key 未配置（从环境变量读取）")
                # 检查环境变量
                okx_key = os.getenv('OKX_API_KEY')
                if okx_key:
                    print(f"  ✓ 环境变量 OKX_API_KEY 已设置: {okx_key[:4]}****")
                else:
                    print("  ✗ 环境变量 OKX_API_KEY 未设置")
        except Exception as e:
            print(f"  ✗ API配置加载失败: {e}")
        
    except Exception as e:
        print(f"✗ 配置管理器加载失败: {e}")
        import traceback
        traceback.print_exc()
        return False
    
    print()
    print("=" * 60)
    print("配置验证完成！")
    print("=" * 60)
    
    return True

if __name__ == "__main__":
    try:
        success = main()
        if not success:
            print("\n⚠ 配置验证未完全通过，请检查上述问题")
            sys.exit(1)
    except KeyboardInterrupt:
        print("\n\n验证已取消")
        sys.exit(0)
    except Exception as e:
        print(f"\n✗ 验证过程出错: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

