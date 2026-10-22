@echo off
chcp 936 >nul
title 上传到云端
set "LOG=%TEMP%\team_sync_push.log"
echo.
echo   正在上传，请稍等...
echo   （如果弹出登录框，请看下面说明，不要关掉窗口）
echo.
powershell -ExecutionPolicy Bypass -File "%~dp0scripts\sync.ps1" -PushOnly > "%LOG%" 2>&1
type "%LOG%"
echo.
echo ----------------------------------------------
findstr /C:"[OK] pushed" "%LOG%" >nul
if not errorlevel 1 echo   【成功】代码已经上传到云端，队友可以 pull 到了 & goto :end
findstr /C:"Authentication failed" "%LOG%" >nul
if not errorlevel 1 echo   【失败】用户名或密码填错了。密码要填【私人令牌】，不是登录密码 & goto :end
findstr /C:"Author identity" "%LOG%" >nul
if not errorlevel 1 echo   【失败】你还没设置名字和邮箱，把窗口截图发给队长 & goto :end
findstr /C:"schannel" "%LOG%" >nul
if not errorlevel 1 echo   【失败】这台电脑的网络加密有问题，把窗口截图发给队长 & goto :end
findstr /C:"not found" "%LOG%" >nul
if not errorlevel 1 echo   【失败】仓库地址不对，或者你还没被加进这个仓库 & goto :end
findstr /C:"push failed" "%LOG%" >nul
if not errorlevel 1 echo   【失败】别人刚好也上传了，再双击一次本文件即可 & goto :end
echo   【未知问题】把整个窗口截图发给队长，不要自己改文件
:end
echo ----------------------------------------------
echo   不需要你输入任何命令，按任意键关闭本窗口
pause >nul