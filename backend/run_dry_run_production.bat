@echo off
REM Production-Ready Dry-Run Test Script
REM Tests with PRODUCTION configuration (50 symbols, 5 max positions)

echo ================================================================================
echo DRY-RUN MODE - PRODUCTION CONFIGURATION TEST
echo ================================================================================
echo.
echo This script tests the system with PRODUCTION settings:
echo   - Top 50 symbols by volume (same as LIVE)
echo   - Max 5 concurrent positions (same as LIVE)
echo   - All production features enabled
echo.
echo This is the FINAL test before going LIVE!
echo ================================================================================
echo.

REM Check if venv exists
if not exist "..\.venv\Scripts\activate.bat" (
    echo ERROR: Virtual environment not found at ..\.venv
    echo Please create venv first: python -m venv .venv
    pause
    exit /b 1
)

echo [1/4] Activating virtual environment...
call "..\.venv\Scripts\activate.bat"
echo OK: Virtual environment activated
echo.

echo [2/4] Checking python-binance installation...
python -c "import binance" 2>nul
if errorlevel 1 (
    echo WARNING: python-binance not installed
    echo.
    echo For PRODUCTION testing, python-binance is HIGHLY RECOMMENDED
    echo It enables dynamic top 50 symbol selection by volume
    echo.
    echo Install now? (Y/N)
    set /p INSTALL_BINANCE=
    if /i "%INSTALL_BINANCE%"=="Y" (
        echo Installing python-binance...
        pip install python-binance
        echo.
    ) else (
        echo Continuing without python-binance (will use fallback symbols)
        echo.
    )
) else (
    echo OK: python-binance is installed
    echo.
)

echo [3/4] Checking API keys in .env file...
python -c "from src.config_loader import load_config; cfg = load_config(); print('OK' if hasattr(cfg, 'binance_api_key') and cfg.binance_api_key else 'MISSING')" 2>nul
if errorlevel 1 (
    echo WARNING: Could not verify API keys
    echo Make sure .env file exists with BINANCE_API_KEY and BINANCE_API_SECRET
    echo.
) else (
    echo OK: API keys found in .env
    echo.
)

echo [4/4] Starting DRY-RUN with PRODUCTION configuration...
echo.
echo ================================================================================
echo PRODUCTION CONFIGURATION
echo ================================================================================
echo   Top Symbols: 50 (dynamic by 24h volume)
echo   Balance: $34 (for testing)
echo   Leverage: 10x
echo   Max Positions: 5 (PRODUCTION setting)
echo   Risk per Trade: 1.0%%
echo   Order TTL: 50 minutes
echo   Frequency Limit: 10 trades/day, 100 trades/month
echo   Spread Cost: ENABLED
echo   Smart Recycling: OFF (use --zombie-killer to enable)
echo   Full TP: OFF (use --full-tp to enable)
echo.
echo Mode: DRY RUN (paper trading - no real orders)
echo.
echo Press Ctrl+C to stop gracefully
echo ================================================================================
echo.

REM Run with production config
python run_live_trading.py --dry-run --top 50 --balance 34 --leverage 10 --max-pos 5

echo.
echo ================================================================================
echo DRY-RUN STOPPED
echo ================================================================================
echo.
echo Check logs at: logs\live_trading_*.log
echo Check trades at: live_trades_*.csv (if any)
echo.
pause
