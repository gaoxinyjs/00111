#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
提示词优化器
根据历史交易结果分析成功/失败原因，自动优化提示词
"""

import json
import os
from typing import Dict, List, Optional, Any
from datetime import datetime
from ..core.logger import get_logger
from ..core.config_manager import get_config_manager
from .trade_result_recorder import TradeResultRecorder


class PromptOptimizer:
    """提示词优化器"""
    
    def __init__(self):
        """初始化提示词优化器"""
        self.logger = get_logger("prompt_optimizer")
        self.config_mgr = get_config_manager()
        self.result_recorder = TradeResultRecorder()
        
        # 获取数据目录（安全获取配置，如果不存在则使用默认值）
        try:
            system_config = self.config_mgr.get_config('system')
            data_dir = system_config.get('data_dir', 'data') if system_config else 'data'
        except (KeyError, TypeError):
            data_dir = 'data'
        
        self.prompts_dir = os.path.join(data_dir, 'optimized_prompts')
        os.makedirs(self.prompts_dir, exist_ok=True)
        
        # 当前提示词版本
        self.current_version = 1
        self.prompt_history: List[Dict[str, Any]] = []
    
    def optimize_prompt(self, min_trades: int = 10) -> Optional[Dict[str, Any]]:
        """
        根据交易结果优化提示词
        
        Args:
            min_trades: 最少需要多少笔交易才开始优化
        
        Returns:
            优化后的提示词配置，如果数据不足则返回None
        """
        # 获取交易结果统计
        stats = self.result_recorder.get_performance_stats()
        
        if stats['total_trades'] < min_trades:
            self.logger.info(
                f"[提示词优化] 交易数量不足({stats['total_trades']}/{min_trades})，暂不优化"
            )
            return None
        
        # 分析成功模式
        patterns = self.result_recorder.analyze_success_patterns(limit=100)
        
        # 生成优化建议
        optimizations = self._generate_optimizations(patterns, stats)
        
        if not optimizations:
            self.logger.info("[提示词优化] 未找到需要优化的地方")
            return None
        
        # 应用优化
        optimized_prompt = self._apply_optimizations(optimizations)
        
        # 保存优化后的提示词
        self._save_optimized_prompt(optimized_prompt)
        
        self.logger.info(f"[提示词优化] 优化完成，版本: {self.current_version}")
        
        return optimized_prompt
    
    def _generate_optimizations(self, patterns: Dict[str, Any],
                               stats: Dict[str, Any]) -> Dict[str, Any]:
        """
        生成优化建议
        
        Args:
            patterns: 成功模式分析
            stats: 交易统计
        
        Returns:
            优化建议
        """
        optimizations = {
            'confidence_threshold': None,
            'emphasis_factors': [],
            'deemphasis_factors': [],
            'recommendation_adjustments': {},
            'reasoning_guidelines': []
        }
        
        # 1. 分析信心度阈值
        profitability_by_confidence = patterns.get('profitability_by_confidence', {})
        
        high_conf = profitability_by_confidence.get('high', {})
        medium_conf = profitability_by_confidence.get('medium', {})
        low_conf = profitability_by_confidence.get('low', {})
        
        # 如果高信心度交易盈利率明显更高，提高阈值
        if (high_conf.get('total', 0) > 5 and 
            high_conf.get('win_rate', 0) > medium_conf.get('win_rate', 0) + 10):
            optimizations['confidence_threshold'] = 0.7
            optimizations['reasoning_guidelines'].append(
                "提高信心度要求：只有高信心度(>=0.7)的交易才执行"
            )
        elif (medium_conf.get('total', 0) > 5 and 
              medium_conf.get('win_rate', 0) > low_conf.get('win_rate', 0) + 10):
            optimizations['confidence_threshold'] = 0.5
            optimizations['reasoning_guidelines'].append(
                "提高信心度要求：只有中等以上信心度(>=0.5)的交易才执行"
            )
        
        # 2. 分析推荐类型的成功率
        profitability_by_rec = patterns.get('profitability_by_recommendation', {})
        
        profitable_recs = []
        unprofitable_recs = []
        
        for rec, rec_stats in profitability_by_rec.items():
            win_rate = rec_stats.get('win_rate', 0)
            total = rec_stats.get('total', 0)
            
            if total >= 3:  # 至少3笔交易才统计
                if win_rate >= 60:
                    profitable_recs.append(rec)
                    optimizations['recommendation_adjustments'][rec] = {
                        'weight': 1.2,  # 增加权重
                        'message': f"{rec}类型交易成功率{win_rate:.1f}%，给予更高权重"
                    }
                elif win_rate <= 40:
                    unprofitable_recs.append(rec)
                    optimizations['recommendation_adjustments'][rec] = {
                        'weight': 0.8,  # 降低权重
                        'message': f"{rec}类型交易成功率{win_rate:.1f}%，给予较低权重"
                    }
        
        # 3. 分析关键因素
        profitable_patterns = patterns.get('profitable_patterns', {})
        loss_patterns = patterns.get('loss_patterns', {})
        
        profitable_factors = profitable_patterns.get('common_key_factors', {})
        loss_factors = loss_patterns.get('common_key_factors', {})
        
        # 找出成功交易中经常出现但亏损交易中少出现的因素
        for factor, count in profitable_factors.items():
            loss_count = loss_factors.get(factor, 0)
            total_profitable = sum(profitable_factors.values())
            total_loss = sum(loss_factors.values())
            
            if total_profitable > 0 and total_loss > 0:
                prof_ratio = count / total_profitable
                loss_ratio = loss_count / total_loss if total_loss > 0 else 0
                
                if prof_ratio > loss_ratio * 1.5:  # 盈利交易中出现频率明显更高
                    optimizations['emphasis_factors'].append({
                        'factor': factor,
                        'reason': f"成功交易中经常出现(占比{prof_ratio:.1%}，亏损交易中{loss_ratio:.1%})"
                    })
        
        # 找出亏损交易中经常出现但成功交易中少出现的因素
        for factor, count in loss_factors.items():
            prof_count = profitable_factors.get(factor, 0)
            total_profitable = sum(profitable_factors.values())
            total_loss = sum(loss_factors.values())
            
            if total_profitable > 0 and total_loss > 0:
                prof_ratio = prof_count / total_profitable if total_profitable > 0 else 0
                loss_ratio = count / total_loss
                
                if loss_ratio > prof_ratio * 1.5:  # 亏损交易中出现频率明显更高
                    optimizations['deemphasis_factors'].append({
                        'factor': factor,
                        'reason': f"亏损交易中经常出现(占比{loss_ratio:.1%}，成功交易中{prof_ratio:.1%})，需要谨慎"
                    })
        
        # 4. 分析技术信号
        profitable_signals = profitable_patterns.get('common_technical_signals', {})
        loss_signals = loss_patterns.get('common_technical_signals', {})
        
        # 找出成功交易中常见的信号
        for signal, count in profitable_signals.items():
            loss_count = loss_signals.get(signal, 0)
            total_profitable_sig = sum(profitable_signals.values())
            total_loss_sig = sum(loss_signals.values())
            
            if total_profitable_sig > 0 and total_loss_sig > 0:
                prof_ratio = count / total_profitable_sig
                loss_ratio = loss_count / total_loss_sig if total_loss_sig > 0 else 0
                
                if prof_ratio > loss_ratio * 1.5:
                    optimizations['emphasis_factors'].append({
                        'factor': f"技术信号:{signal}",
                        'reason': f"成功交易中常见信号(出现{prof_ratio:.1%})"
                    })
        
        # 5. 分析趋势
        profitable_trends = profitable_patterns.get('common_trends', {})
        loss_trends = loss_patterns.get('common_trends', {})
        
        for trend, count in profitable_trends.items():
            loss_count = loss_trends.get(trend, 0)
            total_profitable_trend = sum(profitable_trends.values())
            total_loss_trend = sum(loss_trends.values())
            
            if total_profitable_trend > 0 and total_loss_trend > 0:
                prof_ratio = count / total_profitable_trend
                loss_ratio = loss_count / total_loss_trend if total_loss_trend > 0 else 0
                
                if prof_ratio > loss_ratio * 1.5:
                    optimizations['emphasis_factors'].append({
                        'factor': f"趋势:{trend}",
                        'reason': f"成功交易中常见趋势(出现{prof_ratio:.1%})"
                    })
        
        return optimizations
    
    def _apply_optimizations(self, optimizations: Dict[str, Any]) -> Dict[str, Any]:
        """
        应用优化建议，生成优化后的提示词配置
        
        Args:
            optimizations: 优化建议
        
        Returns:
            优化后的提示词配置
        """
        self.current_version += 1
        
        optimized_prompt = {
            'version': self.current_version,
            'created_at': datetime.now().isoformat(),
            'optimizations_applied': optimizations,
            'guidelines': []
        }
        
        # 生成优化指导原则
        guidelines = []
        
        # 信心度阈值
        if optimizations.get('confidence_threshold'):
            threshold = optimizations['confidence_threshold']
            guidelines.append({
                'type': 'confidence_threshold',
                'value': threshold,
                'instruction': f"只有当AI分析信心度 >= {threshold} 时才执行交易，低于此值的建议一律观望"
            })
        
        # 重点强调的因素
        if optimizations.get('emphasis_factors'):
            emphasis_list = [f.get('factor') for f in optimizations['emphasis_factors']]
            guidelines.append({
                'type': 'emphasis',
                'factors': emphasis_list,
                'instruction': f"在分析时重点考虑以下因素，这些因素在历史成功交易中出现频率高：{', '.join(emphasis_list)}"
            })
        
        # 需要谨慎的因素
        if optimizations.get('deemphasis_factors'):
            deemphasis_list = [f.get('factor') for f in optimizations['deemphasis_factors']]
            guidelines.append({
                'type': 'deemphasis',
                'factors': deemphasis_list,
                'instruction': f"对于以下因素需要更加谨慎，这些因素在历史亏损交易中出现频率高：{', '.join(deemphasis_list)}"
            })
        
        # 推荐类型调整
        if optimizations.get('recommendation_adjustments'):
            for rec, adj in optimizations['recommendation_adjustments'].items():
                weight = adj.get('weight', 1.0)
                if weight != 1.0:
                    guidelines.append({
                        'type': 'recommendation_weight',
                        'recommendation': rec,
                        'weight': weight,
                        'instruction': adj.get('message', '')
                    })
        
        # 其他指导原则
        if optimizations.get('reasoning_guidelines'):
            for guideline in optimizations['reasoning_guidelines']:
                guidelines.append({
                    'type': 'general',
                    'instruction': guideline
                })
        
        optimized_prompt['guidelines'] = guidelines
        
        return optimized_prompt
    
    def _save_optimized_prompt(self, optimized_prompt: Dict[str, Any]):
        """保存优化后的提示词"""
        version = optimized_prompt.get('version', self.current_version)
        filepath = os.path.join(self.prompts_dir, f"prompt_v{version}.json")
        
        try:
            with open(filepath, 'w', encoding='utf-8') as f:
                json.dump(optimized_prompt, f, ensure_ascii=False, indent=2)
            
            # 记录历史
            self.prompt_history.append(optimized_prompt.copy())
            
            self.logger.info(f"[提示词优化] 保存优化后提示词版本 {version}")
        except Exception as e:
            self.logger.error(f"保存优化后提示词失败: {e}")
    
    def get_current_guidelines(self) -> List[Dict[str, Any]]:
        """
        获取当前优化指导原则
        
        Returns:
            指导原则列表
        """
        if not self.prompt_history:
            # 加载最新的优化提示词
            self._load_latest_prompt()
        
        if not self.prompt_history:
            return []
        
        latest = self.prompt_history[-1]
        return latest.get('guidelines', [])
    
    def _load_latest_prompt(self):
        """加载最新的优化提示词"""
        if not os.path.exists(self.prompts_dir):
            return
        
        try:
            versions = []
            for filename in os.listdir(self.prompts_dir):
                if filename.startswith('prompt_v') and filename.endswith('.json'):
                    version_str = filename.replace('prompt_v', '').replace('.json', '')
                    try:
                        version = int(version_str)
                        versions.append((version, filename))
                    except ValueError:
                        continue
            
            if versions:
                # 加载最新版本
                latest_version, latest_filename = max(versions, key=lambda x: x[0])
                filepath = os.path.join(self.prompts_dir, latest_filename)
                
                with open(filepath, 'r', encoding='utf-8') as f:
                    prompt = json.load(f)
                    self.prompt_history = [prompt]
                    self.current_version = latest_version
                    
                    self.logger.info(f"[提示词优化] 加载提示词版本 {latest_version}")
        except Exception as e:
            self.logger.error(f"加载优化提示词失败: {e}")
    
    def get_optimization_summary(self) -> Dict[str, Any]:
        """
        获取优化摘要
        
        Returns:
            优化摘要信息
        """
        stats = self.result_recorder.get_performance_stats()
        guidelines = self.get_current_guidelines()
        
        return {
            'current_version': self.current_version,
            'total_optimizations': len(self.prompt_history),
            'performance_stats': stats,
            'active_guidelines_count': len(guidelines),
            'guidelines': guidelines
        }

