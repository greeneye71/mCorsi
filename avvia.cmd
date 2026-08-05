@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"

set "MODALITA=%~1"
if "%MODALITA%"=="" set "MODALITA=test"
if /I "%MODALITA%"=="sviluppo" set "MODALITA=test"
if /I "%MODALITA%"=="production" set "MODALITA=produzione"
if /I not "%MODALITA%"=="test" if /I not "%MODALITA%"=="produzione" goto :uso

set "PORTA=%~2"
if "%PORTA%"=="" if /I "%MODALITA%"=="test" set "PORTA=%MCORSI_TEST_PORT%"
if "%PORTA%"=="" if /I "%MODALITA%"=="produzione" set "PORTA=%MCORSI_WEB_PORT%"
if "%PORTA%"=="" if /I "%MODALITA%"=="test" set "PORTA=5100"
if "%PORTA%"=="" if /I "%MODALITA%"=="produzione" set "PORTA=8000"
for /f "delims=0123456789" %%A in ("%PORTA%") do goto :porta_non_valida
if %PORTA% LSS 1 goto :porta_non_valida
if %PORTA% GTR 65535 goto :porta_non_valida

echo.
echo ========================================
echo          Avvio di mCorsi
echo ========================================
echo Modalita: %MODALITA% - Porta: %PORTA%
echo.

if not exist ".venv\Scripts\python.exe" (
    echo [1/4] Creazione dell'ambiente Python...
    where py >nul 2>nul
    if errorlevel 1 (
        python -m venv .venv
    ) else (
        py -3 -m venv .venv
    )
    if errorlevel 1 goto :errore_python
) else (
    echo [1/4] Ambiente Python gia presente.
)

set "PYTHON=%CD%\.venv\Scripts\python.exe"
if /I "%MODALITA%"=="test" set "MCORSI_ENV=development"
if /I "%MODALITA%"=="produzione" set "MCORSI_ENV=production"
set "MCORSI_PORT=%PORTA%"
set "MCORSI_WEB_PORT=%PORTA%"

echo [2/4] Controllo delle dipendenze...
"%PYTHON%" -m pip install --disable-pip-version-check -q -r requirements.txt
if errorlevel 1 goto :errore

echo [3/4] Aggiornamento del database...
"%PYTHON%" -m flask --app wsgi init-db
if errorlevel 1 goto :errore

echo [4/4] Controllo dell'amministratore...
"%PYTHON%" -m flask --app wsgi admin bootstrap
if errorlevel 1 goto :errore

echo.
echo mCorsi e disponibile all'indirizzo:
echo.
echo     http://127.0.0.1:%PORTA%
echo.
echo Premi CTRL+C per arrestare il programma.
echo ========================================
echo.
if /I "%MODALITA%"=="produzione" (
    "%PYTHON%" -m waitress --listen=127.0.0.1:%PORTA% --threads=4 wsgi:app
) else (
    "%PYTHON%" wsgi.py
)
goto :fine

:uso
echo Uso: avvia.cmd [test^|produzione] [porta]
echo Esempi:
echo   avvia.cmd test 5100
echo   avvia.cmd produzione 8000
exit /b 2

:porta_non_valida
echo ERRORE: la porta deve essere un numero compreso tra 1 e 65535.
exit /b 2

:errore_python
echo.
echo ERRORE: Python 3 non e installato o non e disponibile nel PATH.
echo Scaricalo da https://www.python.org/downloads/
goto :pausa_errore

:errore
echo.
echo ERRORE: preparazione o avvio non riuscito.
echo Controlla i messaggi visualizzati sopra.

:pausa_errore
pause
exit /b 1

:fine
endlocal
