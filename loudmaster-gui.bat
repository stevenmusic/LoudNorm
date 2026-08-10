@echo off
REM Windows: double-click this file to open the LoudMaster window.
cd /d "%~dp0"

where py >nul 2>nul && (
    py -3 -m loudmaster --gui
    goto :eof
)
where python >nul 2>nul && (
    python -m loudmaster --gui
    goto :eof
)

echo 找不到 Python 3。請先到 https://www.python.org/downloads/ 安裝，
echo 安裝時記得勾選 "Add Python to PATH"。
pause
