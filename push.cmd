@echo off
chcp 65001 >nul
title Push to remote
powershell -ExecutionPolicy Bypass -File "%~dp0scripts\sync.ps1" -PushOnly
if "%~1"=="" (
  echo.
  pause
)
