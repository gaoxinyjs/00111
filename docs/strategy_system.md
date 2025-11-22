# 策略系统说明

## 总览
- 调度循环：`StrategyRunner.run_cycle()`（15 分钟）与 `run_monitor_cycle()`（1 分钟）共同构成闭环。前者负责自研指标 + DeepSeek 融合与下单决策，后者在持仓期间高频监控，触发止盈/止损/AI 反转。
- 维护状态：通过 `StateStore (data/strategy_state.json)` 持久化 `active_position` 与 `last_signals`。系统重启后可恢复仓位。
- 配置入口：`config/strategy.yaml`（币种/周期/指标权重/DeepSeek 融合阈值/仓位档/风险参数）。

## 模块与职责
| 模块 | 说明 |
| --- | --- |
| `data_pipeline/collector.py` | 拉取多周期 K 线、ticker、orderbook、资金费率、未平仓量、Taker Volume、Top Trader Long/Short、标记价、强平等，具备缓存降级。 |
| `data_pipeline/feature_engine.py` | 统一调用 `DataProcessor` 计算技术指标，构建 `indicator_snapshot`、`multi_timeframe` 摘要，并封装 DeepSeek 所需的 market payload。 |
| `indicators/*.py` | 六大自研指标：趋势（MACD/EMA/SuperTrend/ADX）、量价（OBV/VPT/CVD/MFI）、结构波动（HH/HL + ATR/Bollinger）、多周期 RSI、VWAP、反转（Boll %B+OBV 背离+KDJ）。 |
| `scoring/scoring_engine.py` | 按 `indicator_weights` 聚合得分，输出 `indicator_score` 与各类 breakdown。 |
| `scoring/fusion_engine.py` | DeepSeek 先验（方向+置信度）与指标似然线性融合，默认阈值 `>=0.7` 做多、`<=-0.7` 做空。 |
| `execution/position_manager.py` | 将信号强度映射到配置的仓位档，并按杠杆缩放 6%/3% TP/SL。 |
| `execution/risk_controller.py` | 执行 TP/SL、AI 反转/峰值平仓、盈利移动止损与强制平仓时间。 |
| `strategy_runner.py` | 串联数据→指标→AI→打分→下单；维护 DeepSeek 缓存与状态；提供监控循环。 |
| `state_store.py` | JSON 文件形式的状态持久化工具。 |
| `env_loader.py` | 读取 `.env` 中的 OKX/DeepSeek Key。 |

## 运行流程
1. **数据聚合**：根据 `StrategyContext` 调用 `MarketDataCollector.collect()`，获取 K 线/附加指标；`FeatureEngineer.build_features()` 生成特征。
2. **指标打分**：对每个币调用各自的 Indicator Suite；使用 `IndicatorScoringEngine` 输出综合得分。
3. **AI 融合**：`DeepSeekClient.generate_signal()` → `SignalFusionEngine.fuse()`，得到最终方向、置信度与 `score`。
4. **信号筛选与下单**：挑选最高置信度币种；若已有仓位先走 `RiskController.evaluate_position()`；通过 `PositionManager.build_order()` 计算仓位与 TP/SL。
5. **状态更新**：下单或空仓都写入 `strategy_state.json`；`run_monitor_cycle()` 每分钟刷新行情，触发紧急退出或移动止损。

## 高可用要点
- 数据容错：采集失败自动回退缓存，DeepSeek 结果 2 分钟内复用。
- 状态持久化：策略和监控循环都会刷新 `active_position` 与 `last_signals`。
- 快速监控：`run_monitor_cycle()` 覆盖“开仓后每分钟 DeepSeek 分析”需求，调度器只需每分钟调用一次。
- 日志：关键节点使用 `strategy.runner`、`strategy.market_collector` 等 logger 输出错误及降级信息。

## 调度建议
- 15 分钟任务：调用 `StrategyRunner.run_cycle()`。
- 1 分钟任务：调用 `StrategyRunner.run_monitor_cycle()`。
- 结合实际执行引擎/下单模块，将 `order` payload 转入真实交易流程，并在完成后回写成交状态。
