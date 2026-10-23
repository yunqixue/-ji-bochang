@echo off
chcp 65001 >nul
set PYTHONIOENCODING=utf-8
cd /d "%~dp0.."

echo.
echo   对话标注表批量跑 —— 30 条自动填表
echo   只会覆盖三列：实际识别情绪 / 实际回复 / 判对?
echo   你手工填过的列（像不像人、客服腔、严重度…）不会被动
echo.

set "URL=%~1"
if "%URL%"=="" set /p "URL=服务地址（回车 = http://127.0.0.1:8000，C 给的链接就粘进来）: "
if "%URL%"=="" set "URL=http://127.0.0.1:8000"

echo.
echo   目标：%URL%
echo.
py -3.14 "%~dp0annotate_batch.py" --url "%URL%" %2 %3

echo.
echo 跑完了。打开 assets\samples\对话标注表_30条.csv 接着填主观判断那几列。
pause
