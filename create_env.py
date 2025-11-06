#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
创建.env文件
"""

from pathlib import Path

# 获取当前目录
current_dir = Path(__file__).parent
env_file = current_dir / ".env"

# .env文件内容
content = """# OKX API配置
OKX_API_KEY=cdd0aef7-ee09-439e-a106-a1e436374473
OKX_SECRET_KEY=69E4D8BF92E4939572BD77E789D52BE1
OKX_PASSPHRASE=Lishaawbz520.

# DeepSeek API配置（如果需要，请手动填写）
DEEPSEEK_API_KEY=
"""

# 创建文件
try:
    with open(env_file, 'w', encoding='utf-8') as f:
        f.write(content)
    
    print("✓ .env 文件创建成功！")
    print(f"文件路径: {env_file.absolute()}")
    print()
    print("已配置的OKX API密钥：")
    print("  - API Key: cdd0aef7-ee09-439e-a106-a1e436374473")
    print("  - Secret Key: 69E4D8BF92E4939572BD77E789D52BE1")
    print("  - Passphrase: Lishaawbz520.")
    
except Exception as e:
    print(f"✗ 创建失败: {e}")
    import traceback
    traceback.print_exc()

