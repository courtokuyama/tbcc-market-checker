#!/bin/bash
# ダブルクリックで「TBCC 相場ボード」を起動（ブラウザが自動で開く）。止めるときはこの窓で Ctrl+C。
cd "$(dirname "$0")" || exit 1
exec python3 app.py
