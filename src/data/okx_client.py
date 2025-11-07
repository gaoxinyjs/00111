#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
OKX API客户端
封装OKX API调用，处理API限流，错误重试机制
"""

import time
import json
import hmac
import base64
import hashlib
import asyncio
import threading
import contextlib
import atexit
from typing import Dict, List, Optional, Any, Tuple
from datetime import datetime
from urllib.parse import urlencode

import aiohttp
from aiohttp import ClientError, ClientSession
import requests
from ..core.config_manager import get_config_manager
from ..core.logger import get_logger
from ..core.security import get_security_manager
from ..core.exception import APIException


class OKXClient:
    """OKX API客户端"""

    _instance: Optional["OKXClient"] = None
    _instance_lock: threading.Lock = threading.Lock()

    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            with cls._instance_lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False  # type: ignore[attr-defined]
        return cls._instance

    def __init__(self):
        """初始化OKX客户端"""
        if getattr(self, "_initialized", False):
            return

        self.config_mgr = get_config_manager()
        self.logger = get_logger("okx_client")
        self.security = get_security_manager()

        # 获取配置
        okx_config = self.config_mgr.get_config("api", "okx")
        self.api_key = self.security.get_api_key("okx", "api_key")
        self.secret_key = self.security.get_api_key("okx", "secret_key")
        self.passphrase = self.security.get_api_key("okx", "passphrase")
        self.base_url = okx_config.get("base_url", "https://www.okx.com")
        self.test_mode = okx_config.get("test_mode", False)
        self.trade_mode = okx_config.get(
            "trade_mode", "cross"
        )  # 交易模式：cross全仓（合约）, isolated逐仓（合约）, cash现货
        self.timeout = okx_config.get("timeout", 10)

        # 限流配置
        rate_limit = okx_config.get("rate_limit", {})
        self.rest_requests_per_second = rate_limit.get("rest_requests_per_second", 10)
        self.last_request_time = 0
        self._sync_rate_limit_lock = threading.Lock()
        self._async_rate_limit_lock: Optional[asyncio.Lock] = None

        # 重试配置
        retry_config = okx_config.get("retry", {})
        self.max_retries = retry_config.get("max_retries", 3)
        self.retry_delay = retry_config.get("retry_delay", 1)
        self.backoff_factor = retry_config.get("backoff_factor", 2)
        self._session: Optional[ClientSession] = None
        self._session_lock: Optional[asyncio.Lock] = None

        if not all([self.api_key, self.secret_key, self.passphrase]):
            self.logger.warning("OKX API密钥未配置，请检查配置")

        self._initialized = True

    def _generate_signature(
        self, timestamp: str, method: str, request_path: str, body: str = ""
    ) -> str:
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
            bytes(self.secret_key, encoding="utf-8"),
            bytes(message, encoding="utf-8"),
            digestmod=hashlib.sha256,
        )
        return base64.b64encode(mac.digest()).decode()

    def _get_headers(
        self, method: str, request_path: str, body: str = ""
    ) -> Dict[str, str]:
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
        timestamp = now.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
        signature = self._generate_signature(timestamp, method, request_path, body)

        # 检查API密钥是否已配置
        if not all([self.api_key, self.secret_key, self.passphrase]):
            raise APIException("OKX API密钥未完整配置，请检查.env文件或配置文件")

        headers = {
            "OK-ACCESS-KEY": self.api_key,
            "OK-ACCESS-SIGN": signature,
            "OK-ACCESS-TIMESTAMP": timestamp,
            "OK-ACCESS-PASSPHRASE": self.passphrase,
            "Content-Type": "application/json",
        }

        # 如果是测试模式（模拟盘），添加模拟盘标识
        if self.test_mode:
            headers["x-simulated-trading"] = "1"

        return headers

    def _rate_limit(self):
        """API限流"""
        with self._sync_rate_limit_lock:
            current_time = time.time()
            min_interval = 1.0 / self.rest_requests_per_second
            if current_time - self.last_request_time < min_interval:
                sleep_time = min_interval - (current_time - self.last_request_time)
                time.sleep(sleep_time)
            self.last_request_time = time.time()

    async def _rate_limit_async(self):
        """异步API限流"""
        if self._async_rate_limit_lock is None:
            self._async_rate_limit_lock = asyncio.Lock()
        async with self._async_rate_limit_lock:
            current_time = time.time()
            min_interval = 1.0 / self.rest_requests_per_second
            if current_time - self.last_request_time < min_interval:
                sleep_time = min_interval - (current_time - self.last_request_time)
                await asyncio.sleep(sleep_time)
            self.last_request_time = time.time()

    async def _ensure_session(self) -> ClientSession:
        """确保 aiohttp 会话已创建"""
        if self._session and not self._session.closed:
            return self._session
        if self._session_lock is None:
            self._session_lock = asyncio.Lock()
        async with self._session_lock:
            if self._session is None or self._session.closed:
                timeout = aiohttp.ClientTimeout(total=self.timeout)
                self._session = ClientSession(base_url=self.base_url, timeout=timeout)
        return self._session

    async def close(self):
        """关闭底层 aiohttp 会话"""
        if self._session and not self._session.closed:
            await self._session.close()
            self._session = None
        self._session_lock = None
        self._async_rate_limit_lock = None

    def close_sync(self):
        """同步关闭会话（用于脚本）"""
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            asyncio.run(self.close())
        else:
            if loop.is_running():
                loop.create_task(self.close())
            else:
                loop.run_until_complete(self.close())
        self._session = None
        self._session_lock = None
        self._async_rate_limit_lock = None

    @classmethod
    def get_instance(cls) -> "OKXClient":
        """获取单例实例"""
        return cls()

    @classmethod
    def reset_instance(cls):
        """重置单例（主要用于测试）"""
        with cls._instance_lock:
            instance = cls._instance
            if instance is not None:
                with contextlib.suppress(Exception):
                    instance.close_sync()
                instance._initialized = False  # type: ignore[attr-defined]
                instance._session = None
                instance._session_lock = None
                instance._async_rate_limit_lock = None
                instance.last_request_time = 0
            cls._instance = None

    @classmethod
    def close_instance(cls):
        """在程序退出时关闭共享实例"""
        with cls._instance_lock:
            instance = cls._instance
            if instance is not None:
                with contextlib.suppress(Exception):
                    instance.close_sync()
                cls._instance = None

    def _request(
        self,
        method: str,
        endpoint: str,
        params: Optional[Dict] = None,
        data: Optional[Dict] = None,
        retry: int = 0,
    ) -> Dict[str, Any]:
        """
        发送API请求

        Args:
            method: HTTP方法
            endpoint: API端点
            params: URL参数
            data: 请求体数据

        Returns:
            API响应数据
        """
        self._rate_limit()

        url = f"{self.base_url}{endpoint}"
        body = ""
        if data:
            import json

            body = json.dumps(data)

        # 对于GET请求，需要将查询参数添加到请求路径中用于签名
        request_path = endpoint
        if method.upper() == "GET" and params:
            # 构建查询字符串并排序（OKX要求）
            from urllib.parse import urlencode

            sorted_params = sorted(params.items())
            query_string = urlencode(sorted_params)
            request_path = f"{endpoint}?{query_string}"

        headers = self._get_headers(method, request_path, body)

        try:
            if method.upper() == "GET":
                response = requests.get(
                    url, headers=headers, params=params, timeout=self.timeout
                )
            elif method.upper() == "POST":
                response = requests.post(
                    url, headers=headers, json=data, params=params, timeout=self.timeout
                )
            elif method.upper() == "DELETE":
                response = requests.delete(
                    url, headers=headers, json=data, params=params, timeout=self.timeout
                )
            else:
                raise APIException(f"不支持的HTTP方法: {method}")

            # 处理401未授权错误
            if response.status_code == 401:
                error_detail = ""
                try:
                    result = response.json()
                    error_detail = result.get("msg", response.text)
                except:
                    error_detail = response.text

                self.logger.error(f"OKX API认证失败 (401): {error_detail}")
                self.logger.error("请检查以下配置：")
                self.logger.error(
                    f"  - API Key: {'已配置' if self.api_key else '未配置'}"
                )
                self.logger.error(
                    f"  - Secret Key: {'已配置' if self.secret_key else '未配置'}"
                )
                self.logger.error(
                    f"  - Passphrase: {'已配置' if self.passphrase else '未配置'}"
                )
                raise APIException(
                    f"OKX API认证失败: {error_detail}. 请检查API密钥配置"
                )

            # 先检查HTTP状态码，如果是400错误，尝试获取详细错误信息
            if response.status_code == 400:
                try:
                    result = response.json()
                    error_msg = result.get("msg", "未知错误")
                    error_code = result.get("code", "未知")
                    error_data = result.get("data", [])

                    # 记录详细错误信息
                    self.logger.error(f"OKX API 400错误 [{error_code}]: {error_msg}")
                    if error_data:
                        self.logger.error(f"错误详情: {error_data}")
                        # 如果是数组，提取第一个错误
                        if isinstance(error_data, list) and len(error_data) > 0:
                            first_error = error_data[0]
                            if isinstance(first_error, dict):
                                s_code = first_error.get("sCode", "")
                                s_msg = first_error.get("sMsg", "")
                                if s_code or s_msg:
                                    self.logger.error(
                                        f"具体错误: sCode={s_code}, sMsg={s_msg}"
                                    )

                    # 记录请求参数以便调试
                    if params:
                        self.logger.debug(f"请求参数: {params}")
                    if data:
                        self.logger.debug(f"请求体: {data}")

                    raise APIException(f"OKX API 400错误 [{error_code}]: {error_msg}")
                except ValueError:
                    # 如果不是JSON格式，记录原始响应
                    self.logger.error(
                        f"OKX API 400错误，响应不是JSON格式: {response.text}"
                    )
                    raise APIException(f"OKX API 400错误: {response.text}")

            response.raise_for_status()
            result = response.json()

            if result.get("code") != "0":
                error_msg = result.get("msg", "未知错误")
                error_code = result.get("code", "未知")
                error_data = result.get("data", [])

                # 记录详细错误信息
                self.logger.error(f"OKX API错误 [{error_code}]: {error_msg}")
                if error_data:
                    self.logger.error(f"错误详情: {error_data}")
                    # 如果是数组，提取第一个错误
                    if isinstance(error_data, list) and len(error_data) > 0:
                        first_error = error_data[0]
                        if isinstance(first_error, dict):
                            s_code = first_error.get("sCode", "")
                            s_msg = first_error.get("sMsg", "")
                            if s_code or s_msg:
                                self.logger.error(
                                    f"具体错误: sCode={s_code}, sMsg={s_msg}"
                                )

                raise APIException(f"OKX API错误 [{error_code}]: {error_msg}")

            return result.get("data", {})

        except requests.exceptions.RequestException as e:
            self.logger.error(f"OKX API请求失败: {e}")

            # 重试逻辑
            if retry < self.max_retries:
                delay = self.retry_delay * (self.backoff_factor**retry)
                self.logger.info(f"重试请求 (第{retry + 1}次)，延迟{delay}秒...")
                time.sleep(delay)
                return self._request(method, endpoint, params, data, retry + 1)

            raise APIException(f"OKX API请求失败，已重试{self.max_retries}次: {e}")

    def get_ticker(self, symbol: str) -> Dict[str, Any]:
        """
        获取行情

        Args:
            symbol: 交易对符号，如 'BTC-USDT'

        Returns:
            行情数据
        """
        endpoint = f"/api/v5/market/ticker"
        params = {"instId": symbol}
        return self._request("GET", endpoint, params=params)

    async def get_ticker_async(self, symbol: str) -> Dict[str, Any]:
        """异步获取行情"""
        endpoint = "/api/v5/market/ticker"
        params = {"instId": symbol}
        return await self._request_async("GET", endpoint, params=params)

    async def _request_async(
        self,
        method: str,
        endpoint: str,
        params: Optional[Dict] = None,
        data: Optional[Dict] = None,
        retry: int = 0,
    ) -> Dict[str, Any]:
        """异步发送API请求"""
        await self._rate_limit_async()

        body = ""
        if data:
            body = json.dumps(data)

        request_path = endpoint
        if method.upper() == "GET" and params:
            sorted_params = sorted(params.items())
            query_string = urlencode(sorted_params)
            request_path = f"{endpoint}?{query_string}"

        headers = self._get_headers(method, request_path, body)
        session = await self._ensure_session()

        try:
            if method.upper() == "GET":
                http_method = session.get
                request_kwargs = {"params": params}
            elif method.upper() == "POST":
                http_method = session.post
                request_kwargs = {"json": data, "params": params}
            elif method.upper() == "DELETE":
                http_method = session.delete
                request_kwargs = {"json": data, "params": params}
            else:
                raise APIException(f"不支持的HTTP方法: {method}")

            async with http_method(
                endpoint, headers=headers, **request_kwargs
            ) as response:
                text = await response.text()

                if response.status == 401:
                    error_detail = ""
                    try:
                        result = json.loads(text)
                        error_detail = result.get("msg", text)
                    except json.JSONDecodeError:
                        error_detail = text
                    self.logger.error(f"OKX API认证失败 (401): {error_detail}")
                    self.logger.error("请检查以下配置：")
                    self.logger.error(
                        f"  - API Key: {'已配置' if self.api_key else '未配置'}"
                    )
                    self.logger.error(
                        f"  - Secret Key: {'已配置' if self.secret_key else '未配置'}"
                    )
                    self.logger.error(
                        f"  - Passphrase: {'已配置' if self.passphrase else '未配置'}"
                    )
                    raise APIException(
                        f"OKX API认证失败: {error_detail}. 请检查API密钥配置"
                    )

                if response.status == 400:
                    try:
                        result = json.loads(text)
                        error_msg = result.get("msg", "未知错误")
                        error_code = result.get("code", "未知")
                        error_data = result.get("data", [])
                        self.logger.error(
                            f"OKX API 400错误 [{error_code}]: {error_msg}"
                        )
                        if error_data:
                            self.logger.error(f"错误详情: {error_data}")
                            if isinstance(error_data, list) and len(error_data) > 0:
                                first_error = error_data[0]
                                if isinstance(first_error, dict):
                                    s_code = first_error.get("sCode", "")
                                    s_msg = first_error.get("sMsg", "")
                                    if s_code or s_msg:
                                        self.logger.error(
                                            f"具体错误: sCode={s_code}, sMsg={s_msg}"
                                        )
                        if params:
                            self.logger.debug(f"请求参数: {params}")
                        if data:
                            self.logger.debug(f"请求体: {data}")
                        raise APIException(
                            f"OKX API 400错误 [{error_code}]: {error_msg}"
                        )
                    except json.JSONDecodeError:
                        self.logger.error(f"OKX API 400错误，响应不是JSON格式: {text}")
                        raise APIException(f"OKX API 400错误: {text}")

                if response.status >= 400:
                    self.logger.error(
                        f"OKX API请求失败，状态码: {response.status}, 响应: {text}"
                    )
                    response.raise_for_status()

                try:
                    result = json.loads(text)
                except json.JSONDecodeError:
                    raise APIException(f"OKX API响应不是JSON格式: {text}")

                if result.get("code") != "0":
                    error_msg = result.get("msg", "未知错误")
                    error_code = result.get("code", "未知")
                    error_data = result.get("data", [])
                    self.logger.error(f"OKX API错误 [{error_code}]: {error_msg}")
                    if error_data:
                        self.logger.error(f"错误详情: {error_data}")
                        if isinstance(error_data, list) and len(error_data) > 0:
                            first_error = error_data[0]
                            if isinstance(first_error, dict):
                                s_code = first_error.get("sCode", "")
                                s_msg = first_error.get("sMsg", "")
                                if s_code or s_msg:
                                    self.logger.error(
                                        f"具体错误: sCode={s_code}, sMsg={s_msg}"
                                    )
                    raise APIException(f"OKX API错误 [{error_code}]: {error_msg}")

                return result.get("data", {})

        except (ClientError, asyncio.TimeoutError) as e:
            self.logger.error(f"OKX API请求失败: {e}")

            if retry < self.max_retries:
                delay = self.retry_delay * (self.backoff_factor**retry)
                self.logger.info(f"重试请求 (第{retry + 1}次)，延迟{delay}秒...")
                await asyncio.sleep(delay)
                return await self._request_async(
                    method, endpoint, params, data, retry + 1
                )

            raise APIException(f"OKX API请求失败，已重试{self.max_retries}次: {e}")

    def get_orderbook(self, symbol: str, depth: int = 20) -> Dict[str, Any]:
        """
        获取订单簿

        Args:
            symbol: 交易对符号
            depth: 深度（5, 10, 20, 50, 100, 200, 500）

        Returns:
            订单簿数据
        """
        endpoint = f"/api/v5/market/books"
        params = {"instId": symbol, "sz": depth}
        return self._request("GET", endpoint, params=params)

    async def get_orderbook_async(self, symbol: str, depth: int = 20) -> Dict[str, Any]:
        """异步获取订单簿"""
        endpoint = "/api/v5/market/books"
        params = {"instId": symbol, "sz": depth}
        return await self._request_async("GET", endpoint, params=params)

    def get_kline(
        self, symbol: str, interval: str = "1H", limit: int = 100
    ) -> List[Dict[str, Any]]:
        """
        获取K线数据

        Args:
            symbol: 交易对符号
            interval: 时间间隔（1m, 3m, 5m, 15m, 30m, 1H, 2H, 4H, 6H, 12H, 1D, 1W, 1M）
            limit: 返回数量（1-100）

        Returns:
            K线数据列表
        """
        endpoint = f"/api/v5/market/candles"
        params = {"instId": symbol, "bar": interval, "limit": limit}
        return self._request("GET", endpoint, params=params)

    async def get_kline_async(
        self, symbol: str, interval: str = "1H", limit: int = 100
    ) -> List[Dict[str, Any]]:
        """异步获取K线数据"""
        endpoint = "/api/v5/market/candles"
        params = {"instId": symbol, "bar": interval, "limit": limit}
        return await self._request_async("GET", endpoint, params=params)

    def get_balance(self, currency: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        获取账户余额

        Args:
            currency: 币种，如果为None则返回所有币种

        Returns:
            余额列表
        """
        endpoint = "/api/v5/account/balance"
        params = {}
        if currency:
            params["ccy"] = currency

        return self._request("GET", endpoint, params=params)

    async def get_balance_async(
        self, currency: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """异步获取账户余额"""
        endpoint = "/api/v5/account/balance"
        params = {}
        if currency:
            params["ccy"] = currency
        return await self._request_async("GET", endpoint, params=params)

    def get_instruments(
        self, inst_type: str = "SWAP", symbol: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """
        获取合约信息

        Args:
            inst_type: 产品类型（SPOT, MARGIN, SWAP, FUTURES, OPTION）
            symbol: 交易对符号，如果为None则返回所有

        Returns:
            合约信息列表
        """
        endpoint = "/api/v5/public/instruments"
        params = {"instType": inst_type}  # instType是产品类型，不是交易对符号
        if symbol:
            params["instId"] = symbol  # instId是交易对符号

        return self._request("GET", endpoint, params=params)

    async def get_instruments_async(
        self, inst_type: str = "SWAP", symbol: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """异步获取合约信息"""
        endpoint = "/api/v5/public/instruments"
        params = {"instType": inst_type}
        if symbol:
            params["instId"] = symbol
        return await self._request_async("GET", endpoint, params=params)

    def get_positions(self, symbol: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        获取持仓

        Args:
            symbol: 交易对符号，如果为None则返回所有持仓

        Returns:
            持仓列表
        """
        endpoint = "/api/v5/account/positions"
        params = {}
        if symbol:
            params["instId"] = symbol

        return self._request("GET", endpoint, params=params)

    async def get_positions_async(
        self, symbol: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """异步获取持仓"""
        endpoint = "/api/v5/account/positions"
        params = {}
        if symbol:
            params["instId"] = symbol
        return await self._request_async("GET", endpoint, params=params)

    def set_leverage(
        self, symbol: str, leverage: int, margin_mode: str = "cross"
    ) -> Dict[str, Any]:
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
        if symbol.endswith("-SWAP"):
            inst_type = "SWAP"
        elif symbol.endswith("-FUTURES"):
            inst_type = "FUTURES"
        else:
            inst_type = "SWAP"  # 默认SWAP

        data = {"instId": symbol, "lever": str(leverage), "mgnMode": margin_mode}

        self.logger.info(
            f"设置杠杆: {symbol}, 杠杆倍数={leverage}x, 保证金模式={margin_mode}"
        )
        return self._request("POST", endpoint, data=data)

    async def set_leverage_async(
        self, symbol: str, leverage: int, margin_mode: str = "cross"
    ) -> Dict[str, Any]:
        """异步设置杠杆倍数"""
        endpoint = "/api/v5/account/set-leverage"
        if symbol.endswith("-SWAP"):
            inst_type = "SWAP"
        elif symbol.endswith("-FUTURES"):
            inst_type = "FUTURES"
        else:
            inst_type = "SWAP"

        data = {"instId": symbol, "lever": str(leverage), "mgnMode": margin_mode}

        self.logger.info(
            f"设置杠杆(异步): {symbol}, 杠杆倍数={leverage}x, 保证金模式={margin_mode}"
        )
        return await self._request_async("POST", endpoint, data=data)

    def _prepare_place_order_payload(
        self,
        symbol: str,
        side: str,
        order_type: str,
        size: str,
        price: Optional[str] = None,
        pos_side: Optional[str] = None,
        reduce_only: bool = False,
        stop_loss_price: Optional[str] = None,
        take_profit_price: Optional[str] = None,
    ) -> Tuple[str, Dict[str, Any]]:
        """
        构建下单请求数据（内部使用）

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
            包含请求端点和订单数据的元组
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
            if not size_str or size_str == "0":
                size_str = "0"
        else:
            size_str = str(size)

        order_data = {
            "instId": symbol,
            "tdMode": self.trade_mode,  # 交易模式：cross全仓（合约）, isolated逐仓（合约）, cash现货
            "side": side,  # buy或sell
            "ordType": order_type,
            "sz": size_str,  # 确保数量是字符串格式，且精度正确
        }

        self.logger.debug(
            f"[下单数量格式化] {symbol}: 原始={size}, Decimal={size_decimal if isinstance(size, (int, float)) else 'N/A'}, 格式化后={size_str}"
        )

        # 合约交易：必须设置持仓方向
        if self.trade_mode in ["cross", "isolated"]:
            # 合约交易必须指定posSide
            # 对于全仓/逐仓模式，使用"net"（单向持仓）或"long"/"short"（双向持仓）
            # 优先使用"net"（单向持仓模式），如果明确指定了posSide则使用指定的值
            if pos_side:
                # 如果指定了posSide，使用指定的值（long或short）
                order_data["posSide"] = pos_side
            else:
                # 如果没有指定posSide，使用"net"（单向持仓模式）
                # 或者根据side推断（buy->long, sell->short）
                # 先尝试"net"模式
                order_data["posSide"] = "net"  # 单向持仓模式

        # 合约交易：平仓订单
        if reduce_only:
            order_data["reduceOnly"] = "true"

        if order_type == "limit" and price:
            order_data["px"] = str(price)  # 确保价格是字符串格式

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

                algo_order["slTriggerPx"] = sl_price_str  # 止损触发价格
                algo_order["slTriggerPxType"] = "last"  # 触发价格类型：最新价格
                algo_order["slOrdPx"] = (
                    sl_price_str  # 止损委托价格：使用触发价格作为限价
                )

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

                algo_order["tpTriggerPx"] = tp_price_str  # 止盈触发价格
                algo_order["tpTriggerPxType"] = "last"  # 触发价格类型：最新价格
                # 注意：当同时设置止损和止盈时，止盈的 tpOrdPx 必须使用市价（-1）
                algo_order["tpOrdPx"] = "-1"  # 止盈委托价格：-1表示市价

                self.logger.info(
                    f"✅ [开仓时设置止盈] {symbol}: 止盈触发价={tp_price_str}, "
                    f"触发类型=last, 委托类型=市价 | "
                    f"将在开仓订单中一次性设置，避免后续重复设置"
                )

            # 合约交易：设置持仓方向（止损和止盈共享同一个 posSide）
            if self.trade_mode in ["cross", "isolated"]:
                if pos_side:
                    algo_order["posSide"] = pos_side
                else:
                    algo_order["posSide"] = "net"
                algo_order["reduceOnly"] = "true"  # 止损和止盈都是平仓

            # 将止损和止盈合并到一个对象中
            # 这样可以在一个订单中同时设置开仓、止盈、止损，避免后续多次设置
            order_data["attachAlgoOrds"] = [algo_order]

            self.logger.info(
                f"✅ [开仓时一次性设置止盈止损] {symbol}: "
                f"已通过 attachAlgoOrds 在开仓订单中同时设置止盈和止损 | "
                f"止损={sl_price_str if stop_loss_price else 'N/A'}, "
                f"止盈={tp_price_str if take_profit_price else 'N/A'} | "
                f"这样可以避免后续重复创建多个止盈止损订单"
            )

        # 记录订单参数（用于调试）
        self.logger.debug(f"[下单] 交易对: {symbol}, 订单参数: {order_data}")

        return endpoint, order_data

    def place_order(
        self,
        symbol: str,
        side: str,
        order_type: str,
        size: str,
        price: Optional[str] = None,
        pos_side: Optional[str] = None,
        reduce_only: bool = False,
        stop_loss_price: Optional[str] = None,
        take_profit_price: Optional[str] = None,
    ) -> Dict[str, Any]:
        """同步下单接口"""
        endpoint, order_data = self._prepare_place_order_payload(
            symbol,
            side,
            order_type,
            size,
            price,
            pos_side,
            reduce_only,
            stop_loss_price,
            take_profit_price,
        )
        return self._request("POST", endpoint, data=order_data)

    async def place_order_async(
        self,
        symbol: str,
        side: str,
        order_type: str,
        size: str,
        price: Optional[str] = None,
        pos_side: Optional[str] = None,
        reduce_only: bool = False,
        stop_loss_price: Optional[str] = None,
        take_profit_price: Optional[str] = None,
    ) -> Dict[str, Any]:
        """异步下单接口"""
        endpoint, order_data = self._prepare_place_order_payload(
            symbol,
            side,
            order_type,
            size,
            price,
            pos_side,
            reduce_only,
            stop_loss_price,
            take_profit_price,
        )
        return await self._request_async("POST", endpoint, data=order_data)

    def _prepare_stop_loss_order_payload(
        self,
        symbol: str,
        side: str,
        size: str,
        trigger_price: str,
        order_price: Optional[str] = None,
        pos_side: Optional[str] = None,
    ) -> Tuple[str, Dict[str, Any]]:
        """构建止损订单请求数据（内部使用）"""
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
            "instId": symbol,
            "tdMode": self.trade_mode,  # 交易模式
            "side": side,  # buy或sell
            "ordType": "conditional",  # 条件单
            "sz": size_str,  # 数量
            "slTriggerPx": trigger_price_str,  # 止损触发价格
            "slOrdPx": order_price_str,  # 止损委托价格（限价）
        }

        # 合约交易：设置持仓方向
        if self.trade_mode in ["cross", "isolated"]:
            # 对于止损订单（平仓），posSide 必须明确指定，不能为空
            # 如果未指定，根据 side 推断：sell 表示平多仓(long)，buy 表示平空仓(short)
            if pos_side:
                # 确保pos_side是有效的值（long, short, net）
                if pos_side in ["long", "short", "net"]:
                    order_data["posSide"] = pos_side
                else:
                    # 如果值无效，根据side推断
                    if side == "sell":
                        order_data["posSide"] = "long"  # 卖出平多仓
                    elif side == "buy":
                        order_data["posSide"] = "short"  # 买入平空仓
                    else:
                        order_data["posSide"] = "net"
            else:
                # 根据 side 推断：sell 表示平多仓，buy 表示平空仓
                if side == "sell":
                    order_data["posSide"] = "long"  # 卖出平多仓
                elif side == "buy":
                    order_data["posSide"] = "short"  # 买入平空仓
                else:
                    # 如果无法推断，使用 net（可能在某些情况下不支持）
                    order_data["posSide"] = "net"
            # 止损是平仓，设置reduceOnly
            order_data["reduceOnly"] = "true"

        self.logger.info(
            f"设置止损订单（限价）: {symbol} {side} {size_str} @ 触发价={trigger_price_str}, "
            f"限价={order_price_str}"
        )

        return endpoint, order_data

    def place_stop_loss_order(
        self,
        symbol: str,
        side: str,
        size: str,
        trigger_price: str,
        order_price: Optional[str] = None,
        pos_side: Optional[str] = None,
    ) -> Dict[str, Any]:
        """同步设置止损订单"""
        endpoint, order_data = self._prepare_stop_loss_order_payload(
            symbol, side, size, trigger_price, order_price, pos_side
        )
        return self._request("POST", endpoint, data=order_data)

    async def place_stop_loss_order_async(
        self,
        symbol: str,
        side: str,
        size: str,
        trigger_price: str,
        order_price: Optional[str] = None,
        pos_side: Optional[str] = None,
    ) -> Dict[str, Any]:
        """异步设置止损订单"""
        endpoint, order_data = self._prepare_stop_loss_order_payload(
            symbol, side, size, trigger_price, order_price, pos_side
        )
        return await self._request_async("POST", endpoint, data=order_data)

    def _prepare_take_profit_order_payload(
        self,
        symbol: str,
        side: str,
        size: str,
        trigger_price: str,
        order_price: Optional[str] = None,
        pos_side: Optional[str] = None,
    ) -> Tuple[str, Dict[str, Any]]:
        """构建止盈订单请求数据（内部使用）"""
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
            "instId": symbol,
            "tdMode": self.trade_mode,  # 交易模式
            "side": side,  # buy或sell
            "ordType": "conditional",  # 条件单
            "sz": size_str,  # 数量
            "tpTriggerPx": trigger_price_str,  # 止盈触发价格
            "tpOrdPx": order_price_str,  # 止盈委托价格（限价）
        }

        # 合约交易：设置持仓方向
        if self.trade_mode in ["cross", "isolated"]:
            # 对于止盈订单（平仓），posSide 必须明确指定，不能为空
            # 如果未指定，根据 side 推断：sell 表示平多仓(long)，buy 表示平空仓(short)
            if pos_side:
                # 确保pos_side是有效的值（long, short, net）
                if pos_side in ["long", "short", "net"]:
                    order_data["posSide"] = pos_side
                else:
                    # 如果值无效，根据side推断
                    if side == "sell":
                        order_data["posSide"] = "long"  # 卖出平多仓
                    elif side == "buy":
                        order_data["posSide"] = "short"  # 买入平空仓
                    else:
                        order_data["posSide"] = "net"
            else:
                # 根据 side 推断：sell 表示平多仓，buy 表示平空仓
                if side == "sell":
                    order_data["posSide"] = "long"  # 卖出平多仓
                elif side == "buy":
                    order_data["posSide"] = "short"  # 买入平空仓
                else:
                    # 如果无法推断，使用 net（可能在某些情况下不支持）
                    order_data["posSide"] = "net"
            # 止盈是平仓，设置reduceOnly
            order_data["reduceOnly"] = "true"

        self.logger.info(
            f"设置止盈订单（限价）: {symbol} {side} {size_str} @ 触发价={trigger_price_str}, "
            f"限价={order_price_str}"
        )

        return endpoint, order_data

    def place_take_profit_order(
        self,
        symbol: str,
        side: str,
        size: str,
        trigger_price: str,
        order_price: Optional[str] = None,
        pos_side: Optional[str] = None,
    ) -> Dict[str, Any]:
        """同步设置止盈订单"""
        endpoint, order_data = self._prepare_take_profit_order_payload(
            symbol, side, size, trigger_price, order_price, pos_side
        )
        return self._request("POST", endpoint, data=order_data)

    async def place_take_profit_order_async(
        self,
        symbol: str,
        side: str,
        size: str,
        trigger_price: str,
        order_price: Optional[str] = None,
        pos_side: Optional[str] = None,
    ) -> Dict[str, Any]:
        """异步设置止盈订单"""
        endpoint, order_data = self._prepare_take_profit_order_payload(
            symbol, side, size, trigger_price, order_price, pos_side
        )
        return await self._request_async("POST", endpoint, data=order_data)

    def cancel_order(self, symbol: str, order_id: str) -> Dict[str, Any]:
        """
        撤单

        Args:
            symbol: 交易对符号
            order_id: 订单ID

        Returns:
            撤单结果
        """
        endpoint = "/api/v5/trade/cancel-order"
        data = {"instId": symbol, "ordId": order_id}
        return self._request("POST", endpoint, data=data)

    async def cancel_order_async(self, symbol: str, order_id: str) -> Dict[str, Any]:
        """异步撤单"""
        endpoint = "/api/v5/trade/cancel-order"
        data = {"instId": symbol, "ordId": order_id}
        return await self._request_async("POST", endpoint, data=data)

    def cancel_algo_order(self, symbol: str, algo_id: str) -> Dict[str, Any]:
        """
        撤销算法订单（止盈止损订单）

        Args:
            symbol: 交易对符号
            algo_id: 算法订单ID

        Returns:
            撤单结果
        """
        endpoint = "/api/v5/trade/cancel-algo-order"
        data = {"instId": symbol, "algoId": algo_id}
        return self._request("POST", endpoint, data=data)

    async def cancel_algo_order_async(
        self, symbol: str, algo_id: str
    ) -> Dict[str, Any]:
        """异步撤销算法订单"""
        endpoint = "/api/v5/trade/cancel-algo-order"
        data = {"instId": symbol, "algoId": algo_id}
        return await self._request_async("POST", endpoint, data=data)

    def get_algo_orders(
        self,
        symbol: Optional[str] = None,
        order_type: Optional[str] = None,
        state: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """
        查询算法订单（止盈止损订单）

        Args:
            symbol: 交易对符号，如果为None则返回所有
            order_type: 订单类型（conditional, oco, trigger, move_order_stop, iceberg, twap）
                      注意：对于通过attachAlgoOrds创建的止盈止损订单，查询时不需要传递此参数
            state: 订单状态（live, effective, canceled, order_failed, system_canceled）

        Returns:
            算法订单列表
        """
        endpoint = "/api/v5/trade/orders-algo-pending"
        params = {}
        if symbol:
            params["instId"] = symbol
        # 注意：完全不传递ordType参数，避免Parameter ordType error
        # 对于通过attachAlgoOrds创建的止盈止损订单，查询时不需要传递ordType参数
        # 即使order_type参数被传入，也不添加到params中
        if state:
            params["state"] = state

        try:
            result = self._request("GET", endpoint, params=params)

            # _request方法返回的是data字段，如果是列表则直接返回
            if isinstance(result, list):
                return result
            # 如果是字典，尝试提取data字段
            elif isinstance(result, dict):
                # 如果result包含code字段，说明是完整的响应
                if "code" in result:
                    if result.get("code") == "0":
                        return result.get("data", [])
                    else:
                        error_msg = result.get("msg", "未知错误")
                        self.logger.warning(f"查询算法订单失败: {error_msg}")
                        return []
                # 否则result本身就是data字段
                else:
                    # 如果result是字典但包含列表，尝试提取
                    if "data" in result:
                        return result.get("data", [])
                    # 如果result本身就是列表结构，返回空列表
                    return []
            else:
                return []
        except Exception as e:
            error_str = str(e)
            # 改进错误处理：对于400错误，尝试不传problematic参数重试
            if "400" in error_str or "51000" in error_str:
                # 如果错误包含ordType相关错误，说明可能有其他地方传递了ordType参数
                # 由于我们已经不传递ordType参数，这个错误可能是API的误报
                # 尝试不传任何可选参数重试（只保留instId）
                if "ordType" in error_str:
                    self.logger.debug(
                        f"查询算法订单失败（ordType错误），尝试只传instId参数重试: {e}"
                    )
                    try:
                        # 只保留instId参数重试
                        params_minimal = {}
                        if symbol:
                            params_minimal["instId"] = symbol
                        result = self._request("GET", endpoint, params=params_minimal)
                        if isinstance(result, list):
                            # 如果结果是列表，手动过滤state
                            if state == "live":
                                return [
                                    order
                                    for order in result
                                    if order.get("state") == "live"
                                ]
                            return result
                        elif isinstance(result, dict):
                            if "code" in result and result.get("code") == "0":
                                data = result.get("data", [])
                                if state == "live":
                                    return [
                                        order
                                        for order in data
                                        if order.get("state") == "live"
                                    ]
                                return data
                        return []
                    except Exception as retry_e:
                        self.logger.warning(
                            f"查询算法订单重试失败（最小参数）: {retry_e}"
                        )

                # 如果错误包含state相关错误，尝试不传state参数重试
                elif "state" in error_str and state:
                    self.logger.debug(
                        f"查询算法订单失败（参数state={state}），尝试不传state参数重试: {e}"
                    )
                    try:
                        # 移除state参数重试
                        params_no_state = {
                            k: v for k, v in params.items() if k != "state"
                        }
                        result = self._request("GET", endpoint, params=params_no_state)
                        if isinstance(result, list):
                            # 如果结果是列表，手动过滤state
                            if state == "live":
                                return [
                                    order
                                    for order in result
                                    if order.get("state") == "live"
                                ]
                            return result
                        elif isinstance(result, dict):
                            if "code" in result and result.get("code") == "0":
                                data = result.get("data", [])
                                if state == "live":
                                    return [
                                        order
                                        for order in data
                                        if order.get("state") == "live"
                                    ]
                                return data
                        return []
                    except Exception as retry_e:
                        self.logger.warning(
                            f"查询算法订单重试失败（移除state后）: {retry_e}"
                        )

            # 如果重试失败或不是400错误，记录警告并返回空列表
            self.logger.warning(f"查询算法订单失败: {e}")
            return []

    async def get_algo_orders_async(
        self,
        symbol: Optional[str] = None,
        order_type: Optional[str] = None,
        state: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """异步查询算法订单"""
        endpoint = "/api/v5/trade/orders-algo-pending"
        params = {}
        if symbol:
            params["instId"] = symbol
        if state:
            params["state"] = state

        try:
            result = await self._request_async("GET", endpoint, params=params)
            if isinstance(result, list):
                if state == "live":
                    return [order for order in result if order.get("state") == "live"]
                return result
            elif isinstance(result, dict):
                if "code" in result:
                    if result.get("code") == "0":
                        data = result.get("data", [])
                        if state == "live":
                            return [
                                order for order in data if order.get("state") == "live"
                            ]
                        return data
                    else:
                        error_msg = result.get("msg", "未知错误")
                        self.logger.warning(f"查询算法订单失败: {error_msg}")
                        return []
                elif "data" in result:
                    data = result.get("data", [])
                    if state == "live":
                        return [order for order in data if order.get("state") == "live"]
                    return data
                else:
                    return []
            else:
                return []
        except Exception as e:
            self.logger.warning(f"查询算法订单失败(异步): {e}")
            return []

    def get_order_status(self, symbol: str, order_id: str) -> Dict[str, Any]:
        """
        查询订单状态

        Args:
            symbol: 交易对符号
            order_id: 订单ID

        Returns:
            订单状态信息
        """
        endpoint = "/api/v5/trade/order"
        params = {"instId": symbol, "ordId": order_id}
        return self._request("GET", endpoint, params=params)

    async def get_order_status_async(
        self, symbol: str, order_id: str
    ) -> Dict[str, Any]:
        """异步查询订单状态"""
        endpoint = "/api/v5/trade/order"
        params = {"instId": symbol, "ordId": order_id}
        return await self._request_async("GET", endpoint, params=params)

    def get_pending_orders(
        self, symbol: Optional[str] = None, order_type: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """
        获取待处理的订单（委托）

        Args:
            symbol: 交易对符号，如果为None则返回所有
            order_type: 订单类型（market, limit, post_only, fok, ioc, optimal_limit_ioc）

        Returns:
            待处理订单列表
        """
        endpoint = "/api/v5/trade/orders-pending"
        params = {}
        if symbol:
            params["instId"] = symbol
        if order_type:
            params["ordType"] = order_type

        result = self._request("GET", endpoint, params=params)

        # OKX API返回格式：{"code":"0","data":[...],"msg":""}
        if result and isinstance(result, dict):
            if result.get("code") == "0":
                return result.get("data", [])

        return []

    async def get_pending_orders_async(
        self, symbol: Optional[str] = None, order_type: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """异步获取待处理订单"""
        endpoint = "/api/v5/trade/orders-pending"
        params = {}
        if symbol:
            params["instId"] = symbol
        if order_type:
            params["ordType"] = order_type

        result = await self._request_async("GET", endpoint, params=params)

        if result and isinstance(result, dict):
            if result.get("code") == "0":
                return result.get("data", [])

        if isinstance(result, list):
            return result

        return []


async def get_okx_client() -> OKXClient:
    """获取已经初始化的 OKXClient 单例（异步确保会话可用）"""
    client = OKXClient.get_instance()
    await client._ensure_session()
    return client


atexit.register(OKXClient.close_instance)

if __name__ == "__main__":
    # 测试OKX客户端
    client = OKXClient.get_instance()

    # 测试获取行情
    try:
        ticker = client.get_ticker("BTC-USDT")
        print("BTC-USDT 行情:", ticker)
    except Exception as e:
        print(f"获取行情失败: {e}")
