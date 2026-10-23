@echo off
chcp 65001 >nul
cd /d "%~dp0.."
echo.
echo   表情图规整 —— data\raw_images\  →  assets\images\expr_*.webp
echo   原图文件名就是表情名：neutral.png / sad.jpg / happy.webp ...
echo.
node "%~dp0imgtool\prep-images.js" %*
echo.
echo 退出码 0 = 全部合格；非 0 = 上面列了要处理的项。
pause
