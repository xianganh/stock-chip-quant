@echo off
chcp 65001 >nul
title 筹码峰量化投研平台
cd /d "%~dp0"

echo.
echo ============================================================
echo   筹码峰量化投研平台 v1.0
echo ============================================================
echo.

REM ── 1. 检查 Python ──
python --version >nul 2>&1 || (
    echo [错误] 未检测到 Python，请先安装 Python 3.9+
    pause
    exit /b 1
)

REM ── 2. 检查/安装依赖 ──
echo [检查] 依赖包...
set "MISSING="
python -c "import flask" 2>nul || set "MISSING=%MISSING% flask flask-sqlalchemy"
python -c "import pandas" 2>nul || set "MISSING=%MISSING% pandas numpy"
python -c "import tushare" 2>nul || set "MISSING=%MISSING% tushare"
python -c "import plotly" 2>nul || set "MISSING=%MISSING% plotly kaleido"

if defined MISSING (
    echo [安装] 缺失的依赖: %MISSING%
    pip install %MISSING% -q
    if errorlevel 1 (
        echo [错误] 依赖安装失败，请检查网络或手动执行: pip install -r requirements.txt
        pause
        exit /b 1
    )
)

REM ── 3. 检查 Tushare Token ──
if not exist "%USERPROFILE%\.config\tushare\token" (
    if not exist "%USERPROFILE%\.tushare_token" (
        if "%TUSHARE_TOKEN%"=="" (
            echo.
            echo [警告] 未检测到 Tushare Token!
            echo   请通过以下任一方式配置:
            echo   1) 创建 %USERPROFILE%\.config\tushare\token 文件并填入 token
            echo   2) 设置环境变量 TUSHARE_TOKEN
            echo.
            echo   程序将继续启动，但分析功能可能无法使用。
            echo.
            timeout /t 3 >nul
        )
    )
)

REM ── 4. 启动服务 ──
echo [启动] http://127.0.0.1:5000
echo [提示] Ctrl+C 可停止服务
echo.

REM 打开浏览器（延迟 2 秒确保 Flask 已启动）
start /min cmd /c "timeout /t 2 >nul && start http://127.0.0.1:5000"

python app.py

pause