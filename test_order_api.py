#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
测试OKX API订单提交接口
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from src.data.okx_client import OKXClient
from src.core.logger import get_logger

logger = get_logger("test_order_api")

def test_place_order():
    """测试订单提交"""
    try:
        client = OKXClient()
        
        # 测试参数
        symbol = "BCH-USDT-SWAP"
        side = "sell"  # 做空
        order_type = "market"  # 市价单
        
        # 先查询合约信息，获取正确的lotSz
        print("查询合约信息...")
        instruments = client.get_instruments("SWAP", symbol)
        lot_size = 0.1  # 默认值
        min_size = 0.1  # 默认值
        
        if instruments and isinstance(instruments, list) and len(instruments) > 0:
            instrument_info = instruments[0]
            lot_size = float(instrument_info.get('lotSz', 0.1))  # 最小下单单位
            min_size = float(instrument_info.get('minSz', 0.1))  # 最小订单数量
            print(f"合约信息: lotSize={lot_size}, minSize={min_size}")
        
        size = str(min_size)  # 使用最小订单数量
        
        # OKX合约交易posSide可选值：net（单向持仓模式），long（开多），short（开空）
        # 对于单向持仓模式，不需要posSide，或者使用"net"
        pos_side = None  # 先尝试不使用posSide
        
        print("=" * 60)
        print("测试OKX API订单提交")
        print("=" * 60)
        print(f"交易对: {symbol}")
        print(f"方向: {side}")
        print(f"订单类型: {order_type}")
        print(f"数量: {size}")
        print(f"持仓方向: {pos_side}")
        print(f"交易模式: {client.trade_mode}")
        print(f"测试模式: {client.test_mode}")
        print("-" * 60)
        
        # 准备订单参数
        order_data = {
            'instId': symbol,
            'tdMode': client.trade_mode,
            'side': side,
            'ordType': order_type,
            'sz': size,
            'posSide': pos_side
        }
        
        print("\n订单参数:")
        import json
        print(json.dumps(order_data, indent=2, ensure_ascii=False))
        print("-" * 60)
        
        # 调用API
        print("\n正在提交订单...")
        result = client.place_order(
            symbol=symbol,
            side=side,
            order_type=order_type,
            size=size,
            pos_side=pos_side,
            reduce_only=False
        )
        
        print("\nAPI响应:")
        print(json.dumps(result, indent=2, ensure_ascii=False))
        
        if result and isinstance(result, list) and len(result) > 0:
            first_result = result[0]
            if 'ordId' in first_result:
                print(f"\n✓ 订单提交成功！")
                print(f"订单ID: {first_result['ordId']}")
                print(f"状态: {first_result.get('sCode', 'N/A')}")
                print(f"消息: {first_result.get('sMsg', 'N/A')}")
                return True
            else:
                print(f"\n✗ 订单提交失败")
                print(f"错误代码: {first_result.get('sCode', 'N/A')}")
                print(f"错误消息: {first_result.get('sMsg', 'N/A')}")
                return False
        else:
            print("\n✗ API返回空结果")
            return False
            
    except Exception as e:
        print(f"\n✗ 测试失败: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    print("\n开始测试OKX订单提交API...\n")
    success = test_place_order()
    print("\n" + "=" * 60)
    if success:
        print("测试结果: ✓ 成功")
    else:
        print("测试结果: ✗ 失败")
    print("=" * 60 + "\n")

