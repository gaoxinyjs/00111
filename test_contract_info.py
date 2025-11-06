#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
查询合约信息，获取正确的数量格式
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from src.data.okx_client import OKXClient
import json

def test_get_contract_info():
    """查询合约信息"""
    try:
        client = OKXClient()
        
        symbol = "BCH-USDT-SWAP"
        
        print("=" * 60)
        print("查询合约信息")
        print("=" * 60)
        print(f"交易对: {symbol}")
        print("-" * 60)
        
        # 查询合约信息（instType是产品类型SWAP，instId是交易对符号）
        print("\n正在查询合约信息...")
        info = client.get_instruments(inst_type="SWAP", symbol=symbol)
        
        print("\n合约信息:")
        if isinstance(info, list) and len(info) > 0:
            contract_info = info[0]
            print(json.dumps(contract_info, indent=2, ensure_ascii=False))
            
            # 提取关键信息
            print("\n" + "-" * 60)
            print("关键参数:")
            print(f"最小订单数量: {contract_info.get('minSz', 'N/A')}")
            print(f"数量精度: {contract_info.get('lotSz', 'N/A')}")
            print(f"价格精度: {contract_info.get('tickSz', 'N/A')}")
            print(f"合约面值: {contract_info.get('ctVal', 'N/A')}")
            print(f"合约面值币种: {contract_info.get('ctValCcy', 'N/A')}")
            print(f"交易模式: {contract_info.get('tdMode', 'N/A')}")
            print("-" * 60)
            
            return contract_info
        else:
            print("未找到合约信息")
            return None
            
    except Exception as e:
        print(f"\n✗ 查询失败: {e}")
        import traceback
        traceback.print_exc()
        return None

if __name__ == "__main__":
    test_get_contract_info()

