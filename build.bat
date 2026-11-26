@echo off
REM Build NtfsAudit.exe tren may moi. Yeu cau: da cai Python 3.9+ ban 64-bit.
setlocal
cd /d "%~dp0"

set "PY="
python --version >nul 2>nul && set "PY=python"
if not defined PY py -3 --version >nul 2>nul && set "PY=py -3"
if not defined PY (
    echo [LOI] Khong tim thay Python. Cai Python tu https://www.python.org/downloads/ ^(tick "Add python.exe to PATH"^).
    exit /b 1
)
echo Dung Python:
%PY% --version

if not exist ".venv\Scripts\python.exe" (
    echo === Tao moi truong ao .venv ===
    %PY% -m venv .venv || exit /b 1
)

echo === Cai thu vien ===
".venv\Scripts\python.exe" -m pip install --upgrade pip >nul
".venv\Scripts\python.exe" -m pip install -r requirements.txt || exit /b 1

echo === Build exe ===
".venv\Scripts\pyinstaller.exe" --noconfirm --clean --onefile --windowed --uac-admin --name NtfsAudit main.py || exit /b 1

echo.
echo === XONG: %~dp0dist\NtfsAudit.exe ===
endlocal
