#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
测试异步OKXClient
验证异步请求、单例模式、连接池复用等功能
"""

import asyncio
import sys
import os
from datetime import datetime

# 添加项目路径
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

from src.data.okx_client import get_okx_client, OKXClient
from src.core.logger import get_logger

logger = get_logger("test_async_okx")


async def test_singleton():
    """测试单例模式"""
    print("\n" + "="*60)
    print("测试1: 单例模式")
    print("="*60)
    
    client1 = await get_okx_client()
    client2 = await get_okx_client()
    
    assert client1 is client2, "单例模式失败：两个实例不相同"
    print("✅ 单例模式测试通过：两个实例是同一个对象")
    print(f"   实例ID: {id(client1)}")


async def test_async_get_ticker():
    """测试异步获取行情"""
    print("\n" + "="*60)
    print("测试2: 异步获取行情")
    print("="*60)
    
    client = await get_okx_client()
    
    try:
        ticker_data = await client.async_get_ticker("BTC-USDT")
        print(f"✅ 异步获取行情成功")
        if ticker_data and isinstance(ticker_data, list) and len(ticker_data) > 0:
            ticker = ticker_data[0]
            print(f"   交易对: {ticker.get('instId', 'N/A')}")
            print(f"   最新价: {ticker.get('last', 'N/A')}")
            print(f"   买一价: {ticker.get('bidPx', 'N/A')}")
            print(f"   卖一价: {ticker.get('askPx', 'N/A')}")
        else:
            print(f"   数据格式: {type(ticker_data)}")
    except Exception as e:
        print(f"❌ 异步获取行情失败: {e}")
        raise


async def test_async_get_orderbook():
    """测试异步获取订单簿"""
    print("\n" + "="*60)
    print("测试3: 异步获取订单簿")
    print("="*60)
    
    client = await get_okx_client()
    
    try:
        orderbook_data = await client.async_get_orderbook("BTC-USDT", depth=10)
        print(f"✅ 异步获取订单簿成功")
        if orderbook_data and isinstance(orderbook_data, list) and len(orderbook_data) > 0:
            orderbook = orderbook_data[0]
            bids = orderbook.get('bids', [])
            asks = orderbook.get('asks', [])
            print(f"   买盘档数: {len(bids)}")
            print(f"   卖盘档数: {len(asks)}")
            if bids and asks:
                print(f"   买一价: {bids[0][0]}, 买一量: {bids[0][1]}")
                print(f"   卖一价: {asks[0][0]}, 卖一量: {asks[0][1]}")
        else:
            print(f"   数据格式: {type(orderbook_data)}")
    except Exception as e:
        print(f"❌ 异步获取订单簿失败: {e}")
        raise


async def test_async_get_kline():
    """测试异步获取K线"""
    print("\n" + "="*60)
    print("测试4: 异步获取K线")
    print("="*60)
    
    client = await get_okx_client()
    
    try:
        kline_data = await client.async_get_kline("BTC-USDT", interval="1H", limit=5)
        print(f"✅ 异步获取K线成功")
        if kline_data and isinstance(kline_data, list):
            print(f"   K线数量: {len(kline_data)}")
            if kline_data:
                latest = kline_data[0]
                print(f"   最新K线: 开={latest[1]}, 高={latest[2]}, 低={latest[3]}, 收={latest[4]}, 量={latest[5]}")
        else:
            print(f"   数据格式: {type(kline_data)}")
    except Exception as e:
        print(f"❌ 异步获取K线失败: {e}")
        raise


async def test_async_get_balance():
    """测试异步获取余额"""
    print("\n" + "="*60)
    print("测试5: 异步获取余额")
    print("="*60)
    
    client = await get_okx_client()
    
    try:
        balance_data = await client.async_get_balance()
        print(f"✅ 异步获取余额成功")
        if balance_data and isinstance(balance_data, list):
            print(f"   币种数量: {len(balance_data)}")
            if balance_data:
                # 显示前几个币种
                for i, bal in enumerate(balance_data[:3]):
                    details = bal.get('details', [])
                    if details:
                        for detail in details[:1]:
                            ccy = detail.get('ccy', 'N/A')
                            avail = detail.get('availBal', '0')
                            print(f"   {ccy}: 可用余额 = {avail}")
        else:
            print(f"   数据格式: {type(balance_data)}")
    except Exception as e:
        print(f"❌ 异步获取余额失败: {e}")
        raise


async def test_async_get_positions():
    """测试异步获取持仓"""
    print("\n" + "="*60)
    print("测试6: 异步获取持仓")
    print("="*60)
    
    client = await get_okx_client()
    
    try:
        positions_data = await client.async_get_positions()
        print(f"✅ 异步获取持仓成功")
        if positions_data and isinstance(positions_data, list):
            print(f"   持仓数量: {len(positions_data)}")
            if positions_data:
                for pos in positions_data[:3]:
                    inst_id = pos.get('instId', 'N/A')
                    pos_side = pos.get('posSide', 'N/A')
                    pos_size = pos.get('pos', '0')
                    print(f"   {inst_id} ({pos_side}): {pos_size}")
        else:
            print(f"   数据格式: {type(positions_data)}")
    except Exception as e:
        print(f"❌ 异步获取持仓失败: {e}")
        raise


async def test_concurrent_requests():
    """测试并发请求（连接池复用）"""
    print("\n" + "="*60)
    print("测试7: 并发请求（连接池复用）")
    print("="*60)
    
    client = await get_okx_client()
    
    try:
        start_time = datetime.now()
        
        # 并发发送多个请求
        tasks = [
            client.async_get_ticker("BTC-USDT"),
            client.async_get_ticker("ETH-USDT"),
            client.async_get_orderbook("BTC-USDT", depth=5),
            client.async_get_kline("BTC-USDT", interval="1H", limit=3),
        ]
        
        results = await asyncio.gather(*tasks)
        
        elapsed = (datetime.now() - start_time).total_seconds()
        
        print(f"✅ 并发请求成功")
        print(f"   并发请求数: {len(tasks)}")
        print(f"   总耗时: {elapsed:.2f}秒")
        print(f"   平均每个请求: {elapsed/len(tasks):.2f}秒")
        print(f"   连接池复用: 所有请求共享同一个连接池")
        
        # 验证结果
        assert len(results) == len(tasks), "结果数量不匹配"
        print(f"   所有请求都成功返回结果")
        
    except Exception as e:
        print(f"❌ 并发请求失败: {e}")
        raise


async def test_sync_methods():
    """测试同步方法（过渡用）"""
    print("\n" + "="*60)
    print("测试8: 同步方法（过渡用）")
    print("="*60)
    
    client = await get_okx_client()
    
    try:
        # 测试同步方法（在异步环境中应该抛出异常）
        ticker_data = client.get_ticker("BTC-USDT")
        print(f"❌ 同步方法测试失败：应该抛出异常")
        raise AssertionError("在异步环境中调用同步方法应该抛出异常")
    except RuntimeError as e:
        if "不能使用同步方法" in str(e):
            print(f"✅ 同步方法测试成功：正确抛出异常")
            print(f"   异常信息: {str(e)}")
            print(f"   提示：在异步环境中应使用 async_get_ticker() 方法")
        else:
            raise


async def test_connection_pool():
    """测试连接池复用"""
    print("\n" + "="*60)
    print("测试9: 连接池复用")
    print("="*60)
    
    client = await get_okx_client()
    
    try:
        # 检查连接池是否存在
        assert client._connector is not None, "连接池未初始化"
        assert client._session is not None, "会话未初始化"
        
        print(f"✅ 连接池已初始化")
        print(f"   连接池类型: {type(client._connector).__name__}")
        print(f"   会话类型: {type(client._session).__name__}")
        
        # 多次请求，验证连接复用
        start_time = datetime.now()
        for i in range(5):
            await client.async_get_ticker("BTC-USDT")
        elapsed = (datetime.now() - start_time).total_seconds()
        
        print(f"   连续5次请求耗时: {elapsed:.2f}秒")
        print(f"   平均每次请求: {elapsed/5:.2f}秒")
        print(f"   连接池复用: 所有请求共享连接，无需重新建立连接")
        
    except Exception as e:
        print(f"❌ 连接池测试失败: {e}")
        raise


async def main():
    """主测试函数"""
    print("\n" + "="*60)
    print("开始测试异步OKXClient")
    print("="*60)
    print(f"测试时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    
    try:
        # 运行所有测试
        await test_singleton()
        await test_async_get_ticker()
        await test_async_get_orderbook()
        await test_async_get_kline()
        await test_async_get_balance()
        await test_async_get_positions()
        await test_concurrent_requests()
        await test_sync_methods()
        await test_connection_pool()
        
        print("\n" + "="*60)
        print("✅ 所有测试通过！")
        print("="*60)
        
    except Exception as e:
        print("\n" + "="*60)
        print(f"❌ 测试失败: {e}")
        print("="*60)
        import traceback
        traceback.print_exc()
        raise
    finally:
        # 清理资源
        try:
            client = await get_okx_client()
            await client.close()
            print("\n连接池已关闭")
        except Exception as e:
            print(f"\n关闭连接池时出错: {e}")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n测试被用户中断")
    except Exception as e:
        print(f"\n测试异常: {e}")
        sys.exit(1)

