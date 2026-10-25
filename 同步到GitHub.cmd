@echo off
chcp 936 >nul
title 同步到 GitHub
cd /d "%~dp0"
echo.
echo   ================================================
echo    把本地 main 推送到 GitHub 私有仓库
echo    github.com/yunqixue/-ji-bochang
echo   ================================================
echo.
echo   如果弹出登录框：
echo     用户名  yunqixue
echo     密码    填 Personal Access Token（不是登录密码！）
echo             没有令牌就去 GitHub：头像 -^> Settings -^> Developer settings
echo               -^> Personal access tokens -^> Tokens (classic)
echo               -^> Generate new token，勾上 repo，生成后马上复制
echo.
echo   正在推送，第一次要把 165 个提交全传上去，可能 1-3 分钟...
echo.
git push github main
if errorlevel 1 goto failed
echo.
echo   ------------------------------------------------
echo   【成功】GitHub 上的仓库已经和本地一致
echo   ------------------------------------------------
goto end

:failed
echo.
echo   ------------------------------------------------
echo   【失败】上面是 git 的原话，按这句对号入座：
echo     Authentication failed   -^> 密码位置要填令牌，不是登录密码
echo     schannel / SSL          -^> 执行一次：git config http.sslBackend openssl 再重试
echo     rejected / fetch first  -^> GitHub 那个仓库不是空的（建库时勾了 README），删掉重建
echo     repository not found    -^> 用户名或仓库名拼错，或者仓库还没建
echo   ------------------------------------------------

:end
echo.
echo   按任意键关闭本窗口
pause >nul
