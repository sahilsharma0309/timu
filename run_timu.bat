@echo off
REM ---- Timu v2 launcher (Windows) ----------------------------------------
cd /d "%~dp0"
where python >nul 2>nul || (echo Python nahi mila. python.org se install karo. & pause & exit /b 1)
if not exist ".venv" (
  echo [timu] virtual env bana raha hoon...
  python -m venv .venv
)
call .venv\Scripts\activate.bat
python -m pip install -q --upgrade pip
python -m pip install -q -r requirements.txt

REM Chromium sirf JS-rendered sites ke liye chahiye (RENDER = BROWSER)
python timu_doctor.py --chromium
if errorlevel 1 (
  echo.
  set /p TIMUB="[timu] JS-rendered sites ke liye Chromium install karna hai? (y/N): "
  if /i "%TIMUB%"=="y" python -m playwright install chromium
)

echo.
echo   TIMU v2 starting -^> http://127.0.0.1:7801
echo.
python timu_app.py
pause
