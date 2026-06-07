#!/bin/zsh
set -e

cd "$(dirname "$0")"

if [[ ! -x ".venv/bin/python" ]]; then
  echo "未找到 .venv/bin/python。请先在项目目录安装 Python 环境。"
  echo
  echo "建议运行："
  echo "  python3 -m venv .venv"
  echo "  .venv/bin/python -m pip install -e ."
  echo
  read "?按回车关闭..."
  exit 1
fi

export PYTHONPATH="src:."
".venv/bin/python" -m question_bank.gui.app

