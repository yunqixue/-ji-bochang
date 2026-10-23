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
if not errorlevel 1 echo   【成功】代码已经上传到云端 & goto :end

rem 只认 sync.ps1 输出的 [RESULT] 分类，不模糊搜关键字
findstr /C:"[RESULT] REJECTED" "%LOG%" >nul
if not errorlevel 1 (
  echo   【失败】队友比你早推了，云端有他更新的提交。
  echo.
  echo   解决：先双击 pull.cmd，再双击本文件。
  echo   pull 时如果提示冲突，按 docs\疑难排查.md 第 12 节处理。
  goto :end
)
findstr /C:"[RESULT] AUTH" "%LOG%" >nul
if not errorlevel 1 (
  echo   【失败】账号密码不对。密码要填【私人令牌】，不是登录密码。
  echo   令牌在：Gitee 头像 -^> 设置 -^> 安全设置 -^> 私人令牌 -^> 生成新令牌（勾 projects）
  goto :end
)
findstr /C:"[RESULT] TLS" "%LOG%" >nul
if not errorlevel 1 (
  echo   【失败】这台电脑的网络加密有问题（TLS）。
  echo   在项目目录执行一次：git config http.sslBackend openssl
  echo   然后重试；还不行就把窗口截图发队长。
  goto :end
)
findstr /C:"[RESULT] NO_REPO" "%LOG%" >nul
if not errorlevel 1 (
  echo   【失败】仓库地址不对，或者你还没被加进这个仓库。
  echo   用浏览器打开仓库地址确认能不能访问。
  goto :end
)
findstr /C:"[CONFLICT]" "%LOG%" >nul
if not errorlevel 1 (
  echo   【失败】有冲突没解决，先把冲突处理完（见 docs\疑难排查.md 第 12 节）。
  goto :end
)
echo   【失败】原因没识别出来（UNKNOWN）。把整个窗口截图发给队长，不要自己猜。
:end
echo ----------------------------------------------
echo   不需要你输入任何命令，按任意键关闭本窗口
pause >nul