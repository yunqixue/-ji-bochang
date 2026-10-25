@echo off
chcp 65001 >nul
cd /d "%~dp0"
set "PYTHONPATH=%~dp0..\.pylibs;%~dp0;%PYTHONPATH%"
set "PORT=8001"
set "DEMO_FALLBACK=1"
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"

echo.
echo   模式 B：完全离线（保险模式）
echo   地址：http://127.0.0.1:%PORT%
echo.
echo   特点：只认演示脚本里的 9 句，回答质量已验证，每句约 3 毫秒，
echo         语音 100%% 有声音；临时提问答不出来。
echo   什么时候用：自检说语音失败、现场网络不稳、或模式 A 卡住时。
echo   关掉这个窗口就停止服务。
echo.

start "" /b powershell -NoProfile -WindowStyle Hidden -Command "Start-Sleep -Seconds 4; Start-Process 'http://127.0.0.1:%PORT%'"

python -m uvicorn app:app --host 127.0.0.1 --port %PORT%

echo.
echo 服务已停止。
pause
