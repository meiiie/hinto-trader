@echo off
REM Dry-Run Mode Test Script
REM Activates venv and runs NEW LIVE system in dry-run mode

echo ================================================================================
echo DRY-RUN MODE TEST - NEW LIVE SYSTEM
echo ================================================================================
echo.

REM Check if venv exists
if not exist "..\.venv\Scripts\activate.bat" (
    echo ERROR: Virtual environment not found at ..\.venv
    echo Please create venv first: python -m venv .venv
    pause
    exit /b 1
)

echo Activating virtual environment...
call "..\.venv\Scripts\activate.bat"

echo.
echo Checking python-binance installation...
python -c "import binance" 2>nul
if errorlevel 1 (
    echo WARNING: python-binance not installed
    echo System will use fallback symbols
    echo.
    echo To install: pip install python-binance
    echo.
    timeout /t 3
) else (
    echo OK: python-binance is installed
)

echo.
echo ================================================================================
echo STARTING DRY-RUN MODE
echo ================================================================================
echo Configuration:
echo   - Top 5 symbols by volume
echo   - Balance: $34
echo   - Leverage: 10x
echo   - Max Positions: 2
echo   - Mode: DRY RUN (paper trading)
echo.
echo Press Ctrl+C to stop
echo ================================================================================
echo.

REM Run dry-run mode
python run_live_trading.py --dry-run --top 5 --balance 34 --leverage 10 --max-pos 2

echo.
echo ================================================================================
echo DRY-RUN MODE STOPPED
echo ================================================================================
pause
