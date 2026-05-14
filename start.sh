#!/bin/bash
# CDI猎头工具 - Mac启动脚本
# 用法：在终端运行 bash start.sh
#       或右键 → 打开方式 → 终端（需先执行 chmod +x start.sh）

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

echo "================================"
echo "  CDI 猎头工具 - 启动中..."
echo "================================"
echo ""

# ── 检查Python版本（需要3.10+） ──────────────────────────────────────────────
if ! command -v python3 &>/dev/null; then
  echo "❌ 未找到 Python3，请先安装 Python 3.10 或以上版本"
  echo "   下载地址：https://www.python.org/downloads/"
  echo ""
  read -p "按回车键退出..."
  exit 1
fi

PY_MAJOR=$(python3 -c "import sys; print(sys.version_info.major)")
PY_MINOR=$(python3 -c "import sys; print(sys.version_info.minor)")
PY_VER="$PY_MAJOR.$PY_MINOR"

if [ "$PY_MAJOR" -lt 3 ] || { [ "$PY_MAJOR" -eq 3 ] && [ "$PY_MINOR" -lt 10 ]; }; then
  echo "❌ Python 版本过低（当前：$PY_VER），需要 3.10 或以上"
  echo "   下载地址：https://www.python.org/downloads/"
  echo ""
  read -p "按回车键退出..."
  exit 1
fi

echo "✓ Python $PY_VER"

# ── 创建虚拟环境（仅首次） ──────────────────────────────────────────────────
if [ ! -d "venv" ]; then
  echo "正在创建虚拟环境（首次启动，约需1分钟）..."
  python3 -m venv venv
  if [ $? -ne 0 ]; then
    echo "❌ 虚拟环境创建失败，请检查 Python 安装是否完整"
    read -p "按回车键退出..."
    exit 1
  fi
fi

# ── 激活虚拟环境 ────────────────────────────────────────────────────────────
source venv/bin/activate

# ── 安装/更新依赖 ──────────────────────────────────────────────────────────
echo "正在检查依赖（首次约需2-3分钟）..."
pip install -r requirements.txt -q --no-warn-script-location

if [ $? -ne 0 ]; then
  echo ""
  echo "❌ 依赖安装失败，请检查网络连接后重试"
  read -p "按回车键退出..."
  exit 1
fi

echo ""
echo "✓ 就绪！浏览器将自动打开 http://localhost:8000"
echo "  如未自动打开，请手动在浏览器访问该地址"
echo ""
echo "  按 Ctrl+C 可关闭工具"
echo ""

# 启动FastAPI服务（app.py内部会自动打开浏览器）
python3 -m uvicorn app:app --host 127.0.0.1 --port 8000
