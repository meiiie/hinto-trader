@echo off
REM Production Dry-Run with ALL Features Enabled
REM Tests with zombie-killer (smart recycling) + full TP at TP1

echo ================================================================================
echo DRY-RUN MODE - FULL FEATURES TEST
echo ================================================================================
echo.
echo This script tests ALL production features:
echo   - Top 50 symbols by volume
echo   - Max 5 concurrent positions
echo   - Zombie Killer (smart recycling) ENABLED
echo   - Full TP at TP1 (100%% close) ENABLED
echo.
echo ================================================================================
echo.

REM Check if venv exists
if not exist "..\.venv\Scripts\activate.bat" (
    echo ERROR: Virtual environment not found at ..\.venv
    pause
    exit /b 1
)

echo Activating virtual environment...
call "..\.venv\Scripts\activate.bat"

echo.
echo ================================================================================
echo FULL FEATURES CONFIGURATION
echo ================================================================================
echo   Top Symbols: 50
echo   Max Positions: 5
echo   Zombie Killer: ENABLED (recycle underperforming positions)
echo   Full TP: ENABLED (close 100%% at TP1 instead of 60%%)
echo   Balance: $34
echo   Leverage: 10x
echo   Order TTL: 50 minutes
echo.
echo Mode: DRY RUN (paper trading)
echo.
echo Press Ctrl+C to stop
echo ================================================================================
echo.

REM Run with all features
python run_live_trading.py --dry-run --top 50 --balance 34 --leverage 10 --max-pos 5 --zombie-killer --full-tp

echo.
echo ================================================================================
echo DRY-RUN STOPPED
echo ================================================================================
pause
