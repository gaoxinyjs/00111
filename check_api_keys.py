#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
检查API密钥配置
诊断OKX API密钥配置问题
"""

import sys
from pathlib import Path

# 添加项目根目录到Python路径
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

from src.core.config_manager import get_config_manager
from src.core.security import get_security_manager

def check_api_keys():
    """检查API密钥配置"""
    print("=" * 60)
    print("检查OKX API密钥配置")
    print("=" * 60)
    print()
    
    # 检查.env文件
    env_file = project_root / '.env'
    if env_file.exists():
        print("✓ .env文件存在")
    else:
        print("✗ .env文件不存在")
        print("  请运行 'python create_env.py' 创建.env文件")
        print()
    
    # 检查配置管理器
    try:
        config_mgr = get_config_manager()
        security = get_security_manager()
        
        # 检查OKX API密钥
        print("\n[OKX API密钥检查]")
        api_key = security.get_api_key('okx', 'api_key')
        secret_key = security.get_api_key('okx', 'secret_key')
        passphrase = security.get_api_key('okx', 'passphrase')
        
        if api_key:
            print(f"✓ API Key: {api_key[:8]}...{api_key[-4:] if len(api_key) > 12 else ''}")
        else:
            print("✗ API Key: 未配置")
        
        if secret_key:
            print(f"✓ Secret Key: {secret_key[:8]}...{secret_key[-4:] if len(secret_key) > 12 else ''}")
        else:
            print("✗ Secret Key: 未配置")
        
        if passphrase:
            print(f"✓ Passphrase: {passphrase[:4]}...")
        else:
            print("✗ Passphrase: 未配置")
        
        if all([api_key, secret_key, passphrase]):
            print("\n✓ 所有OKX API密钥已配置")
            print("\n如果仍然遇到401错误，请检查：")
            print("  1. API密钥是否正确")
            print("  2. API密钥是否有查询账户余额的权限")
            print("  3. 是否设置了IP白名单（如果有，请确保当前IP在列表中）")
            print("  4. 账户是否需要使用特定的域名（如 eea.okx.com 或 us.okx.com）")
            
            # 尝试测试API调用
            print("\n正在测试API连接...")
            try:
                from src.data.okx_client import OKXClient
                client = OKXClient()
                balance = client.get_balance()
                print("✓ API连接成功！")
                if balance:
                    print(f"  账户余额数据: {len(balance)} 条记录")
            except Exception as e:
                print(f"✗ API连接失败: {e}")
                print("\n可能的原因：")
                print("  - API密钥错误")
                print("  - API密钥权限不足")
                print("  - IP地址未在白名单中")
                print("  - 需要使用不同的域名（如 eea.okx.com）")
        else:
            print("\n✗ OKX API密钥未完整配置")
            print("\n配置步骤：")
            print("  1. 在项目根目录创建 .env 文件")
            print("  2. 添加以下内容：")
            print("     OKX_API_KEY=your_api_key")
            print("     OKX_SECRET_KEY=your_secret_key")
            print("     OKX_PASSPHRASE=your_passphrase")
            print("  3. 或运行: python create_env.py")
        
    except Exception as e:
        print(f"\n✗ 检查配置时出错: {e}")
        import traceback
        traceback.print_exc()
        return False
    
    print("\n" + "=" * 60)
    return True

if __name__ == "__main__":
    success = check_api_keys()
    sys.exit(0 if success else 1)

