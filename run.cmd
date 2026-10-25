@echo off
chcp 65001 >nul
cd /d "%~dp0"
set "PYTHONPATH=%~dp0..\.pylibs;%~dp0;%PYTHONPATH%"
set "PORT=8000"

echo.
echo   情感交互智能体 —— 本地演示
echo   地址：http://127.0.0.1:%PORT%
echo   关掉这个窗口就停止服务
echo.

rem 服务要几秒才起得来，所以延迟 4 秒再开浏览器，避免打开是「无法连接」
start "" /b powershell -NoProfile -WindowStyle Hidden -Command "Start-Sleep -Seconds 4; Start-Process 'http://127.0.0.1:%PORT%'"

python -m uvicorn app:app --host 127.0.0.1 --port %PORT%

echo.
echo 服务已停止。如果是报错，把上面的内容截图发群里。
pause
