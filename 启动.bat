@echo off
chcp 65001 >nul
cd /d "%~dp0"
set PORT=8000
set PYEXE=

rem 优先用 py 启动器，避免命中 Microsoft Store 的 python 占位程序
where py >nul 2>nul && set PYEXE=py -3
if not defined PYEXE (where python >nul 2>nul && set PYEXE=python)
if not defined PYEXE (
  echo [!] 找不到 Python。请先安装 Python 3，安装时勾选 "Add python.exe to PATH"。
  pause
  exit /b 1
)

echo 正在启动《第一年》...
echo 地址：http://127.0.0.1:%PORT%
start "" http://127.0.0.1:%PORT%
%PYEXE% server.py
echo.
echo 服务已退出。如果上面提示端口被占用，说明已经开着一个了，直接浏览器访问 http://127.0.0.1:%PORT% 即可。
pause
