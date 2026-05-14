@echo off
chcp 65001 >nul
title CDI 猎头工具

echo ================================
echo   CDI 猎头工具 - 启动中...
echo ================================
echo.

REM ── 进入脚本所在目录 ────────────────────────────────────────────────────────
cd /d "%~dp0"

REM ── 检查Python ──────────────────────────────────────────────────────────────
python --version >nul 2>&1
if %errorlevel% neq 0 (
  echo [错误] 未找到 Python，请先安装 Python 3.10 或以上版本
  echo        下载地址：https://www.python.org/downloads/
  echo.
  pause
  exit /b 1
)

REM 获取版本号并检查
for /f "tokens=2" %%v in ('python --version 2^>^&1') do set PYVER=%%v
echo   Python %PYVER%

REM 简单检查主版本（3.x才继续，更精确的版本检查留给pip安装阶段报错）
for /f "tokens=1 delims=." %%m in ("%PYVER%") do set PYMAJOR=%%m
if %PYMAJOR% lss 3 (
  echo [错误] Python 版本过低，需要 3.10 或以上
  echo        下载地址：https://www.python.org/downloads/
  echo.
  pause
  exit /b 1
)

REM ── 创建虚拟环境（仅首次） ──────────────────────────────────────────────────
if not exist venv (
  echo 正在创建虚拟环境（首次启动，约需1分钟）...
  python -m venv venv
  if %errorlevel% neq 0 (
    echo [错误] 虚拟环境创建失败，请检查 Python 安装是否完整
    pause
    exit /b 1
  )
)

REM ── 激活虚拟环境 ────────────────────────────────────────────────────────────
call venv\Scripts\activate.bat

REM ── 安装/更新依赖 ──────────────────────────────────────────────────────────
echo 正在检查依赖（首次约需2-3分钟）...
pip install -r requirements.txt -q
if %errorlevel% neq 0 (
  echo.
  echo [错误] 依赖安装失败，请检查网络连接后重试
  pause
  exit /b 1
)

echo.
echo   就绪！浏览器将自动打开 http://localhost:8000
echo   如未自动打开，请手动在浏览器访问该地址
echo.
echo   关闭此窗口即可停止工具
echo.

REM ── 启动FastAPI服务 ─────────────────────────────────────────────────────────
python -m uvicorn app:app --host 127.0.0.1 --port 8000

pause
