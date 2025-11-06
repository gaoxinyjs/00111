#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
交易结果记录器
记录每次交易的决策过程、结果和盈亏情况
"""

import json
import os
from typing import Dict, List, Optional, Any
from datetime import datetime
from ..core.logger import get_logger
from ..core.config_manager import get_config_manager


class TradeResultRecorder:
    """交易结果记录器"""
    
    def __init__(self):
        """初始化交易结果记录器"""
        self.logger = get_logger("trade_result_recorder")
        self.config_mgr = get_config_manager()
        
        # 获取数据目录（安全获取配置，如果不存在则使用默认值）
        try:
            system_config = self.config_mgr.get_config('system')
            data_dir = system_config.get('data_dir', 'data') if system_config else 'data'
        except (KeyError, TypeError):
            data_dir = 'data'
        
        self.results_dir = os.path.join(data_dir, 'trade_results')
        os.makedirs(self.results_dir, exist_ok=True)
        
        # 当前会话的交易记录
        self.current_session_records: List[Dict[str, Any]] = []
        
        # 统计信息
        self.stats = {
            'total_trades': 0,
            'profitable_trades': 0,
            'loss_trades': 0,
            'total_profit_pct': 0.0,
            'win_rate': 0.0
        }
    
    def record_trade_decision(self, symbol: str, decision: Dict[str, Any],
                              ai_analysis: Dict[str, Any],
                              market_data: Dict[str, Any]) -> str:
        """
        记录交易决策
        
        Args:
            symbol: 交易对
            decision: 交易决策（包含action, size等）
            ai_analysis: AI分析结果（DeepSeek的分析）
            market_data: 市场数据
        
        Returns:
            记录ID
        """
        record_id = f"{symbol}_{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}"
        
        record = {
            'record_id': record_id,
            'timestamp': datetime.now().isoformat(),
            'symbol': symbol,
            'decision': {
                'action': decision.get('action', 'unknown'),
                'position_size': decision.get('position_size', 0),
                'entry_price': decision.get('entry_price', 0),
                'confidence': decision.get('confidence', 0),
            },
            'ai_analysis': {
                'recommendation': ai_analysis.get('recommendation', 'unknown'),
                'confidence': ai_analysis.get('confidence', 0),
                'trend': ai_analysis.get('trend', 'unknown'),
                'technical_signal': ai_analysis.get('technical_signal', 'unknown'),
                'reasoning': ai_analysis.get('reasoning', ''),
                'key_factors': ai_analysis.get('key_factors', []),
                'volume_price_analysis': ai_analysis.get('volume_price_analysis', ''),
                'market_maker_intent': ai_analysis.get('market_maker_intent', ''),
            },
            'market_conditions': {
                'price': market_data.get('price', 0),
                'change_24h': market_data.get('change_24h', 0),
                'indicators': market_data.get('indicators', {}),
                'multi_timeframe': market_data.get('multi_timeframe', {}),
            },
            'status': 'open',  # open, closed, cancelled
            'result': None  # 将在平仓时更新
        }
        
        self.current_session_records.append(record)
        
        # 保存到文件
        self._save_record(record)
        
        self.logger.info(f"[交易记录] 记录ID: {record_id}, 交易对: {symbol}, 操作: {decision.get('action')}")
        
        return record_id
    
    def record_trade_result(self, record_id: str, exit_price: float,
                           profit_pct: float, holding_duration_hours: float,
                           exit_reason: str) -> bool:
        """
        记录交易结果（平仓时调用）
        
        Args:
            record_id: 记录ID
            exit_price: 平仓价格
            profit_pct: 盈亏百分比
            holding_duration_hours: 持仓时长（小时）
            exit_reason: 平仓原因
        
        Returns:
            是否成功记录
        """
        # 查找记录
        record = self._load_record(record_id)
        if not record:
            self.logger.warning(f"[交易记录] 找不到记录ID: {record_id}")
            return False
        
        # 更新结果
        record['status'] = 'closed'
        record['result'] = {
            'exit_price': exit_price,
            'entry_price': record['decision'].get('entry_price', 0),
            'profit_pct': profit_pct,
            'holding_duration_hours': holding_duration_hours,
            'exit_reason': exit_reason,
            'exit_timestamp': datetime.now().isoformat(),
            'is_profitable': profit_pct > 0
        }
        
        # 更新统计
        self._update_stats(profit_pct)
        
        # 保存更新后的记录
        self._save_record(record)
        
        # 更新会话记录
        for i, r in enumerate(self.current_session_records):
            if r.get('record_id') == record_id:
                self.current_session_records[i] = record
                break
        
        self.logger.info(
            f"[交易结果] 记录ID: {record_id}, 盈亏: {profit_pct:.2f}%, "
            f"持仓时长: {holding_duration_hours:.2f}小时, 原因: {exit_reason}"
        )
        
        return True
    
    def get_recent_results(self, limit: int = 50) -> List[Dict[str, Any]]:
        """
        获取最近的交易结果
        
        Args:
            limit: 返回数量限制
        
        Returns:
            交易结果列表
        """
        # 加载所有记录
        all_records = self._load_all_records()
        
        # 只返回已平仓的记录
        closed_records = [r for r in all_records if r.get('status') == 'closed']
        
        # 按时间排序
        closed_records.sort(key=lambda x: x.get('result', {}).get('exit_timestamp', ''), reverse=True)
        
        return closed_records[:limit]
    
    def get_performance_stats(self) -> Dict[str, Any]:
        """
        获取交易表现统计
        
        Returns:
            统计信息
        """
        recent_results = self.get_recent_results(limit=100)
        
        if not recent_results:
            return self.stats
        
        # 重新计算统计
        total = len(recent_results)
        profitable = sum(1 for r in recent_results if r.get('result', {}).get('is_profitable', False))
        loss = total - profitable
        total_profit = sum(r.get('result', {}).get('profit_pct', 0) for r in recent_results)
        
        self.stats = {
            'total_trades': total,
            'profitable_trades': profitable,
            'loss_trades': loss,
            'total_profit_pct': total_profit,
            'win_rate': (profitable / total * 100) if total > 0 else 0.0,
            'avg_profit_pct': (total_profit / total) if total > 0 else 0.0,
            'avg_holding_hours': (
                sum(r.get('result', {}).get('holding_duration_hours', 0) for r in recent_results) / total
            ) if total > 0 else 0.0
        }
        
        return self.stats
    
    def analyze_success_patterns(self, limit: int = 50) -> Dict[str, Any]:
        """
        分析成功交易的模式
        
        Args:
            limit: 分析最近N笔交易
        
        Returns:
            成功模式分析
        """
        recent_results = self.get_recent_results(limit=limit)
        
        profitable = [r for r in recent_results if r.get('result', {}).get('is_profitable', False)]
        losses = [r for r in recent_results if not r.get('result', {}).get('is_profitable', False)]
        
        if not profitable and not losses:
            return {'message': '数据不足，无法分析'}
        
        # 分析盈利交易的共同特征
        profitable_patterns = {
            'common_recommendations': {},
            'common_technical_signals': {},
            'common_trends': {},
            'avg_confidence': 0.0,
            'common_key_factors': {}
        }
        
        if profitable:
            # 统计推荐类型
            for r in profitable:
                rec = r.get('ai_analysis', {}).get('recommendation', 'unknown')
                profitable_patterns['common_recommendations'][rec] = \
                    profitable_patterns['common_recommendations'].get(rec, 0) + 1
            
            # 统计技术信号
            for r in profitable:
                sig = r.get('ai_analysis', {}).get('technical_signal', 'unknown')
                profitable_patterns['common_technical_signals'][sig] = \
                    profitable_patterns['common_technical_signals'].get(sig, 0) + 1
            
            # 统计趋势
            for r in profitable:
                trend = r.get('ai_analysis', {}).get('trend', 'unknown')
                profitable_patterns['common_trends'][trend] = \
                    profitable_patterns['common_trends'].get(trend, 0) + 1
            
            # 平均信心度
            confidences = [r.get('ai_analysis', {}).get('confidence', 0) for r in profitable]
            profitable_patterns['avg_confidence'] = sum(confidences) / len(confidences) if confidences else 0
            
            # 关键因素
            for r in profitable:
                factors = r.get('ai_analysis', {}).get('key_factors', [])
                for factor in factors:
                    profitable_patterns['common_key_factors'][factor] = \
                        profitable_patterns['common_key_factors'].get(factor, 0) + 1
        
        # 分析亏损交易的共同特征
        loss_patterns = {
            'common_recommendations': {},
            'common_technical_signals': {},
            'common_trends': {},
            'avg_confidence': 0.0,
            'common_key_factors': {}
        }
        
        if losses:
            for r in losses:
                rec = r.get('ai_analysis', {}).get('recommendation', 'unknown')
                loss_patterns['common_recommendations'][rec] = \
                    loss_patterns['common_recommendations'].get(rec, 0) + 1
            
            for r in losses:
                sig = r.get('ai_analysis', {}).get('technical_signal', 'unknown')
                loss_patterns['common_technical_signals'][sig] = \
                    loss_patterns['common_technical_signals'].get(sig, 0) + 1
            
            for r in losses:
                trend = r.get('ai_analysis', {}).get('trend', 'unknown')
                loss_patterns['common_trends'][trend] = \
                    loss_patterns['common_trends'].get(trend, 0) + 1
            
            confidences = [r.get('ai_analysis', {}).get('confidence', 0) for r in losses]
            loss_patterns['avg_confidence'] = sum(confidences) / len(confidences) if confidences else 0
            
            for r in losses:
                factors = r.get('ai_analysis', {}).get('key_factors', [])
                for factor in factors:
                    loss_patterns['common_key_factors'][factor] = \
                        loss_patterns['common_key_factors'].get(factor, 0) + 1
        
        return {
            'profitable_patterns': profitable_patterns,
            'loss_patterns': loss_patterns,
            'profitability_by_recommendation': self._analyze_by_recommendation(recent_results),
            'profitability_by_confidence': self._analyze_by_confidence(recent_results)
        }
    
    def _analyze_by_recommendation(self, results: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
        """按推荐类型分析盈利率"""
        by_rec = {}
        
        for r in results:
            rec = r.get('ai_analysis', {}).get('recommendation', 'unknown')
            if rec not in by_rec:
                by_rec[rec] = {'total': 0, 'profitable': 0, 'total_profit': 0.0}
            
            by_rec[rec]['total'] += 1
            if r.get('result', {}).get('is_profitable', False):
                by_rec[rec]['profitable'] += 1
            by_rec[rec]['total_profit'] += r.get('result', {}).get('profit_pct', 0)
        
        # 计算盈利率
        for rec in by_rec:
            stats = by_rec[rec]
            stats['win_rate'] = (stats['profitable'] / stats['total'] * 100) if stats['total'] > 0 else 0
            stats['avg_profit'] = stats['total_profit'] / stats['total'] if stats['total'] > 0 else 0
        
        return by_rec
    
    def _analyze_by_confidence(self, results: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
        """按信心度区间分析盈利率"""
        by_conf = {
            'high': {'min': 0.7, 'total': 0, 'profitable': 0, 'total_profit': 0.0},
            'medium': {'min': 0.5, 'max': 0.7, 'total': 0, 'profitable': 0, 'total_profit': 0.0},
            'low': {'max': 0.5, 'total': 0, 'profitable': 0, 'total_profit': 0.0}
        }
        
        for r in results:
            conf = r.get('ai_analysis', {}).get('confidence', 0)
            profit_pct = r.get('result', {}).get('profit_pct', 0)
            is_profitable = r.get('result', {}).get('is_profitable', False)
            
            if conf >= 0.7:
                by_conf['high']['total'] += 1
                if is_profitable:
                    by_conf['high']['profitable'] += 1
                by_conf['high']['total_profit'] += profit_pct
            elif conf >= 0.5:
                by_conf['medium']['total'] += 1
                if is_profitable:
                    by_conf['medium']['profitable'] += 1
                by_conf['medium']['total_profit'] += profit_pct
            else:
                by_conf['low']['total'] += 1
                if is_profitable:
                    by_conf['low']['profitable'] += 1
                by_conf['low']['total_profit'] += profit_pct
        
        # 计算盈利率
        for level in by_conf:
            stats = by_conf[level]
            stats['win_rate'] = (stats['profitable'] / stats['total'] * 100) if stats['total'] > 0 else 0
            stats['avg_profit'] = stats['total_profit'] / stats['total'] if stats['total'] > 0 else 0
        
        return by_conf
    
    def _serialize_for_json(self, obj: Any) -> Any:
        """
        递归处理对象，将不可序列化的类型转换为可序列化的类型
        
        Args:
            obj: 要处理的对象
            
        Returns:
            可序列化的对象
        """
        import pandas as pd
        import numpy as np
        
        if isinstance(obj, pd.Timestamp):
            # pandas Timestamp转换为ISO格式字符串
            return obj.isoformat()
        elif isinstance(obj, (pd.Series, pd.DataFrame)):
            # pandas Series/DataFrame转换为字典或列表
            return obj.to_dict()
        elif isinstance(obj, np.integer):
            # numpy整数类型
            return int(obj)
        elif isinstance(obj, np.floating):
            # numpy浮点数类型
            return float(obj)
        elif isinstance(obj, np.ndarray):
            # numpy数组转换为列表
            return obj.tolist()
        elif isinstance(obj, datetime):
            # datetime对象转换为ISO格式字符串
            return obj.isoformat()
        elif isinstance(obj, dict):
            # 字典递归处理
            return {k: self._serialize_for_json(v) for k, v in obj.items()}
        elif isinstance(obj, (list, tuple)):
            # 列表或元组递归处理
            return [self._serialize_for_json(item) for item in obj]
        elif isinstance(obj, (str, int, float, bool, type(None))):
            # 基本类型直接返回
            return obj
        else:
            # 其他类型尝试转换为字符串
            try:
                return str(obj)
            except Exception:
                return None
    
    def _save_record(self, record: Dict[str, Any]):
        """保存记录到文件"""
        record_id = record.get('record_id', 'unknown')
        filepath = os.path.join(self.results_dir, f"{record_id}.json")
        
        try:
            # 先序列化record，确保所有对象都可以JSON序列化
            serialized_record = self._serialize_for_json(record)
            with open(filepath, 'w', encoding='utf-8') as f:
                json.dump(serialized_record, f, ensure_ascii=False, indent=2)
        except Exception as e:
            self.logger.error(f"保存交易记录失败: {e}", exc_info=True)
    
    def _load_record(self, record_id: str) -> Optional[Dict[str, Any]]:
        """加载单个记录"""
        filepath = os.path.join(self.results_dir, f"{record_id}.json")
        
        if not os.path.exists(filepath):
            return None
        
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            self.logger.error(f"加载交易记录失败: {e}")
            return None
    
    def _load_all_records(self) -> List[Dict[str, Any]]:
        """加载所有记录"""
        records = []
        
        if not os.path.exists(self.results_dir):
            return records
        
        try:
            for filename in os.listdir(self.results_dir):
                if filename.endswith('.json'):
                    filepath = os.path.join(self.results_dir, filename)
                    with open(filepath, 'r', encoding='utf-8') as f:
                        record = json.load(f)
                        records.append(record)
        except Exception as e:
            self.logger.error(f"加载所有交易记录失败: {e}")
        
        return records
    
    def _update_stats(self, profit_pct: float):
        """更新统计信息"""
        self.stats['total_trades'] += 1
        if profit_pct > 0:
            self.stats['profitable_trades'] += 1
        else:
            self.stats['loss_trades'] += 1
        
        self.stats['total_profit_pct'] += profit_pct
        if self.stats['total_trades'] > 0:
            self.stats['win_rate'] = (
                self.stats['profitable_trades'] / self.stats['total_trades'] * 100
            )

