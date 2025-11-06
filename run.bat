@echo off
chcp 65001 >nul
echo ============================================================
echo 量化交易系统 - 启动脚本
echo ============================================================
echo.

cd /d "%~dp0"

echo 正在检查Python环境...
python --version >nul 2>&1
if errorlevel 1 (
    echo [错误] 未找到Python，请先安装Python
    pause
    exit /b 1
)

echo.
echo 正在启动系统...
echo.

python run.py

if errorlevel 1 (
    echo.
    echo ============================================================
    echo 系统启动失败，请查看上面的错误信息
    echo ============================================================
    pause
    exit /b 1
)

pause

