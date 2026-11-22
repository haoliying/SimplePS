@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo ============================================
echo  SimplePS - 打包 Windows 可执行程序
echo ============================================
echo.

python --version >nul 2>&1
if errorlevel 1 (
    echo [错误] 未找到 Python，请先安装 Python 3.10+ 并勾选 Add Python to PATH
    pause
    exit /b 1
)

echo [1/3] 安装依赖...
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
if errorlevel 1 goto fail

echo [2/3] 清理旧构建...
if exist build rmdir /s /q build
if exist dist rmdir /s /q dist

echo [3/3] 使用 PyInstaller 生成 EXE...
pyinstaller --clean --noconfirm SimplePS.spec
if errorlevel 1 goto fail
pyinstaller --clean --noconfirm SimplePS_CLI.spec
if errorlevel 1 goto fail

echo.
echo [完成] 已生成:
echo   %~dp0dist\SimplePS.exe      (图形界面版)
echo   %~dp0dist\SimplePS-cli.exe  (命令行版)
echo 可将 exe 单独复制到其他 Windows 电脑运行（无需安装 Python）。
echo.
pause
exit /b 0

:fail
echo.
echo [失败] 打包过程中出现错误，请查看上方日志。
pause
exit /b 1
