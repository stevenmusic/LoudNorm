#!/usr/bin/env bash
# macOS: double-click this file in Finder to open the LoudMaster window.
# (If macOS refuses, run once in Terminal:  chmod +x loudmaster-gui.command)
cd "$(dirname "$0")" || exit 1

for candidate in python3 python; do
    if command -v "$candidate" >/dev/null 2>&1; then
        exec "$candidate" -m loudmaster --gui
    fi
done

echo "找不到 Python 3。請先到 https://www.python.org/downloads/ 安裝。"
read -r -p "按 Enter 關閉…" _
exit 1
