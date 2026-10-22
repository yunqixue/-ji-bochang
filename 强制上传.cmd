@echo off
chcp 936 >nul
title 强制上传（只在清理历史时用一次）
set "LOG=%TEMP%\team_force_push.log"
echo.
echo ============================================================
echo   用途：把本地已清理的历史【覆盖】到云端。
echo   只在这次清理 令牌.txt 之后用一次。
echo.
echo   注意：如果队友已经把代码推上去了，绝对不要点这个，
echo         因为它会覆盖掉云端的提交。现在只有队长自己推过，所以安全。
echo ============================================================
echo.
pause
echo.
echo   正在强制上传...
echo.
powershell -ExecutionPolicy Bypass -File "%~dp0scripts\sync.ps1" -Force > "%LOG%" 2>&1
type "%LOG%"
echo.
echo ----------------------------------------------
findstr /C:"[OK] pushed" "%LOG%" >nul
if not errorlevel 1 echo   【成功】云端历史已被覆盖，令牌文件彻底没了 & goto :end
findstr /C:"Authentication failed" "%LOG%" >nul
if not errorlevel 1 echo   【失败】用户名或密码错。注意：旧令牌已删，要用【新生成的令牌】 & goto :end
findstr /C:"schannel" "%LOG%" >nul
if not errorlevel 1 echo   【失败】网络加密问题，把窗口截图发给队长 & goto :end
findstr /C:"not found" "%LOG%" >nul
if not errorlevel 1 echo   【失败】仓库不存在，先去 Gitee 确认仓库还在 & goto :end
echo   【未知问题】把整个窗口截图发群里
:end
echo ----------------------------------------------
echo   按任意键关闭本窗口
pause >nul