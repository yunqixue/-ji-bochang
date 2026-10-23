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
findstr /C:"[CONFLICT]" "%LOG%" >nul
if not errorlevel 1 (
  echo   【有冲突】你和队友改了同一批文件，自动合并失败。
  echo.
  echo   按这三步做（文档类冲突很简单）：
  echo     1. 打开上面列出的文件，删掉 ^<^<^<^<^<^<^< / ======= / ^>^>^>^>^>^>^> 这些标记行
  echo        两边内容都保留，别删别人的
  echo     2. git add -A
  echo     3. git commit -m "merge: 解决冲突"
  echo.
  echo   如果想放弃、回到拉取之前的状态： git merge --abort
  echo   （如果提示还有没结束的 rebase，先执行 git rebase --abort）
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