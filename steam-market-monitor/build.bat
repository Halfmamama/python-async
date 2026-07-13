@echo off
echo ============================================================
echo  Steam Market Monitor - Build (no console window)
echo ============================================================

echo.
echo [1/3] pip install -r requirements.txt ...
pip install -r requirements.txt
if errorlevel 1 ( echo ERROR: pip install failed. & pause & exit /b 1 )

echo.
echo [2/3] pip install pyinstaller ...
pip install pyinstaller
if errorlevel 1 ( echo ERROR: pyinstaller install failed. & pause & exit /b 1 )

echo.
echo [3/3] pyinstaller --onefile --noconsole ...
pyinstaller --onefile --noconsole --name steam_market_monitor --clean monitor.py
if errorlevel 1 ( echo ERROR: PyInstaller failed. & pause & exit /b 1 )

echo.
echo ============================================================
echo  Done!  File: dist\steam_market_monitor.exe
echo  Copy dist\steam_market_monitor.exe + config.json + README.md
echo  into one folder on the target machine.
echo ============================================================
pause
