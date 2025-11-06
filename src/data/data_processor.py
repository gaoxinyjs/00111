#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
数据处理器
数据清洗和标准化，技术指标计算，数据聚合和统计
"""

import pandas as pd
import numpy as np
from typing import Dict, List, Optional, Any
from ..core.logger import get_logger


class DataProcessor:
    """数据处理器"""
    
    def __init__(self):
        """初始化数据处理器"""
        self.logger = get_logger("data_processor")
    
    def clean_kline_data(self, kline_data: List[Dict[str, Any]]) -> pd.DataFrame:
        """
        清洗K线数据
        
        Args:
            kline_data: 原始K线数据列表
            
        Returns:
            清洗后的DataFrame
        """
        if not kline_data:
            return pd.DataFrame()
        
        df = pd.DataFrame(kline_data)
        
        # 确保数据类型正确
        # 先将timestamp转换为数值类型，避免FutureWarning
        timestamp_numeric = pd.to_numeric(df['timestamp'], errors='coerce')
        df['timestamp'] = pd.to_datetime(timestamp_numeric, unit='ms', errors='coerce')
        df['open'] = pd.to_numeric(df['open'], errors='coerce')
        df['high'] = pd.to_numeric(df['high'], errors='coerce')
        df['low'] = pd.to_numeric(df['low'], errors='coerce')
        df['close'] = pd.to_numeric(df['close'], errors='coerce')
        df['volume'] = pd.to_numeric(df['volume'], errors='coerce')
        
        # 去除异常值（价格不能为负，成交量不能为负）
        df = df[(df['open'] > 0) & (df['high'] > 0) & (df['low'] > 0) & (df['close'] > 0)]
        df = df[df['volume'] >= 0]
        
        # 去除重复时间戳
        df = df.drop_duplicates(subset=['timestamp'], keep='last')
        
        # 按时间排序
        df = df.sort_values('timestamp').reset_index(drop=True)
        
        # 填充缺失值（前向填充，然后后向填充）
        df = df.ffill().bfill()
        
        return df
    
    def calculate_macd(self, df: pd.DataFrame, fast: int = 12, slow: int = 26, signal: int = 9) -> pd.DataFrame:
        """
        计算MACD指标
        
        Args:
            df: K线DataFrame
            fast: 快线周期
            slow: 慢线周期
            signal: 信号线周期
            
        Returns:
            包含MACD指标的DataFrame
        """
        if 'close' not in df.columns or len(df) < slow:
            return df
        
        # 计算EMA
        ema_fast = df['close'].ewm(span=fast, adjust=False).mean()
        ema_slow = df['close'].ewm(span=slow, adjust=False).mean()
        
        # MACD线
        df['macd'] = ema_fast - ema_slow
        
        # 信号线
        df['macd_signal'] = df['macd'].ewm(span=signal, adjust=False).mean()
        
        # 柱状图
        df['macd_hist'] = df['macd'] - df['macd_signal']
        
        return df
    
    def calculate_ma(self, df: pd.DataFrame, periods: List[int] = [5, 20]) -> pd.DataFrame:
        """
        计算移动平均线
        
        Args:
            df: K线DataFrame
            periods: 计算周期列表
            
        Returns:
            包含MA指标的DataFrame
        """
        if 'close' not in df.columns:
            return df
        
        for period in periods:
            if len(df) >= period:
                df[f'ma_{period}'] = df['close'].rolling(window=period).mean()
        
        return df
    
    def calculate_rsi(self, df: pd.DataFrame, period: int = 14) -> pd.DataFrame:
        """
        计算RSI指标
        
        Args:
            df: K线DataFrame
            period: 计算周期
            
        Returns:
            包含RSI指标的DataFrame
        """
        if 'close' not in df.columns or len(df) < period + 1:
            return df
        
        delta = df['close'].diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
        
        rs = gain / loss
        df['rsi'] = 100 - (100 / (1 + rs))
        
        return df
    
    def calculate_bollinger_bands(self, df: pd.DataFrame, period: int = 20, std_dev: int = 2) -> pd.DataFrame:
        """
        计算布林带指标
        
        Args:
            df: K线DataFrame
            period: 计算周期
            std_dev: 标准差倍数
            
        Returns:
            包含布林带指标的DataFrame
        """
        if 'close' not in df.columns or len(df) < period:
            return df
        
        # 中轨（移动平均线）
        df['bb_middle'] = df['close'].rolling(window=period).mean()
        
        # 标准差
        rolling_std = df['close'].rolling(window=period).std()
        
        # 上轨和下轨
        df['bb_upper'] = df['bb_middle'] + (rolling_std * std_dev)
        df['bb_lower'] = df['bb_middle'] - (rolling_std * std_dev)
        
        # 带宽
        df['bb_width'] = (df['bb_upper'] - df['bb_lower']) / df['bb_middle']
        
        return df
    
    def calculate_indicators(self, kline_data: List[Dict[str, Any]], 
                           indicators: Optional[List[str]] = None) -> pd.DataFrame:
        """
        计算所有技术指标
        
        Args:
            kline_data: K线数据列表
            indicators: 要计算的指标列表，如果为None则计算所有
            
        Returns:
            包含技术指标的DataFrame
        """
        # 清洗数据
        df = self.clean_kline_data(kline_data)
        
        if df.empty:
            return df
        
        # 默认计算所有指标（包括MA）
        if indicators is None:
            indicators = ['MACD', 'RSI', 'BB', 'MA']
        
        # 计算MA（必须在其他指标之前，因为其他指标可能依赖MA）
        if 'MA' in indicators:
            df = self.calculate_ma(df, periods=[5, 20, 60])  # 增加60日均线
        
        # 计算MACD
        if 'MACD' in indicators:
            df = self.calculate_macd(df)
        
        # 计算RSI
        if 'RSI' in indicators:
            df = self.calculate_rsi(df)
        
        # 计算布林带
        if 'BB' in indicators:
            df = self.calculate_bollinger_bands(df)
        
        # 计算成交量指标（量价关系）
        if len(df) > 0 and 'volume' in df.columns:
            # 成交量移动平均
            df['volume_ma_5'] = df['volume'].rolling(window=5).mean()
            df['volume_ma_20'] = df['volume'].rolling(window=20).mean()
            # 量价比率
            if 'ma_20' in df.columns:
                df['volume_price_ratio'] = df['volume'] / df['ma_20'] if df['ma_20'].iloc[-1] > 0 else 0
        
        # 计算KDJ指标（随机指标，超买超卖）
        if 'KDJ' in indicators or indicators is None:
            df = self.calculate_kdj(df)
        
        # 计算CCI指标（商品通道指标）
        if 'CCI' in indicators or indicators is None:
            df = self.calculate_cci(df)
        
        # 计算OBV指标（能量潮指标）
        if 'OBV' in indicators or indicators is None:
            df = self.calculate_obv(df)
        
        # 计算ATR指标（平均真实波幅）
        if 'ATR' in indicators or indicators is None:
            df = self.calculate_atr(df)
        
        # 计算ADX指标（平均趋向指标，趋势强度）
        if 'ADX' in indicators or indicators is None:
            df = self.calculate_adx(df)
        
        # 计算EMA（指数移动平均）
        if 'EMA' in indicators or indicators is None:
            df['ema_12'] = df['close'].ewm(span=12, adjust=False).mean()
            df['ema_26'] = df['close'].ewm(span=26, adjust=False).mean()
            df['ema_50'] = df['close'].ewm(span=50, adjust=False).mean()
        
        # 计算价格动量
        if len(df) > 0:
            df['momentum'] = df['close'].pct_change(periods=10)  # 10周期动量
            df['price_change'] = df['close'].pct_change(periods=1)  # 单周期变化
            df['volatility'] = df['close'].rolling(window=20).std() / df['close'].rolling(window=20).mean()  # 波动率
        
        # 记录计算出的指标
        if not df.empty:
            latest_indicators = df.iloc[-1].to_dict()
            
            # 提取关键指标
            indicator_summary = {}
            if 'macd' in latest_indicators:
                indicator_summary['MACD'] = latest_indicators.get('macd', 'N/A')
                indicator_summary['MACD_Signal'] = latest_indicators.get('macd_signal', 'N/A')
                indicator_summary['MACD_Hist'] = latest_indicators.get('macd_hist', 'N/A')
            if 'rsi' in latest_indicators:
                indicator_summary['RSI'] = latest_indicators.get('rsi', 'N/A')
            if 'bb_upper' in latest_indicators:
                indicator_summary['BB_Upper'] = latest_indicators.get('bb_upper', 'N/A')
                indicator_summary['BB_Middle'] = latest_indicators.get('bb_middle', 'N/A')
                indicator_summary['BB_Lower'] = latest_indicators.get('bb_lower', 'N/A')
                indicator_summary['BB_Width'] = latest_indicators.get('bb_width', 'N/A')
            if 'kdj_k' in latest_indicators:
                indicator_summary['KDJ_K'] = latest_indicators.get('kdj_k', 'N/A')
                indicator_summary['KDJ_D'] = latest_indicators.get('kdj_d', 'N/A')
                indicator_summary['KDJ_J'] = latest_indicators.get('kdj_j', 'N/A')
            if 'cci' in latest_indicators:
                indicator_summary['CCI'] = latest_indicators.get('cci', 'N/A')
            if 'obv' in latest_indicators:
                indicator_summary['OBV'] = latest_indicators.get('obv', 'N/A')
            if 'atr' in latest_indicators:
                indicator_summary['ATR'] = latest_indicators.get('atr', 'N/A')
                indicator_summary['ATR_Pct'] = latest_indicators.get('atr_pct', 'N/A')
            if 'adx' in latest_indicators:
                indicator_summary['ADX'] = latest_indicators.get('adx', 'N/A')
                indicator_summary['Plus_DI'] = latest_indicators.get('plus_di', 'N/A')
                indicator_summary['Minus_DI'] = latest_indicators.get('minus_di', 'N/A')
            if 'volatility' in latest_indicators:
                indicator_summary['Volatility'] = latest_indicators.get('volatility', 'N/A')
            if 'momentum' in latest_indicators:
                indicator_summary['Momentum'] = latest_indicators.get('momentum', 'N/A')
            
            # 记录指标摘要
            if indicator_summary:
                summary_str = ' | '.join([f"{k}: {v:.4f}" if isinstance(v, (int, float)) else f"{k}: {v}" 
                                         for k, v in indicator_summary.items()])
                self.logger.info(f"[技术指标] 计算完成 | {summary_str}")
            
            # 记录完整指标详情（DEBUG级别）
            self.logger.debug(f"[技术指标详情] 完整指标数据: {latest_indicators}")
        
        return df
    
    def calculate_kdj(self, df: pd.DataFrame, n: int = 9, m1: int = 3, m2: int = 3) -> pd.DataFrame:
        """
        计算KDJ指标（随机指标）
        
        Args:
            df: K线DataFrame
            n: RSV周期
            m1: K值平滑周期
            m2: D值平滑周期
            
        Returns:
            包含KDJ指标的DataFrame
        """
        if 'close' not in df.columns or 'high' not in df.columns or 'low' not in df.columns:
            return df
        if len(df) < n:
            return df
        
        # 计算RSV（未成熟随机值）
        low_n = df['low'].rolling(window=n).min()
        high_n = df['high'].rolling(window=n).max()
        rsv = (df['close'] - low_n) / (high_n - low_n) * 100
        rsv = rsv.fillna(50)  # 填充NaN为50
        
        # 计算K值（快速随机指标）
        df['kdj_k'] = rsv.ewm(alpha=1/m1, adjust=False).mean()
        
        # 计算D值（慢速随机指标）
        df['kdj_d'] = df['kdj_k'].ewm(alpha=1/m2, adjust=False).mean()
        
        # 计算J值（J=3K-2D）
        df['kdj_j'] = 3 * df['kdj_k'] - 2 * df['kdj_d']
        
        return df
    
    def calculate_cci(self, df: pd.DataFrame, period: int = 20) -> pd.DataFrame:
        """
        计算CCI指标（商品通道指标）
        
        Args:
            df: K线DataFrame
            period: 计算周期
            
        Returns:
            包含CCI指标的DataFrame
        """
        if 'close' not in df.columns or 'high' not in df.columns or 'low' not in df.columns:
            return df
        if len(df) < period:
            return df
        
        # 计算典型价格（TP）
        tp = (df['high'] + df['low'] + df['close']) / 3
        
        # 计算移动平均
        sma = tp.rolling(window=period).mean()
        
        # 计算平均偏差
        mad = tp.rolling(window=period).apply(lambda x: np.abs(x - x.mean()).mean())
        
        # 计算CCI
        df['cci'] = (tp - sma) / (0.015 * mad)
        df['cci'] = df['cci'].fillna(0)
        
        return df
    
    def calculate_obv(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        计算OBV指标（能量潮指标）
        
        Args:
            df: K线DataFrame
            
        Returns:
            包含OBV指标的DataFrame
        """
        if 'close' not in df.columns or 'volume' not in df.columns:
            return df
        
        # 计算价格变化方向
        price_change = df['close'].diff()
        
        # 计算OBV
        obv = (np.sign(price_change) * df['volume']).fillna(0).cumsum()
        df['obv'] = obv
        
        # OBV移动平均
        df['obv_ma'] = df['obv'].rolling(window=20).mean()
        
        return df
    
    def calculate_atr(self, df: pd.DataFrame, period: int = 14) -> pd.DataFrame:
        """
        计算ATR指标（平均真实波幅）
        
        Args:
            df: K线DataFrame
            period: 计算周期
            
        Returns:
            包含ATR指标的DataFrame
        """
        if 'close' not in df.columns or 'high' not in df.columns or 'low' not in df.columns:
            return df
        if len(df) < period + 1:
            return df
        
        # 计算真实波幅（TR）
        high_low = df['high'] - df['low']
        high_close = np.abs(df['high'] - df['close'].shift())
        low_close = np.abs(df['low'] - df['close'].shift())
        
        tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
        
        # 计算ATR（TR的移动平均）
        df['atr'] = tr.rolling(window=period).mean()
        df['atr_pct'] = (df['atr'] / df['close']) * 100  # ATR百分比
        
        return df
    
    def calculate_adx(self, df: pd.DataFrame, period: int = 14) -> pd.DataFrame:
        """
        计算ADX指标（平均趋向指标）
        
        Args:
            df: K线DataFrame
            period: 计算周期
            
        Returns:
            包含ADX指标的DataFrame
        """
        if 'close' not in df.columns or 'high' not in df.columns or 'low' not in df.columns:
            return df
        if len(df) < period * 2:
            return df
        
        # 计算+DM和-DM
        high_diff = df['high'].diff()
        low_diff = -df['low'].diff()
        
        plus_dm = high_diff.where((high_diff > low_diff) & (high_diff > 0), 0)
        minus_dm = low_diff.where((low_diff > high_diff) & (low_diff > 0), 0)
        
        # 计算TR（真实波幅）
        high_low = df['high'] - df['low']
        high_close = np.abs(df['high'] - df['close'].shift())
        low_close = np.abs(df['low'] - df['close'].shift())
        tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
        
        # 平滑处理
        atr = tr.rolling(window=period).mean()
        plus_di = 100 * (plus_dm.rolling(window=period).mean() / atr)
        minus_di = 100 * (minus_dm.rolling(window=period).mean() / atr)
        
        # 计算DX
        dx = 100 * np.abs(plus_di - minus_di) / (plus_di + minus_di)
        dx = dx.fillna(0)
        
        # 计算ADX（DX的移动平均）
        df['adx'] = dx.rolling(window=period).mean()
        df['plus_di'] = plus_di
        df['minus_di'] = minus_di
        
        return df
    
    def calculate_volatility(self, prices: pd.Series, window: int = 20) -> pd.Series:
        """
        计算波动率
        
        Args:
            prices: 价格序列
            window: 窗口大小
            
        Returns:
            波动率序列
        """
        returns = prices.pct_change()
        volatility = returns.rolling(window=window).std() * np.sqrt(252)  # 年化波动率
        return volatility
    
    def detect_anomalies(self, df: pd.DataFrame, column: str, 
                        method: str = 'zscore', threshold: float = 3.0) -> pd.Series:
        """
        检测异常值
        
        Args:
            df: 数据DataFrame
            column: 要检测的列名
            method: 检测方法（zscore, iqr）
            threshold: 阈值
            
        Returns:
            布尔序列，True表示异常值
        """
        if column not in df.columns:
            return pd.Series(False, index=df.index)
        
        if method == 'zscore':
            z_scores = np.abs((df[column] - df[column].mean()) / df[column].std())
            return z_scores > threshold
        elif method == 'iqr':
            Q1 = df[column].quantile(0.25)
            Q3 = df[column].quantile(0.75)
            IQR = Q3 - Q1
            lower_bound = Q1 - 1.5 * IQR
            upper_bound = Q3 + 1.5 * IQR
            return (df[column] < lower_bound) | (df[column] > upper_bound)
        else:
            raise ValueError(f"不支持的检测方法: {method}")


if __name__ == "__main__":
    # 测试数据处理器
    processor = DataProcessor()
    
    # 模拟K线数据
    sample_kline = [
        {'timestamp': i * 3600000, 'open': 50000 + i * 10, 'high': 50100 + i * 10,
         'low': 49900 + i * 10, 'close': 50050 + i * 10, 'volume': 1000 + i * 100}
        for i in range(100)
    ]
    
    print("计算技术指标...")
    df = processor.calculate_indicators(sample_kline)
    
    if not df.empty:
        print(f"\n数据行数: {len(df)}")
        print(f"最新收盘价: {df['close'].iloc[-1]}")
        print(f"最新MACD: {df['macd'].iloc[-1]:.2f}")
        print(f"最新RSI: {df['rsi'].iloc[-1]:.2f}")

