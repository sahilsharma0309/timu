@echo off
REM ---- Timu -> GitHub, one click (Windows) -------------------------------
REM Repo: https://github.com/sahilsharma0309/timu   (khaali repo pehle se bana hua ho)
cd /d "%~dp0"
setlocal
set OWNER=sahilsharma0309
set REPO=timu

where git >nul 2>nul || (echo [x] git nahi mila. https://git-scm.com/download/win se install karo. & pause & exit /b 1)

if not exist ".git" (
  echo [timu] git repo initialise kar raha hoon...
  git init
  git branch -M main
)
git add -A
git -c user.name="%OWNER%" commit -m "Timu v2 - extraction engine, transport layer, Streamlit + Flask UIs, tests" || echo [i] commit karne ke liye kuch naya nahi tha
git remote remove origin >nul 2>nul
git remote add origin https://github.com/%OWNER%/%REPO%.git
echo.
echo [timu] push kar raha hoon -^> https://github.com/%OWNER%/%REPO%
echo        GitHub username/password poochhe to password ki jagah apna PERSONAL ACCESS TOKEN daalo.
echo.
git push -u origin main
if errorlevel 1 (
  echo.
  echo [x] push fail hua. Aksar wajah: token me "Contents: write" nahi hai, ya repo me pehle se commits hain.
  echo     Force karna ho to:  git push -u origin main --force
) else (
  echo.
  echo [ok] ho gaya. Ab Streamlit pe deploy:
  echo      https://share.streamlit.io  -^>  New app  -^>  %OWNER%/%REPO%  -^>  main  -^>  streamlit_app.py
)
pause
