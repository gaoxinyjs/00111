# 量化交易系统

基于OKX API和DeepSeek AI的量化交易系统

## 📋 项目简介

这是一个完整的量化交易系统，集成了：
- **OKX API**：实时行情数据获取和交易执行
- **DeepSeek AI**：智能市场分析和信号生成
- **多维度信号**：技术面、资金面、情绪面综合分析
- **风险管理**：多层次风险控制和监控
- **收益统计**：交易、小时、天、月多维度统计

## ✨ 核心功能

- ✅ **数据采集**：实时行情、K线、订单簿数据采集
- ✅ **信号生成**：技术面、资金面、AI分析信号融合
- ✅ **决策生成**：综合多维度信号生成交易决策
- ✅ **交易执行**：订单管理、执行优化、滑点控制
- ✅ **风险管理**：止损、回撤、仓位控制
- ✅ **收益统计**：多维度收益统计和报告

## 🚀 快速开始

### 1. 环境准备

```bash
# 进入项目目录
cd crypto-trading-system

# 安装依赖
pip install -r requirements.txt
```

### 2. 配置设置

```bash
# 创建.env文件（参考.env.example）
# 配置OKX和DeepSeek的API密钥

# 检查配置
python scripts/check_config.py
```

### 3. 初始化数据库（可选）

```bash
# 初始化PostgreSQL表结构
python scripts/init_db.py
```

### 4. 运行系统

```bash
# 启动交易系统
python src/main.py
```

## 📁 项目结构

```
crypto-trading-system/
├── config/              # 配置文件
│   ├── config.yaml
│   ├── trading_config.yaml
│   ├── risk_config.yaml
│   └── api_config.yaml
├── src/                  # 源代码
│   ├── core/            # 核心模块
│   ├── data/            # 数据采集
│   ├── analysis/        # 分析模块
│   ├── decision/        # 决策模块
│   ├── trading/         # 交易执行
│   ├── risk/            # 风险管理
│   ├── monitoring/      # 监控模块
│   ├── storage/         # 存储模块
│   ├── utils/           # 工具模块
│   └── main.py          # 主程序
├── scripts/             # 脚本
│   ├── init_db.py       # 初始化数据库
│   └── check_config.py  # 检查配置
├── tests/               # 测试
├── logs/                # 日志
├── data/                # 数据
└── docs/                # 文档
```

## ⚙️ 配置说明

### 主配置文件 (config/config.yaml)

- 系统配置：名称、版本、环境
- 日志配置：级别、文件路径、轮转设置
- 数据库配置：PostgreSQL、InfluxDB、Redis
- 任务调度配置：数据采集、信号生成间隔

### 交易配置 (config/trading_config.yaml)

- 交易对配置
- 信号生成配置（技术面、资金面、AI分析）
- 信号评分配置

### 风险配置 (config/risk_config.yaml)

- 仓位管理配置
- 止损配置
- VaR配置
- 风险限制

### API配置 (config/api_config.yaml)

- OKX API配置
- DeepSeek API配置
- 限流和重试配置

## 🔧 使用说明

### 检查配置

```bash
python scripts/check_config.py
```

验证配置文件和环境变量是否正确。

### 初始化数据库

```bash
python scripts/init_db.py
```

创建PostgreSQL数据库表结构。

### 运行系统

```bash
python src/main.py
```

系统将：
1. 加载所有配置
2. 初始化各个模块
3. 启动数据采集
4. 启动主交易循环
5. 执行自动化交易

## 📊 核心模块

### 数据采集模块

- **DataCollector**：定时采集行情、订单簿、K线数据
- **DataProcessor**：数据清洗和技术指标计算

### 分析模块

- **SignalGenerator**：多维度信号生成（技术面、资金面、AI分析）
- **SignalFilter**：信号过滤和假信号识别

### 决策模块

- **DecisionEngine**：综合信号生成交易决策
- **PositionCalculator**：动态仓位计算
- **RiskEvaluator**：风险评估

### 交易执行模块

- **OrderManager**：订单生命周期管理
- **ExecutionEngine**：订单执行优化
- **TradingEngine**：完整交易流程整合

### 风险管理模块

- **RiskManager**：统一风险管理
- **StopLossManager**：止损管理
- **DrawdownController**：回撤控制

### 监控模块

- **ProfitStatistics**：收益统计（交易、小时、天、月）

## ⚠️ 重要提示

1. **测试环境**：建议先在测试环境验证所有功能
2. **API密钥**：确保API密钥正确配置且权限足够
3. **风险控制**：系统有完善的风险控制，但实际交易需谨慎
4. **资金管理**：建议从小额开始测试
5. **监控日志**：密切关注系统日志和交易状态

## 📚 文档

- [项目架构设计](../项目架构设计.md) - 完整架构设计
- [交易策略](../交易策略.md) - 交易策略文档
- [快速开始](./快速开始.md) - 快速开始指南
- [完整项目清单](./完整项目清单.md) - 完整模块清单

## 📝 许可证

本项目仅供学习和研究使用。

## 🤝 贡献

欢迎提交问题和改进建议。

## 📞 联系方式

如有问题，请通过GitHub Issues联系。

---

**免责声明**：本系统仅供学习研究使用，使用本系统进行实盘交易的所有风险由使用者自行承担。
