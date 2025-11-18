#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
OKX API客户端（异步版本）
封装OKX API调用，处理API限流，错误重试机制
使用aiohttp实现异步HTTP请求，支持连接池复用和单例模式
"""

import time
import hmac
import base64
import hashlib
import asyncio
import json
import threading
from typing import Dict, List, Optional, Any
from datetime import datetime
from urllib.parse import urlencode
import aiohttp
import requests
from ..core.config_manager import get_config_manager
from ..core.logger import get_logger
from ..core.security import get_security_manager
from ..core.exception import APIException


# 模块级单例实例
_instance: Optional['OKXClient'] = None
_init_lock = asyncio.Lock()


async def get_okx_client() -> 'OKXClient':
    """
    获取OKX客户端单例（异步工厂函数）
    
    Returns:
        OKXClient实例
    """
    global _instance
    if _instance is None:
        async with _init_lock:
            if _instance is None:
                _instance = OKXClient()
                await _instance._async_init()
    return _instance


class OKXClient:
    """OKX API客户端（异步版本，支持连接池复用）"""
    
    def __init__(self):
        """初始化OKX客户端（同步部分）"""
        self.config_mgr = get_config_manager()
        self.logger = get_logger("okx_client")
        self.security = get_security_manager()
        
        # 获取配置
        okx_config = self.config_mgr.get_config('api', 'okx')
        self.api_key = self.security.get_api_key('okx', 'api_key')
        self.secret_key = self.security.get_api_key('okx', 'secret_key')
        self.passphrase = self.security.get_api_key('okx', 'passphrase')
        self.base_url = okx_config.get('base_url', 'https://www.okx.com')
        self.test_mode = okx_config.get('test_mode', False)
        self.trade_mode = okx_config.get('trade_mode', 'cross')  # 交易模式：cross全仓（合约）, isolated逐仓（合约）, cash现货
        
        # 限流配置
        rate_limit = okx_config.get('rate_limit', {})
        self.rest_requests_per_second = rate_limit.get('rest_requests_per_second', 10)
        self.last_request_time = 0
        self._rate_limit_lock = asyncio.Lock()
        self._rate_limit_sync_lock = threading.Lock()
        
        # 重试配置
        retry_config = okx_config.get('retry', {})
        self.max_retries = retry_config.get('max_retries', 3)
        self.retry_delay = retry_config.get('retry_delay', 1)
        self.backoff_factor = retry_config.get('backoff_factor', 2)
        
        # aiohttp会话和连接池（异步初始化）
        self._session: Optional[aiohttp.ClientSession] = None
        self._connector: Optional[aiohttp.TCPConnector] = None
        
        if not all([self.api_key, self.secret_key, self.passphrase]):
            self.logger.warning("OKX API密钥未配置，请检查配置")

    def _infer_inst_type(self, symbol: Optional[str]) -> str:
        """根据交易对推断产品类型"""
        if not symbol:
            return "SWAP"
        upper_symbol = symbol.upper()
        if upper_symbol.endswith("-SWAP"):
            return "SWAP"
        if upper_symbol.endswith("-FUTURES") or upper_symbol.endswith("-FUT"):
            return "FUTURES"
        if upper_symbol.endswith("-SPOT"):
            return "SPOT"
        if upper_symbol.endswith("-MARGIN"):
            return "MARGIN"
        if upper_symbol.endswith("-OPTION") or upper_symbol.endswith("-OPT"):
            return "OPTION"
        # 根据常见后缀推断失败时，默认使用SWAP（合约交易最常见）
        return "SWAP"
    
    def _extract_underlying(self, symbol: Optional[str]) -> Optional[str]:
        """
        根据合约ID提取基础交易对（例如 SOL-USDT-SWAP -> SOL-USDT）
        """
        if not symbol:
            return None
        parts = symbol.split('-')
        if len(parts) <= 2:
            return symbol
        suffix = parts[-1].upper()
        if suffix in {'SWAP', 'FUTURES', 'FUT', 'SPOT', 'MARGIN', 'OPTION', 'OPT'}:
            return '-'.join(parts[:-1])
        return symbol

    async def _async_init(self):
        """异步初始化（创建连接池和会话）"""
        # 创建连接池（复用连接）
        self._connector = aiohttp.TCPConnector(
            limit=100,  # 连接池大小
            limit_per_host=30,  # 每个主机的连接数
            ttl_dns_cache=300,  # DNS缓存TTL
            force_close=False,  # 不强制关闭连接，复用连接
            enable_cleanup_closed=True  # 清理已关闭的连接
        )
        
        # 创建aiohttp会话（复用连接池）
        timeout = aiohttp.ClientTimeout(total=30, connect=10)
        self._session = aiohttp.ClientSession(
            connector=self._connector,
            timeout=timeout,
            headers={'Content-Type': 'application/json'}
        )
        
        self.logger.info("OKX客户端异步初始化完成（连接池已创建）")
    
    async def close(self):
        """关闭连接池和会话"""
        if self._session:
            await self._session.close()
            self._session = None
        if self._connector:
            await self._connector.close()
            self._connector = None
        self.logger.info("OKX客户端连接池已关闭")
    
    def _generate_signature(self, timestamp: str, method: str, request_path: str, body: str = "") -> str:
        """
        生成API签名
        
        Args:
            timestamp: 时间戳（ISO 8601格式）
            method: HTTP方法
            request_path: 请求路径
            body: 请求体（JSON字符串或空字符串）
            
        Returns:
            签名字符串（Base64编码）
        """
        if not self.secret_key:
            raise APIException("OKX Secret Key未配置")
        
        # 构建签名字符串：timestamp + method + request_path + body
        message = timestamp + method.upper() + request_path + (body if body else "")
        
        # 使用HMAC-SHA256生成签名
        mac = hmac.new(
            bytes(self.secret_key, encoding='utf-8'),
            bytes(message, encoding='utf-8'),
            digestmod=hashlib.sha256
        )
        return base64.b64encode(mac.digest()).decode()
    
    def _get_headers(self, method: str, request_path: str, body: str = "") -> Dict[str, str]:
        """
        获取请求头
        
        Args:
            method: HTTP方法
            request_path: 请求路径
            body: 请求体
            
        Returns:
            请求头字典
        """
        # OKX API要求ISO 8601格式的时间戳：YYYY-MM-DDTHH:MM:SS.sssZ
        now = datetime.utcnow()
        timestamp = now.strftime('%Y-%m-%dT%H:%M:%S.%f')[:-3] + 'Z'
        signature = self._generate_signature(timestamp, method, request_path, body)
        
        # 检查API密钥是否已配置
        if not all([self.api_key, self.secret_key, self.passphrase]):
            raise APIException("OKX API密钥未完整配置，请检查.env文件或配置文件")
        
        headers = {
            'OK-ACCESS-KEY': self.api_key,
            'OK-ACCESS-SIGN': signature,
            'OK-ACCESS-TIMESTAMP': timestamp,
            'OK-ACCESS-PASSPHRASE': self.passphrase,
            'Content-Type': 'application/json'
        }
        
        # 如果是测试模式（模拟盘），添加模拟盘标识
        if self.test_mode:
            headers['x-simulated-trading'] = '1'
        
        return headers
    
    async def _rate_limit(self):
        """API限流（异步版本）"""
        async with self._rate_limit_lock:
            current_time = time.time()
            min_interval = 1.0 / self.rest_requests_per_second
            
            if current_time - self.last_request_time < min_interval:
                sleep_time = min_interval - (current_time - self.last_request_time)
                await asyncio.sleep(sleep_time)
            
            self.last_request_time = time.time()
    
    def _rate_limit_sync(self):
        """API限流（同步版本）"""
        with self._rate_limit_sync_lock:
            current_time = time.time()
            min_interval = 1.0 / self.rest_requests_per_second
            if current_time - self.last_request_time < min_interval:
                sleep_time = min_interval - (current_time - self.last_request_time)
                if sleep_time > 0:
                    time.sleep(sleep_time)
            self.last_request_time = time.time()
    
    async def _request(self, method: str, endpoint: str, params: Optional[Dict] = None, 
                      data: Optional[Dict] = None, retry: int = 0) -> Dict[str, Any]:
        """
        发送API请求（异步版本，使用aiohttp）
        
        Args:
            method: HTTP方法
            endpoint: API端点
            params: URL参数
            data: 请求体数据
            retry: 重试次数
            
        Returns:
            API响应数据
        """
        # 确保会话已初始化
        if self._session is None:
            await self._async_init()
        
        await self._rate_limit()
        
        url = f"{self.base_url}{endpoint}"
        request_params = params
        body = ""
        if data:
            body = json.dumps(data)
        
        # 对于GET请求，需要将查询参数添加到请求路径中用于签名
        request_path = endpoint
        if method.upper() == 'GET' and params:
            # 构建查询字符串并排序（OKX要求）
            sorted_params = sorted(params.items())
            query_string = urlencode(sorted_params)
            request_path = f"{endpoint}?{query_string}"
            url = f"{self.base_url}{request_path}"
            request_params = None
        elif method.upper() == 'GET':
            request_params = None
        
        headers = self._get_headers(method, request_path, body)
        
        try:
            # 使用aiohttp发送异步请求
            async with self._session.request(
                method=method.upper(),
                url=url,
                headers=headers,
                params=request_params if method.upper() != 'GET' else None,
                json=data if method.upper() in ['POST', 'DELETE'] and data else None,
                data=body if method.upper() in ['POST', 'DELETE'] and not data else None
            ) as response:
                # 处理401未授权错误
                if response.status == 401:
                    error_detail = ""
                    try:
                        result = await response.json()
                        error_detail = result.get('msg', await response.text())
                    except:
                        error_detail = await response.text()
                    
                    self.logger.error(f"OKX API认证失败 (401): {error_detail}")
                    self.logger.error("请检查以下配置：")
                    self.logger.error(f"  - API Key: {'已配置' if self.api_key else '未配置'}")
                    self.logger.error(f"  - Secret Key: {'已配置' if self.secret_key else '未配置'}")
                    self.logger.error(f"  - Passphrase: {'已配置' if self.passphrase else '未配置'}")
                    raise APIException(f"OKX API认证失败: {error_detail}. 请检查API密钥配置")
                
                # 先检查HTTP状态码，如果是400错误，尝试获取详细错误信息
                if response.status == 400:
                    try:
                        result = await response.json()
                        error_msg = result.get('msg', '未知错误')
                        error_code = result.get('code', '未知')
                        error_data = result.get('data', [])
                        
                        # 记录详细错误信息
                        self.logger.error(f"OKX API 400错误 [{error_code}]: {error_msg}")
                        if error_data:
                            self.logger.error(f"错误详情: {error_data}")
                            # 如果是数组，提取第一个错误
                            if isinstance(error_data, list) and len(error_data) > 0:
                                first_error = error_data[0]
                                if isinstance(first_error, dict):
                                    s_code = first_error.get('sCode', '')
                                    s_msg = first_error.get('sMsg', '')
                                    if s_code or s_msg:
                                        self.logger.error(f"具体错误: sCode={s_code}, sMsg={s_msg}")
                        
                        # 记录请求参数以便调试
                        if params:
                            self.logger.debug(f"请求参数: {params}")
                        if data:
                            self.logger.debug(f"请求体: {data}")
                        
                        raise APIException(f"OKX API 400错误 [{error_code}]: {error_msg}")
                    except (ValueError, aiohttp.ContentTypeError):
                        # 如果不是JSON格式，记录原始响应
                        error_text = await response.text()
                        self.logger.error(f"OKX API 400错误，响应不是JSON格式: {error_text}")
                        raise APIException(f"OKX API 400错误: {error_text}")
                
                # 检查HTTP状态码
                if response.status >= 400:
                    error_text = await response.text()
                    self.logger.error(f"OKX API HTTP错误 [{response.status}]: {error_text}")
                    raise APIException(f"OKX API HTTP错误 [{response.status}]: {error_text}")
                
                # 解析JSON响应
                result = await response.json()
                
                if result.get('code') != '0':
                    error_msg = result.get('msg', '未知错误')
                    error_code = result.get('code', '未知')
                    error_data = result.get('data', [])
                    
                    # 记录详细错误信息
                    self.logger.error(f"OKX API错误 [{error_code}]: {error_msg}")
                    if error_data:
                        self.logger.error(f"错误详情: {error_data}")
                        # 如果是数组，提取第一个错误
                        if isinstance(error_data, list) and len(error_data) > 0:
                            first_error = error_data[0]
                            if isinstance(first_error, dict):
                                s_code = first_error.get('sCode', '')
                                s_msg = first_error.get('sMsg', '')
                                if s_code or s_msg:
                                    self.logger.error(f"具体错误: sCode={s_code}, sMsg={s_msg}")
                    
                    raise APIException(f"OKX API错误 [{error_code}]: {error_msg}")
                
                return result.get('data', {})
        
        except (aiohttp.ClientError, asyncio.TimeoutError) as e:
            self.logger.error(f"OKX API请求失败: {e}")
            
            # 重试逻辑
            if retry < self.max_retries:
                delay = self.retry_delay * (self.backoff_factor ** retry)
                self.logger.info(f"重试请求 (第{retry + 1}次)，延迟{delay}秒...")
                await asyncio.sleep(delay)
                return await self._request(method, endpoint, params, data, retry + 1)
            
            raise APIException(f"OKX API请求失败，已重试{self.max_retries}次: {e}")
    
    def _request_sync(self, method: str, endpoint: str, params: Optional[Dict] = None,
                      data: Optional[Dict] = None, retry: int = 0) -> Dict[str, Any]:
        """发送API请求（同步版本，使用requests）"""
        self._rate_limit_sync()
        
        url = f"{self.base_url}{endpoint}"
        request_params = params
        body = ""
        if data:
            body = json.dumps(data)
        
        request_path = endpoint
        if method.upper() == 'GET' and params:
            sorted_params = sorted(params.items())
            query_string = urlencode(sorted_params)
            request_path = f"{endpoint}?{query_string}"
            url = f"{self.base_url}{request_path}"
            request_params = None
        elif method.upper() == 'GET':
            request_params = None
        
        headers = self._get_headers(method, request_path, body)
        
        try:
            response = requests.request(
                method=method.upper(),
                url=url,
                headers=headers,
                params=request_params if method.upper() != 'GET' else None,
                json=data if method.upper() in ['POST', 'DELETE'] and data else None,
                data=body if method.upper() in ['POST', 'DELETE'] and not data else None,
                timeout=30,
            )
            
            if response.status_code == 401:
                try:
                    result = response.json()
                    error_detail = result.get('msg', response.text)
                except ValueError:
                    error_detail = response.text
                self.logger.error(f"OKX API认证失败 (401): {error_detail}")
                self.logger.error("请检查以下配置：")
                self.logger.error(f"  - API Key: {'已配置' if self.api_key else '未配置'}")
                self.logger.error(f"  - Secret Key: {'已配置' if self.secret_key else '未配置'}")
                self.logger.error(f"  - Passphrase: {'已配置' if self.passphrase else '未配置'}")
                raise APIException(f"OKX API认证失败: {error_detail}. 请检查API密钥配置")
            
            if response.status_code == 400:
                try:
                    result = response.json()
                    error_msg = result.get('msg', '未知错误')
                    error_code = result.get('code', '未知')
                    error_data = result.get('data', [])
                    self.logger.error(f"OKX API 400错误 [{error_code}]: {error_msg}")
                    if error_data:
                        self.logger.error(f"错误详情: {error_data}")
                        if isinstance(error_data, list) and error_data:
                            first_error = error_data[0]
                            if isinstance(first_error, dict):
                                s_code = first_error.get('sCode', '')
                                s_msg = first_error.get('sMsg', '')
                                if s_code or s_msg:
                                    self.logger.error(f"具体错误: sCode={s_code}, sMsg={s_msg}")
                    if params:
                        self.logger.debug(f"请求参数: {params}")
                    if data:
                        self.logger.debug(f"请求体: {data}")
                    raise APIException(f"OKX API 400错误 [{error_code}]: {error_msg}")
                except ValueError:
                    error_text = response.text
                    self.logger.error(f"OKX API 400错误，响应不是JSON格式: {error_text}")
                    raise APIException(f"OKX API 400错误: {error_text}")
            
            if response.status_code >= 400:
                error_text = response.text
                self.logger.error(f"OKX API HTTP错误 [{response.status_code}]: {error_text}")
                raise APIException(f"OKX API HTTP错误 [{response.status_code}]: {error_text}")
            
            try:
                result = response.json()
            except ValueError as e:
                self.logger.error(f"解析OKX API响应失败: {e}")
                raise APIException(f"解析OKX API响应失败: {e}")
            
            if result.get('code') != '0':
                error_msg = result.get('msg', '未知错误')
                error_code = result.get('code', '未知')
                error_data = result.get('data', [])
                self.logger.error(f"OKX API错误 [{error_code}]: {error_msg}")
                if error_data:
                    self.logger.error(f"错误详情: {error_data}")
                    if isinstance(error_data, list) and error_data:
                        first_error = error_data[0]
                        if isinstance(first_error, dict):
                            s_code = first_error.get('sCode', '')
                            s_msg = first_error.get('sMsg', '')
                            if s_code or s_msg:
                                self.logger.error(f"具体错误: sCode={s_code}, sMsg={s_msg}")
                raise APIException(f"OKX API错误 [{error_code}]: {error_msg}")
            
            return result.get('data', {})
        
        except requests.RequestException as e:
            self.logger.error(f"OKX API请求失败: {e}")
            if retry < self.max_retries:
                delay = self.retry_delay * (self.backoff_factor ** retry)
                self.logger.info(f"重试请求 (第{retry + 1}次)，延迟{delay}秒...")
                time.sleep(delay)
                return self._request_sync(method, endpoint, params, data, retry + 1)
            raise APIException(f"OKX API请求失败，已重试{self.max_retries}次: {e}")

    def _parse_algo_orders(self, result: Any, state: Optional[str] = None) -> List[Dict[str, Any]]:
        """解析算法订单响应"""
        orders: List[Dict[str, Any]] = []
        if isinstance(result, list):
            orders = result
        elif isinstance(result, dict):
            if 'data' in result:
                data_field = result.get('data', [])
                if isinstance(data_field, list):
                    orders = data_field
                elif isinstance(data_field, dict):
                    orders = [data_field]
            else:
                orders = [result]
        if state == 'live':
            orders = [order for order in orders if isinstance(order, dict) and order.get('state') == 'live']
        return orders
    
    async def async_get_ticker(self, symbol: str) -> Dict[str, Any]:
        """
        获取行情（异步版本）
        
        Args:
            symbol: 交易对符号，如 'BTC-USDT'
            
        Returns:
            行情数据
        """
        endpoint = f"/api/v5/market/ticker"
        params = {'instId': symbol}
        return await self._request('GET', endpoint, params=params)
    
    def get_ticker(self, symbol: str) -> Dict[str, Any]:
        """
        获取行情（同步版本，过渡用）
        
        注意：如果在异步环境中调用，请使用 async_get_ticker() 方法
        
        Args:
            symbol: 交易对符号，如 'BTC-USDT'
            
        Returns:
            行情数据
        """
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                # 如果已经在事件循环中，提示使用异步方法
                raise RuntimeError(
                    "在异步环境中不能使用同步方法 get_ticker()，请使用 async_get_ticker() 方法"
                )
            else:
                return loop.run_until_complete(self.async_get_ticker(symbol))
        except RuntimeError as e:
            if "不能使用同步方法" in str(e):
                raise
            # 如果没有事件循环，创建新的
            return asyncio.run(self.async_get_ticker(symbol))
    
    async def async_get_orderbook(self, symbol: str, depth: int = 20) -> Dict[str, Any]:
        """
        获取订单簿（异步版本）
        
        Args:
            symbol: 交易对符号
            depth: 深度（5, 10, 20, 50, 100, 200, 500）
            
        Returns:
            订单簿数据
        """
        endpoint = f"/api/v5/market/books"
        params = {'instId': symbol, 'sz': depth}
        return await self._request('GET', endpoint, params=params)
    
    def get_orderbook(self, symbol: str, depth: int = 20) -> Dict[str, Any]:
        """
        获取订单簿（同步版本，过渡用）
        
        注意：如果在异步环境中调用，请使用 async_get_orderbook() 方法
        
        Args:
            symbol: 交易对符号
            depth: 深度（5, 10, 20, 50, 100, 200, 500）
            
        Returns:
            订单簿数据
        """
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                raise RuntimeError(
                    "在异步环境中不能使用同步方法 get_orderbook()，请使用 async_get_orderbook() 方法"
                )
            else:
                return loop.run_until_complete(self.async_get_orderbook(symbol, depth))
        except RuntimeError as e:
            if "不能使用同步方法" in str(e):
                raise
            return asyncio.run(self.async_get_orderbook(symbol, depth))
    
    async def async_get_kline(self, symbol: str, interval: str = '1H', limit: int = 100) -> List[Dict[str, Any]]:
        """
        获取K线数据（异步版本）
        
        Args:
            symbol: 交易对符号
            interval: 时间间隔（1m, 3m, 5m, 15m, 30m, 1H, 2H, 4H, 6H, 12H, 1D, 1W, 1M）
            limit: 返回数量（1-100）
            
        Returns:
            K线数据列表
        """
        endpoint = f"/api/v5/market/candles"
        params = {
            'instId': symbol,
            'bar': interval,
            'limit': limit
        }
        return await self._request('GET', endpoint, params=params)
    
    async def async_get_trades(self, symbol: str, limit: int = 100) -> List[Dict[str, Any]]:
        """
        获取最近成交明细（异步版本）
        """
        endpoint = "/api/v5/market/trades"
        params = {
            'instId': symbol,
            'limit': limit
        }
        return await self._request('GET', endpoint, params=params)
    
    async def async_get_mark_price(self, symbol: str) -> List[Dict[str, Any]]:
        """
        获取标记价格信息
        """
        endpoint = "/api/v5/public/mark-price"
        params = {
            'instType': self._infer_inst_type(symbol),
            'instId': symbol
        }
        return await self._request('GET', endpoint, params=params)
    
    async def async_get_index_ticker(self, symbol: str) -> List[Dict[str, Any]]:
        """
        获取指数价格（用于计算基差）
        """
        endpoint = "/api/v5/market/index-tickers"
        params = {'instId': symbol}
        return await self._request('GET', endpoint, params=params)
    
    async def async_get_liquidation_orders(self, symbol: str, limit: int = 100) -> List[Dict[str, Any]]:
        """
        获取强平订单（已成交）
        """
        endpoint = "/api/v5/public/liquidation-orders"
        underlying = self._extract_underlying(symbol)
        params = {
            'instType': self._infer_inst_type(symbol),
            'instId': symbol,
            'uly': underlying,
            'state': 'filled',
            'limit': limit
        }
        return await self._request('GET', endpoint, params=params)
    
    async def async_get_funding_rate(self, symbol: str) -> List[Dict[str, Any]]:
        """
        获取永续合约资金费率
        """
        endpoint = "/api/v5/public/funding-rate"
        params = {'instId': symbol}
        return await self._request('GET', endpoint, params=params)
    
    async def async_get_open_interest(self, symbol: str) -> List[Dict[str, Any]]:
        """
        获取未平仓量
        """
        endpoint = "/api/v5/public/open-interest"
        params = {
            'instType': self._infer_inst_type(symbol),
            'instId': symbol
        }
        return await self._request('GET', endpoint, params=params)
    
    async def async_get_taker_volume(self, symbol: str, period: str = '5m') -> List[Dict[str, Any]]:
        """
        获取主动买卖量（Taker Volume）
        """
        endpoint = "/api/v5/market/taker-volume"
        underlying = self._extract_underlying(symbol)
        params = {
            'instType': self._infer_inst_type(symbol),
            'uly': underlying,
            'period': period
        }
        return await self._request('GET', endpoint, params=params)
    
    async def async_get_long_short_ratio(self, symbol: str, period: str = '5m') -> List[Dict[str, Any]]:
        """
        获取多空账户占比（Top Trader Sentiment）
        """
        endpoint = "/api/v5/market/account-ratio"
        underlying = self._extract_underlying(symbol)
        params = {
            'instType': self._infer_inst_type(symbol),
            'uly': underlying,
            'period': period
        }
        return await self._request('GET', endpoint, params=params)
    
    def get_kline(self, symbol: str, interval: str = '1H', limit: int = 100) -> List[Dict[str, Any]]:
        """
        获取K线数据（同步版本，过渡用）
        
        注意：如果在异步环境中调用，请使用 async_get_kline() 方法
        
        Args:
            symbol: 交易对符号
            interval: 时间间隔（1m, 3m, 5m, 15m, 30m, 1H, 2H, 4H, 6H, 12H, 1D, 1W, 1M）
            limit: 返回数量（1-100）
            
        Returns:
            K线数据列表
        """
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                raise RuntimeError(
                    "在异步环境中不能使用同步方法 get_kline()，请使用 async_get_kline() 方法"
                )
            else:
                return loop.run_until_complete(self.async_get_kline(symbol, interval, limit))
        except RuntimeError as e:
            if "不能使用同步方法" in str(e):
                raise
            return asyncio.run(self.async_get_kline(symbol, interval, limit))
    
    async def async_get_balance(self, currency: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        获取账户余额（异步版本）
        
        Args:
            currency: 币种，如果为None则返回所有币种
            
        Returns:
            余额列表
        """
        endpoint = "/api/v5/account/balance"
        params = {}
        if currency:
            params['ccy'] = currency
        
        return await self._request('GET', endpoint, params=params)
    
    def get_balance(self, currency: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        获取账户余额（同步版本，过渡用）
        
        注意：如果在异步环境中调用，请使用 async_get_balance() 方法
        
        Args:
            currency: 币种，如果为None则返回所有币种
            
        Returns:
            余额列表
        """
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                raise RuntimeError(
                    "在异步环境中不能使用同步方法 get_balance()，请使用 async_get_balance() 方法"
                )
            else:
                return loop.run_until_complete(self.async_get_balance(currency))
        except RuntimeError as e:
            if "不能使用同步方法" in str(e):
                raise
            return asyncio.run(self.async_get_balance(currency))
    
    def get_instruments(self, inst_type: str = "SWAP", symbol: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        获取合约信息
        
        Args:
            inst_type: 产品类型（SPOT, MARGIN, SWAP, FUTURES, OPTION）
            symbol: 交易对符号，如果为None则返回所有
        
        Returns:
            合约信息列表
        """
        endpoint = "/api/v5/public/instruments"
        params = {'instType': inst_type}  # instType是产品类型，不是交易对符号
        if symbol:
            params['instId'] = symbol  # instId是交易对符号
        
        return self._request_sync('GET', endpoint, params=params)
    
    async def async_get_positions(self, symbol: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        获取持仓（异步版本）
        
        Args:
            symbol: 交易对符号，如果为None则返回所有持仓
            
        Returns:
            持仓列表
        """
        endpoint = "/api/v5/account/positions"
        params = {}
        if symbol:
            params['instId'] = symbol
        
        return await self._request('GET', endpoint, params=params)
    
    def get_positions(self, symbol: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        获取持仓（同步版本，过渡用）
        
        注意：如果在异步环境中调用，请使用 async_get_positions() 方法
        
        Args:
            symbol: 交易对符号，如果为None则返回所有持仓
            
        Returns:
            持仓列表
        """
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                raise RuntimeError(
                    "在异步环境中不能使用同步方法 get_positions()，请使用 async_get_positions() 方法"
                )
            else:
                return loop.run_until_complete(self.async_get_positions(symbol))
        except RuntimeError as e:
            if "不能使用同步方法" in str(e):
                raise
            return asyncio.run(self.async_get_positions(symbol))
    
    def set_leverage(self, symbol: str, leverage: int, margin_mode: str = 'cross') -> Dict[str, Any]:
        """
        设置杠杆倍数
        
        Args:
            symbol: 交易对符号
            leverage: 杠杆倍数（1-125）
            margin_mode: 保证金模式（cross全仓, isolated逐仓）
            
        Returns:
            设置结果
        """
        endpoint = "/api/v5/account/set-leverage"
        
        # 判断产品类型
        if symbol.endswith('-SWAP'):
            inst_type = 'SWAP'
        elif symbol.endswith('-FUTURES'):
            inst_type = 'FUTURES'
        else:
            inst_type = 'SWAP'  # 默认SWAP
        
        data = {
            'instId': symbol,
            'lever': str(leverage),
            'mgnMode': margin_mode
        }
        
        self.logger.info(f"设置杠杆: {symbol}, 杠杆倍数={leverage}x, 保证金模式={margin_mode}")
        return self._request_sync('POST', endpoint, data=data)
    
    def place_order(self, symbol: str, side: str, order_type: str, 
                   size: str, price: Optional[str] = None,
                   pos_side: Optional[str] = None, reduce_only: bool = False,
                   stop_loss_price: Optional[str] = None,
                   take_profit_price: Optional[str] = None) -> Dict[str, Any]:
        """
        下单（支持合约交易，支持同时设置止盈止损）
        
        Args:
            symbol: 交易对符号
            side: 方向（buy, sell）
            order_type: 订单类型（market, limit）
            size: 数量
            price: 价格（限价单必填）
            pos_side: 持仓方向（long, short）- 合约交易使用
            reduce_only: 是否只减仓（平仓）- 合约交易使用
            stop_loss_price: 止损触发价格（可选，创建订单时同时设置止损）
            take_profit_price: 止盈触发价格（可选，创建订单时同时设置止盈）
            
        Returns:
            订单信息
        """
        endpoint = "/api/v5/trade/order"
        
        # 格式化数量字符串，确保精度正确且是lotSize的倍数
        from decimal import Decimal
        if isinstance(size, (int, float)):
            # 使用Decimal确保精度，避免浮点数误差
            size_decimal = Decimal(str(size))
            # 使用normalize()移除尾随零
            size_str = str(size_decimal.normalize())
            
            # 如果是空字符串或0，特殊处理
            if not size_str or size_str == '0':
                size_str = '0'
        else:
            size_str = str(size)
        
        order_data = {
            'instId': symbol,
            'tdMode': self.trade_mode,  # 交易模式：cross全仓（合约）, isolated逐仓（合约）, cash现货
            'side': side,  # buy或sell
            'ordType': order_type,
            'sz': size_str  # 确保数量是字符串格式，且精度正确
        }
        
        self.logger.debug(f"[下单数量格式化] {symbol}: 原始={size}, Decimal={size_decimal if isinstance(size, (int, float)) else 'N/A'}, 格式化后={size_str}")
        
        # 合约交易：必须设置持仓方向
        if self.trade_mode in ['cross', 'isolated']:
            # 合约交易必须指定posSide
            # 对于全仓/逐仓模式，使用"net"（单向持仓）或"long"/"short"（双向持仓）
            # 优先使用"net"（单向持仓模式），如果明确指定了posSide则使用指定的值
            if pos_side:
                # 如果指定了posSide，使用指定的值（long或short）
                order_data['posSide'] = pos_side
            else:
                # 如果没有指定posSide，使用"net"（单向持仓模式）
                # 或者根据side推断（buy->long, sell->short）
                # 先尝试"net"模式
                order_data['posSide'] = 'net'  # 单向持仓模式
        
        # 合约交易：平仓订单
        if reduce_only:
            order_data['reduceOnly'] = 'true'
        
        if order_type == 'limit' and price:
            order_data['px'] = str(price)  # 确保价格是字符串格式
        
        # 设置止盈止损（使用 attachAlgoOrds 数组附加算法订单）
        # 注意：止损和止盈应该合并到同一个对象中，而不是创建两个独立的对象
        if stop_loss_price or take_profit_price:
            algo_order = {}
            
            # 格式化止损价格
            if stop_loss_price:
                from decimal import Decimal
                if isinstance(stop_loss_price, (int, float)):
                    sl_price_decimal = Decimal(str(stop_loss_price))
                    sl_price_str = str(sl_price_decimal.normalize())
                else:
                    sl_price_str = str(stop_loss_price)
                
                algo_order['slTriggerPx'] = sl_price_str  # 止损触发价格
                algo_order['slTriggerPxType'] = 'last'  # 触发价格类型：最新价格
                algo_order['slOrdPx'] = sl_price_str  # 止损委托价格：使用触发价格作为限价
                
                self.logger.info(
                    f"✅ [开仓时设置止损] {symbol}: 止损触发价={sl_price_str}, "
                    f"触发类型=last, 委托类型=限价 | "
                    f"将在开仓订单中一次性设置，避免后续重复设置"
                )
            
            # 格式化止盈价格
            if take_profit_price:
                from decimal import Decimal
                if isinstance(take_profit_price, (int, float)):
                    tp_price_decimal = Decimal(str(take_profit_price))
                    tp_price_str = str(tp_price_decimal.normalize())
                else:
                    tp_price_str = str(take_profit_price)
                
                algo_order['tpTriggerPx'] = tp_price_str  # 止盈触发价格
                algo_order['tpTriggerPxType'] = 'last'  # 触发价格类型：最新价格
                # 注意：当同时设置止损和止盈时，止盈的 tpOrdPx 必须使用市价（-1）
                algo_order['tpOrdPx'] = '-1'  # 止盈委托价格：-1表示市价
                
                self.logger.info(
                    f"✅ [开仓时设置止盈] {symbol}: 止盈触发价={tp_price_str}, "
                    f"触发类型=last, 委托类型=市价 | "
                    f"将在开仓订单中一次性设置，避免后续重复设置"
                )
            
            # 合约交易：设置持仓方向（止损和止盈共享同一个 posSide）
            if self.trade_mode in ['cross', 'isolated']:
                if pos_side:
                    algo_order['posSide'] = pos_side
                else:
                    algo_order['posSide'] = 'net'
                algo_order['reduceOnly'] = 'true'  # 止损和止盈都是平仓
            
            # 将止损和止盈合并到一个对象中
            # 这样可以在一个订单中同时设置开仓、止盈、止损，避免后续多次设置
            order_data['attachAlgoOrds'] = [algo_order]
            
            self.logger.info(
                f"✅ [开仓时一次性设置止盈止损] {symbol}: "
                f"已通过 attachAlgoOrds 在开仓订单中同时设置止盈和止损 | "
                f"止损={sl_price_str if stop_loss_price else 'N/A'}, "
                f"止盈={tp_price_str if take_profit_price else 'N/A'} | "
                f"这样可以避免后续重复创建多个止盈止损订单"
            )
        
        # 记录订单参数（用于调试）
        self.logger.debug(f"[下单] 交易对: {symbol}, 订单参数: {order_data}")
        
        return self._request_sync('POST', endpoint, data=order_data)
    
    def place_stop_loss_order(self, symbol: str, side: str, size: str, 
                              trigger_price: str, order_price: Optional[str] = None,
                              pos_side: Optional[str] = None) -> Dict[str, Any]:
        """
        设置止损订单（条件单）
        
        Args:
            symbol: 交易对符号
            side: 方向（buy, sell）
            size: 数量
            trigger_price: 触发价格（当价格达到此价格时触发）
            order_price: 委托价格（触发后的下单价格，None表示使用触发价格作为限价）
            pos_side: 持仓方向（long, short）- 合约交易使用
            
        Returns:
            订单信息
        """
        endpoint = "/api/v5/trade/order-algo"
        
        # 格式化数量
        from decimal import Decimal
        if isinstance(size, (int, float)):
            size_decimal = Decimal(str(size))
            size_str = str(size_decimal.normalize())
        else:
            size_str = str(size)
        
        # 触发价格
        if isinstance(trigger_price, (int, float)):
            trigger_decimal = Decimal(str(trigger_price))
            trigger_price_str = str(trigger_decimal.normalize())
        else:
            trigger_price_str = str(trigger_price)
        
        # 格式化委托价格（限价单）
        if order_price is None:
            # 如果没有指定委托价格，使用触发价格作为限价
            order_price_str = trigger_price_str
        else:
            # 限价单
            if isinstance(order_price, (int, float)):
                price_decimal = Decimal(str(order_price))
                order_price_str = str(price_decimal.normalize())
            else:
                order_price_str = str(order_price)
        
        order_data = {
            'instId': symbol,
            'tdMode': self.trade_mode,  # 交易模式
            'side': side,  # buy或sell
            'ordType': 'conditional',  # 条件单
            'sz': size_str,  # 数量
            'slTriggerPx': trigger_price_str,  # 止损触发价格
            'slOrdPx': order_price_str  # 止损委托价格（限价）
        }
        
        # 合约交易：设置持仓方向
        if self.trade_mode in ['cross', 'isolated']:
            # 对于止损订单（平仓），posSide 必须明确指定，不能为空
            # 如果未指定，根据 side 推断：sell 表示平多仓(long)，buy 表示平空仓(short)
            if pos_side:
                # 确保pos_side是有效的值（long, short, net）
                if pos_side in ['long', 'short', 'net']:
                    order_data['posSide'] = pos_side
                else:
                    # 如果值无效，根据side推断
                    if side == 'sell':
                        order_data['posSide'] = 'long'  # 卖出平多仓
                    elif side == 'buy':
                        order_data['posSide'] = 'short'  # 买入平空仓
                    else:
                        order_data['posSide'] = 'net'
            else:
                # 根据 side 推断：sell 表示平多仓，buy 表示平空仓
                if side == 'sell':
                    order_data['posSide'] = 'long'  # 卖出平多仓
                elif side == 'buy':
                    order_data['posSide'] = 'short'  # 买入平空仓
                else:
                    # 如果无法推断，使用 net（可能在某些情况下不支持）
                    order_data['posSide'] = 'net'
            # 止损是平仓，设置reduceOnly
            order_data['reduceOnly'] = 'true'
        
        self.logger.info(
            f"设置止损订单（限价）: {symbol} {side} {size_str} @ 触发价={trigger_price_str}, "
            f"限价={order_price_str}"
        )
        
        return self._request_sync('POST', endpoint, data=order_data)
    
    def place_take_profit_order(self, symbol: str, side: str, size: str,
                                trigger_price: str, order_price: Optional[str] = None,
                                pos_side: Optional[str] = None) -> Dict[str, Any]:
        """
        设置止盈订单（条件单）
        
        Args:
            symbol: 交易对符号
            side: 方向（buy, sell）
            size: 数量
            trigger_price: 触发价格（当价格达到此价格时触发）
            order_price: 委托价格（触发后的下单价格，None表示使用触发价格作为限价）
            pos_side: 持仓方向（long, short）- 合约交易使用
            
        Returns:
            订单信息
        """
        endpoint = "/api/v5/trade/order-algo"
        
        # 格式化数量
        from decimal import Decimal
        if isinstance(size, (int, float)):
            size_decimal = Decimal(str(size))
            size_str = str(size_decimal.normalize())
        else:
            size_str = str(size)
        
        # 触发价格
        if isinstance(trigger_price, (int, float)):
            trigger_decimal = Decimal(str(trigger_price))
            trigger_price_str = str(trigger_decimal.normalize())
        else:
            trigger_price_str = str(trigger_price)
        
        # 格式化委托价格（限价单）
        if order_price is None:
            # 如果没有指定委托价格，使用触发价格作为限价
            order_price_str = trigger_price_str
        else:
            # 限价单
            if isinstance(order_price, (int, float)):
                price_decimal = Decimal(str(order_price))
                order_price_str = str(price_decimal.normalize())
            else:
                order_price_str = str(order_price)
        
        order_data = {
            'instId': symbol,
            'tdMode': self.trade_mode,  # 交易模式
            'side': side,  # buy或sell
            'ordType': 'conditional',  # 条件单
            'sz': size_str,  # 数量
            'tpTriggerPx': trigger_price_str,  # 止盈触发价格
            'tpOrdPx': order_price_str  # 止盈委托价格（限价）
        }
        
        # 合约交易：设置持仓方向
        if self.trade_mode in ['cross', 'isolated']:
            # 对于止盈订单（平仓），posSide 必须明确指定，不能为空
            # 如果未指定，根据 side 推断：sell 表示平多仓(long)，buy 表示平空仓(short)
            if pos_side:
                # 确保pos_side是有效的值（long, short, net）
                if pos_side in ['long', 'short', 'net']:
                    order_data['posSide'] = pos_side
                else:
                    # 如果值无效，根据side推断
                    if side == 'sell':
                        order_data['posSide'] = 'long'  # 卖出平多仓
                    elif side == 'buy':
                        order_data['posSide'] = 'short'  # 买入平空仓
                    else:
                        order_data['posSide'] = 'net'
            else:
                # 根据 side 推断：sell 表示平多仓，buy 表示平空仓
                if side == 'sell':
                    order_data['posSide'] = 'long'  # 卖出平多仓
                elif side == 'buy':
                    order_data['posSide'] = 'short'  # 买入平空仓
                else:
                    # 如果无法推断，使用 net（可能在某些情况下不支持）
                    order_data['posSide'] = 'net'
            # 止盈是平仓，设置reduceOnly
            order_data['reduceOnly'] = 'true'
        
        self.logger.info(
            f"设置止盈订单（限价）: {symbol} {side} {size_str} @ 触发价={trigger_price_str}, "
            f"限价={order_price_str}"
        )
        
        return self._request_sync('POST', endpoint, data=order_data)
    
    async def async_cancel_order(self, symbol: str, order_id: str) -> Dict[str, Any]:
        """
        撤单（异步）
        
        Args:
            symbol: 交易对符号
            order_id: 订单ID
            
        Returns:
            撤单结果
        """
        endpoint = "/api/v5/trade/cancel-order"
        data = {
            'instId': symbol,
            'ordId': order_id
        }
        return await self._request('POST', endpoint, data=data)
    
    def cancel_order(self, symbol: str, order_id: str) -> Dict[str, Any]:
        """撤单（同步）"""
        endpoint = "/api/v5/trade/cancel-order"
        data = {
            'instId': symbol,
            'ordId': order_id
        }
        return self._request_sync('POST', endpoint, data=data)
    
    async def async_cancel_algo_order(self, symbol: str, algo_id: str) -> Dict[str, Any]:
        """
        撤销算法订单（止盈止损订单）（异步）
        """
        endpoint = "/api/v5/trade/cancel-algo-order"
        data = {
            'instId': symbol,
            'algoId': algo_id
        }
        return await self._request('POST', endpoint, data=data)
    
    def cancel_algo_order(self, symbol: str, algo_id: str) -> Dict[str, Any]:
        """撤销算法订单（同步）"""
        endpoint = "/api/v5/trade/cancel-algo-order"
        data = {
            'instId': symbol,
            'algoId': algo_id
        }
        return self._request_sync('POST', endpoint, data=data)
    
    async def async_get_algo_orders(self, symbol: Optional[str] = None,
                                    order_type: Optional[str] = None,
                                    state: Optional[str] = None) -> List[Dict[str, Any]]:
        """查询算法订单（异步）"""
        endpoint = "/api/v5/trade/orders-algo-pending"
        params: Dict[str, Any] = {}
        inst_type = self._infer_inst_type(symbol)
        params['instType'] = inst_type
        if symbol:
            params['instId'] = symbol
        if order_type:
            params['ordType'] = order_type
        if state:
            params['state'] = state
        try:
            result = await self._request('GET', endpoint, params=params)
            return self._parse_algo_orders(result, state)
        except APIException as e:
            error_str = str(e)
            if 'ordType' in error_str:
                self.logger.debug(f"查询算法订单失败（ordType错误），尝试只传instId参数重试: {e}")
                try:
                    params_minimal: Dict[str, Any] = {}
                    if symbol:
                        params_minimal['instId'] = symbol
                    result = await self._request('GET', endpoint, params=params_minimal)
                    return self._parse_algo_orders(result, state)
                except Exception as retry_e:
                    self.logger.warning(f"查询算法订单重试失败（最小参数）: {retry_e}")
            elif 'state' in error_str and state:
                self.logger.debug(f"查询算法订单失败（state参数错误），尝试移除state参数重试: {e}")
                try:
                    params_no_state = {k: v for k, v in params.items() if k != 'state'}
                    result = await self._request('GET', endpoint, params=params_no_state)
                    return self._parse_algo_orders(result, state)
                except Exception as retry_e:
                    self.logger.warning(f"查询算法订单重试失败（移除state后）: {retry_e}")
            self.logger.warning(f"查询算法订单失败: {e}")
            return []
        except Exception as e:
            self.logger.warning(f"查询算法订单出现异常: {e}")
            return []
    
    def get_algo_orders(self, symbol: Optional[str] = None,
                        order_type: Optional[str] = None,
                        state: Optional[str] = None) -> List[Dict[str, Any]]:
        """查询算法订单（同步）"""
        endpoint = "/api/v5/trade/orders-algo-pending"
        params: Dict[str, Any] = {}
        inst_type = self._infer_inst_type(symbol)
        params['instType'] = inst_type
        if symbol:
            params['instId'] = symbol
        if order_type:
            params['ordType'] = order_type
        if state:
            params['state'] = state
        try:
            result = self._request_sync('GET', endpoint, params=params)
            return self._parse_algo_orders(result, state)
        except APIException as e:
            error_str = str(e)
            if 'ordType' in error_str:
                self.logger.debug(f"查询算法订单失败（ordType错误），尝试只传instId参数重试: {e}")
                try:
                    params_minimal: Dict[str, Any] = {}
                    if symbol:
                        params_minimal['instId'] = symbol
                    result = self._request_sync('GET', endpoint, params=params_minimal)
                    return self._parse_algo_orders(result, state)
                except Exception as retry_e:
                    self.logger.warning(f"查询算法订单重试失败（最小参数）: {retry_e}")
            elif 'state' in error_str and state:
                self.logger.debug(f"查询算法订单失败（state参数错误），尝试移除state参数重试: {e}")
                try:
                    params_no_state = {k: v for k, v in params.items() if k != 'state'}
                    result = self._request_sync('GET', endpoint, params=params_no_state)
                    return self._parse_algo_orders(result, state)
                except Exception as retry_e:
                    self.logger.warning(f"查询算法订单重试失败（移除state后）: {retry_e}")
            self.logger.warning(f"查询算法订单失败: {e}")
            return []
        except Exception as e:
            self.logger.warning(f"查询算法订单出现异常: {e}")
            return []
    
    def get_order_status(self, symbol: str, order_id: str) -> Dict[str, Any]:
        """查询订单状态（同步）"""
        endpoint = "/api/v5/trade/order"
        params = {
            'instId': symbol,
            'ordId': order_id
        }
        return self._request_sync('GET', endpoint, params=params)
    
    async def async_get_pending_orders(self, symbol: Optional[str] = None,
                                       order_type: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        获取待处理的订单（异步）
        """
        endpoint = "/api/v5/trade/orders-pending"
        params: Dict[str, Any] = {}
        inst_type = self._infer_inst_type(symbol)
        params['instType'] = inst_type
        if symbol:
            params['instId'] = symbol
        if order_type:
            params['ordType'] = order_type
        try:
            result = await self._request('GET', endpoint, params=params)
            if isinstance(result, list):
                return result
            if isinstance(result, dict):
                return result.get('data', [])
            return []
        except APIException as e:
            self.logger.warning(f"获取待处理订单失败: {e}")
            return []
        except Exception as e:
            self.logger.warning(f"获取待处理订单出现异常: {e}")
            return []
    
    def get_pending_orders(self, symbol: Optional[str] = None,
                          order_type: Optional[str] = None) -> List[Dict[str, Any]]:
        """获取待处理的订单（同步）"""
        endpoint = "/api/v5/trade/orders-pending"
        params: Dict[str, Any] = {}
        inst_type = self._infer_inst_type(symbol)
        params['instType'] = inst_type
        if symbol:
            params['instId'] = symbol
        if order_type:
            params['ordType'] = order_type
        result = self._request_sync('GET', endpoint, params=params)
        if isinstance(result, list):
            return result
        if isinstance(result, dict):
            return result.get('data', [])
        return []


if __name__ == "__main__":
    # 测试OKX客户端
    client = OKXClient()
    
    # 测试获取行情
    try:
        ticker = client.get_ticker("BTC-USDT")
        print("BTC-USDT 行情:", ticker)
    except Exception as e:
        print(f"获取行情失败: {e}")
