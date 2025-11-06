# 项目打包说明

## 打包方式

### 方式1：使用 Python 脚本（推荐）

```bash
cd crypto-trading-system
python package.py
```

打包完成后，会在项目父目录生成 `crypto-trading-system_YYYYMMDD_HHMMSS.tar.gz` 文件。

### 方式2：使用批处理文件（Windows）

双击运行 `package.bat`

### 方式3：手动使用 tar 命令（Linux/Mac）

```bash
cd crypto-trading-system
tar -czf ../crypto-trading-system.tar.gz \
  --exclude='__pycache__' \
  --exclude='*.pyc' \
  --exclude='.env' \
  --exclude='*.log' \
  --exclude='venv' \
  --exclude='.git' \
  .
```

## 打包内容

打包脚本会自动排除以下内容：
- `__pycache__/` 目录和 `*.pyc` 文件
- `.env` 文件（敏感信息）
- `*.log` 日志文件
- 虚拟环境目录（`venv/`, `env/`）
- IDE 配置目录（`.vscode/`, `.idea/`）
- Git 相关文件（`.git/`, `.gitignore`）
- 构建产物（`build/`, `dist/`, `*.egg-info/`）

## 解压

解压 tar.gz 文件：

```bash
# Linux/Mac
tar -xzf crypto-trading-system_*.tar.gz

# Windows (使用 7-Zip 或 WinRAR)
# 或者使用 Python
python -c "import tarfile; tarfile.open('crypto-trading-system_*.tar.gz').extractall()"
```

