@echo off
chcp 936 >nul
title 下载队友的改动
set "LOG=%TEMP%\team_sync_pull.log"
echo.
echo   正在把队友最新的改动下载下来，请稍等...
echo.
powershell -ExecutionPolicy Bypass -File "%~dp0scripts\sync.ps1" -PullOnly > "%LOG%" 2>&1
set "RC=%ERRORLEVEL%"
type "%LOG%"
echo.
echo ----------------------------------------------
findstr /C:"[CONFLICT]" "%LOG%" >nul
if not errorlevel 1 (
  echo   【有冲突】你和队友改了同一批文件，自动合并失败。
  echo   不要自己乱改！把窗口截图发群里，由改得多的那个人处理。
  echo   想回到拉取之前的状态，可以在项目目录执行：git rebase --abort
  goto :end
)
findstr /C:"[OK] up to date" "%LOG%" >nul
if not errorlevel 1 echo   【成功】已经是最新的，可以开始干活了 & goto :end
findstr /C:"[INFO] nothing new" "%LOG%" >nul
if not errorlevel 1 echo   【成功】没有新东西，已经是最新的 & goto :end
findstr /C:"[FAIL] pull failed" "%LOG%" >nul
if not errorlevel 1 echo   【失败】云端可能还是空的（那就先双击 push.cmd），否则把截图发群里 & goto :end
findstr /C:"schannel" "%LOG%" >nul
if not errorlevel 1 echo   【失败】网络加密问题，把窗口截图发群里 & goto :end
findstr /C:"not found" "%LOG%" >nul
if not errorlevel 1 echo   【失败】仓库地址不对，或你还没被加进这个仓库 & goto :end
echo   【未知问题】把整个窗口截图发群里，不要自己改文件
:end
echo ----------------------------------------------
echo   不需要你输入任何命令，按任意键关闭本窗口
pause >nul