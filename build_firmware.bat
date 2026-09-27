@echo off
echo ===================================================
echo Starting Beelink GT-King Custom Firmware Build
echo ===================================================
python build_firmware.py
if %ERRORLEVEL% NEQ 0 (
    echo [ERROR] Build failed with exit code %ERRORLEVEL%!
    pause
    exit /b %ERRORLEVEL%
)
echo.
echo [SUCCESS] Build completed successfully!
pause
