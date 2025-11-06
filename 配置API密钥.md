# 配置API密钥指南

## 🔑 OKX API密钥配置

### 方式1：创建.env文件（推荐）

在项目根目录（`crypto-trading-system/`）创建 `.env` 文件，并填入以下内容：

```env
# OKX API配置
OKX_API_KEY=cdd0aef7-ee09-439e-a106-a1e436374473
OKX_SECRET_KEY=69E4D8BF92E4939572BD77E789D52BE1
OKX_PASSPHRASE=Lishaawbz520.

# DeepSeek API配置（如果需要）
DEEPSEEK_API_KEY=your_deepseek_api_key_here
```

### 方式2：直接编辑配置文件（不推荐）

可以直接在 `config/api_config.yaml` 中填写API密钥，但不推荐，因为配置文件可能会被提交到代码库。

```yaml
okx:
  api_key: "cdd0aef7-ee09-439e-a106-a1e436374473"
  secret_key: "69E4D8BF92E4939572BD77E789D52BE1"
  passphrase: "Lishaawbz520."
```

## 📝 配置步骤

### 步骤1：创建.env文件

1. 在项目根目录 `crypto-trading-system/` 下创建 `.env` 文件
2. 复制以下内容到 `.env` 文件：

```env
OKX_API_KEY=cdd0aef7-ee09-439e-a106-a1e436374473
OKX_SECRET_KEY=69E4D8BF92E4939572BD77E789D52BE1
OKX_PASSPHRASE=Lishaawbz520.
```

### 步骤2：验证配置

运行配置检查脚本：

```bash
python scripts/check_config.py
```

或双击 `check_config.bat`

如果配置正确，会显示：
```
✓ OKX API Key: cdd0****
✓ OKX Secret Key: 69E4****
✓ OKX Passphrase: Lish****
```

## ⚠️ 安全提示

1. **不要将.env文件提交到Git**
   - `.env` 文件已在 `.gitignore` 中，不会被提交
   - 确保不要意外提交包含密钥的文件

2. **保护API密钥**
   - 不要分享API密钥给他人
   - 不要在公共场合展示API密钥
   - 定期更换API密钥

3. **API权限设置**
   - 建议在OKX账户中限制API权限（只读或有限交易权限）
   - 不要给API完全权限

4. **备份密钥**
   - 妥善保管API密钥的备份
   - 建议使用密码管理器存储

## 🔧 验证配置

配置完成后，运行以下命令验证：

```bash
python scripts/check_config.py
```

如果看到以下输出，说明配置成功：
```
✓ OKX API Key: cdd0****
✓ OKX Secret Key: 69E4****
✓ OKX Passphrase: Lish****
```

## ❓ 常见问题

### Q1: 配置后仍然显示"未配置"
**A**: 确保 `.env` 文件在项目根目录，且格式正确（没有多余空格）

### Q2: API密钥无效
**A**: 检查API密钥是否正确，确保从OKX官方网站获取

### Q3: 权限错误
**A**: 检查OKX API密钥的权限设置，确保有足够的权限

---

**注意**：配置完成后，系统会自动从环境变量读取API密钥，无需重启系统。

