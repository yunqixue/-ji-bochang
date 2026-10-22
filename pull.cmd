@echo off
chcp 65001 >nul
title Pull from remote
powershell -ExecutionPolicy Bypass -File "%~dp0scripts\sync.ps1" -PullOnly
if "%~1"=="" (
  echo.
  pause
)
