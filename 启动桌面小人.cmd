@echo off
chcp 65001 >nul
cd /d "%~dp0"
set "PYTHONPATH=%~dp0..\.pylibs;%~dp0"
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"

echo ==========================================================
echo    桌面小人（戴安娜）
echo ----------------------------------------------------------
echo    左键拖 = 挪位置      双击 = 打开完整聊天页
echo    右键   = 说话 / 三个小游戏 / 换站姿 / 退出
echo ==========================================================
echo.

python -c "import PySide6" 2>nul
if errorlevel 1 (
  echo   [!] 没装 PySide6，界面起不来。装一下再双击本文件：
  echo       python -m pip install -i https://pypi.tuna.tsinghua.edu.cn/simple PySide6-Essentials
  echo.
  pause
  exit /b 1
)

if not exist "assets\pet\diana_front.webp" (
  echo   [!] 找不到立绘 assets\pet\diana_front.webp
  echo       先生成： python experiments\make_cutout.py --src ^<参考图^> --out data\cutout\diana_front.png
  echo.
  pause
  exit /b 1
)

python desktop_pet.py %*
echo.
echo 小人已退出。
pause
