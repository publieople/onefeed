#!/usr/bin/env sh
# OneFeed 现场启动：先自检，再起服务。
#   ./start.sh          用 8791 端口
#   ./start.sh 8792     换端口
set -e
cd "$(dirname "$0")"
PORT="${1:-8791}"

echo "============================================"
echo "  OneFeed 现场启动   端口 ${PORT}"
echo "============================================"
echo

if ! uv run python -m onefeed --preflight --port "$PORT"; then
  echo
  echo "自检有阻塞项，先按上面的箭头提示处理，再重跑这个脚本。" >&2
  exit 1
fi

echo
echo "自检通过，启动服务（Ctrl+C 退出）…"
echo
exec uv run python -m onefeed --port "$PORT"
