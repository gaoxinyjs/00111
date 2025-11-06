#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
确保.env文件存在
如果不存在则自动创建
"""

from pathlib import Path
import os

def ensure_env_file():
    """确保.env文件存在"""
    script_dir = Path(__file__).parent
    env_file = script_dir / ".env"
    
    if env_file.exists():
        print(f"✓ .env 文件已存在: {env_file}")
        return True
    
    print(f"✗ .env 文件不存在，正在创建...")
    
    # .env文件内容
    env_content = """# OKX API配置
OKX_API_KEY=cdd0aef7-ee09-439e-a106-a1e436374473
OKX_SECRET_KEY=69E4D8BF92E4939572BD77E789D52BE1
OKX_PASSPHRASE=Lishaawbz520.

# DeepSeek API配置（如果需要，请手动填写）
DEEPSEEK_API_KEY=
"""
    
    try:
        with open(env_file, 'w', encoding='utf-8') as f:
            f.write(env_content)
        
        print(f"✓ .env 文件创建成功: {env_file}")
        print()
        print("OKX API密钥已配置：")
        print("  - API Key: cdd0aef7-ee09-439e-a106-a1e436374473")
        print("  - Secret Key: 69E4D8BF92E4939572BD77E789D52BE1")
        print("  - Passphrase: Lishaawbz520.")
        
        return True
    
    except Exception as e:
        print(f"✗ 创建失败: {e}")
        print()
        print("请手动创建 .env 文件：")
        print("1. 在 crypto-trading-system 目录下创建名为 .env 的文件")
        print("2. 复制以下内容到文件中：")
        print()
        print(env_content)
        return False

if __name__ == "__main__":
    ensure_env_file()
    input("\n按Enter键退出...")

