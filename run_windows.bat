@echo off
setlocal
cd /d "%~dp0"
where py >nul 2>nul
if %ERRORLEVEL% EQU 0 (
    py -3 -m pip install -r requirements.txt
    if errorlevel 1 goto :err
    py -3 -m streamlit run app.py --server.address 127.0.0.1 --server.port 8501
) else (
    python -m pip install -r requirements.txt
    if errorlevel 1 goto :err
    python -m streamlit run app.py --server.address 127.0.0.1 --server.port 8501
)
if errorlevel 1 goto :err
goto :end
:err
echo.
echo There was a startup error. Please send the lines above to support.
:end
pause
