#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
创建 .env 文件
"""

import os
from pathlib import Path

def create_env_file():
    """创建.env文件"""
    # 获取脚本所在目录
    script_dir = Path(__file__).parent
    env_file = script_dir / ".env"
    
    # 检查文件是否已存在
    if env_file.exists():
        print(f".env 文件已存在: {env_file}")
        response = input("是否要覆盖现有的.env文件? (y/n): ")
        if response.lower() != 'y':
            print("已取消")
            return False
    
    # .env文件内容
    env_content = """# OKX API配置
OKX_API_KEY=cdd0aef7-ee09-439e-a106-a1e436374473
OKX_SECRET_KEY=69E4D8BF92E4939572BD77E789D52BE1
OKX_PASSPHRASE=Lishaawbz520.

# DeepSeek API配置（如果需要，请手动填写）
DEEPSEEK_API_KEY=
"""
    
    try:
        # 写入文件
        with open(env_file, 'w', encoding='utf-8') as f:
            f.write(env_content)
        
        print("=" * 60)
        print(".env 文件创建成功！")
        print("=" * 60)
        print()
        print(f"文件位置: {env_file}")
        print()
        print("OKX API密钥已配置：")
        print("  - API Key: cdd0aef7-ee09-439e-a106-a1e436374473")
        print("  - Secret Key: 69E4D8BF92E4939572BD77E789D52BE1")
        print("  - Passphrase: Lishaawbz520.")
        print()
        print("现在可以运行 验证配置.bat 或 python 验证配置.py 验证配置")
        
        return True
    
    except Exception as e:
        print(f"✗ .env 文件创建失败: {e}")
        return False

if __name__ == "__main__":
    create_env_file()
    input("\n按Enter键退出...")

