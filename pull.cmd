@echo off
chcp 936 >nul
title 下载队友的改动
set "LOG=%TEMP%\team_sync_pull.log"
echo.
echo   正在把队友最新的改动下载下来，请稍等...
echo.
powershell -ExecutionPolicy Bypass -File "%~dp0scripts\sync.ps1" -PullOnly > "%LOG%" 2>&1
type "%LOG%"
echo.
echo ----------------------------------------------
findstr /C:"[OK] up to date" "%LOG%" >nul
if not errorlevel 1 echo   【成功】已经是最新的，可以开始干活了 & goto :end
findstr /C:"[INFO] no local changes" "%LOG%" >nul
if not errorlevel 1 echo   【成功】已经是最新的，可以开始干活了 & goto :end
findstr /C:"[FAIL] pull failed" "%LOG%" >nul
if not errorlevel 1 echo   【没东西可下载】云端还是空的，说明队长还没上传过。请先双击 push.cmd & goto :end
findstr /C:"schannel" "%LOG%" >nul
if not errorlevel 1 echo   【失败】这台电脑的网络加密有问题，把窗口截图发给队长 & goto :end
findstr /C:"not found" "%LOG%" >nul
if not errorlevel 1 echo   【失败】仓库地址不对，或者你还没被加进这个仓库 & goto :end
echo   【未知问题】把整个窗口截图发给队长，不要自己改文件
:end
echo ----------------------------------------------
echo   不需要你输入任何命令，按任意键关闭本窗口
pause >nul