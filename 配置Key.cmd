@echo off
chcp 65001 >nul
cd /d "%~dp0"
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"

echo ==========================================================
echo    配置 DeepSeek Key（每台机器只需要做一次）
echo ----------------------------------------------------------
echo    1. 接下来会自动打开 DeepSeek 的 API keys 页面
echo    2. 点「新建」，复制那串 sk- 开头的东西
echo    3. 然后会弹出记事本，把 Key 整串粘进去
echo       注意：文件里只放这一串，不带引号、不留别的行
echo    4. 保存并关掉记事本，我自动帮你验证能不能用
echo ==========================================================
echo.
echo   （没有账号也行：不配 Key 也能启动，只是回复会变成很机械的固定模板，
echo     那种状态不能用来评价"像不像人"。）
echo.
pause

start "" "https://platform.deepseek.com/api_keys"
if not exist "api_key.txt" echo.> "api_key.txt"
notepad "api_key.txt"

echo.
echo 正在真实调用一次模型验证……
echo.
python experiments/check_key.py

echo.
echo ----------------------------------------------------------
echo   如果上面是绿勾：关掉这个窗口，双击 run.cmd 就能用了。
echo   如果报错了：按上面的中文提示处理；处理不了把截图发群里。
echo ----------------------------------------------------------
echo.
pause
