@echo off
setlocal EnableExtensions
title WHITEBLOCK - Blender 3D Whiteblock Workbench
cd /d "%~dp0"

rem Prefer an explicitly configured local Blender, then PATH, then common install paths.
if not defined BLENDER_BIN (
  for /f "delims=" %%B in ('where blender.exe 2^>nul') do if not defined BLENDER_BIN set "BLENDER_BIN=%%B"
)
if not defined BLENDER_BIN if exist "C:\Program Files\Blender Foundation\Blender 5.1\blender.exe" set "BLENDER_BIN=C:\Program Files\Blender Foundation\Blender 5.1\blender.exe"
if not defined BLENDER_BIN if exist "C:\Program Files\Blender Foundation\Blender 5.0\blender.exe" set "BLENDER_BIN=C:\Program Files\Blender Foundation\Blender 5.0\blender.exe"
if not defined BLENDER_BIN if exist "C:\Program Files\Blender Foundation\Blender 4.3\blender.exe" set "BLENDER_BIN=C:\Program Files\Blender Foundation\Blender 4.3\blender.exe"
if not defined BLENDER_BIN if exist "D:\Program Files\Blender Foundation\Blender 5.1\blender.exe" set "BLENDER_BIN=D:\Program Files\Blender Foundation\Blender 5.1\blender.exe"
if not defined BLENDER_BIN if exist "D:\Blender\blender.exe" set "BLENDER_BIN=D:\Blender\blender.exe"

if defined BLENDER_BIN (
  echo [OK] Local Blender: %BLENDER_BIN%
  "%BLENDER_BIN%" --version 2^>nul | findstr /i "Blender" >nul
  if errorlevel 1 echo [WARN] Blender executable was found but could not report its version.
) else (
  echo [WARN] Local Blender was not found.
  echo        Set BLENDER_BIN to Blender 5.1.2 before using Agent: run Blender.
)

set "PYTHON_EXE=D:\Python\python.exe"
if not exist "%PYTHON_EXE%" set "PYTHON_EXE=python.exe"
if not exist "%PYTHON_EXE%" (
  echo [ERROR] Python was not found. Expected D:\Python\python.exe or PATH python.exe.
  pause
  exit /b 1
)

echo [OK] Starting WHITEBLOCK desktop control room...
rem Empty START title is intentional: the first quoted argument is otherwise interpreted as a window title.
start "" /D "%~dp0" /b "%PYTHON_EXE%" -m whiteblock desktop
exit /b 0
