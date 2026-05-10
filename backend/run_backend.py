"""
Run Backend Server

SOTA: Strict Startup Mode
- Requires ENV variable (paper/testnet/live)
- Validates API keys match environment
- Shows clear environment indicator

Usage:
    ENV=paper python run_backend.py    # Safe development
    ENV=testnet python run_backend.py  # Binance testnet
    ENV=live python run_backend.py     # PRODUCTION (real money!)
"""

import os
import sys
import logging
from pathlib import Path
# Note: load_dotenv removed - using centralized config_loader instead

# SOTA: File logging for sidecar debugging (console hidden by Tauri)
def setup_file_logging():
    """Setup file logging to AppData for debugging when console is hidden."""
    try:
        if os.name == 'nt':
            log_dir = Path(os.environ.get('APPDATA', Path.home())) / "Hinto" / "logs"
        else:
            log_dir = Path.home() / ".config" / "Hinto" / "logs"

        log_dir.mkdir(parents=True, exist_ok=True)
        # SOTA: Include ENV in log filename for clarity
        env_mode = os.getenv("ENV", "unknown").lower().strip()
        log_file = log_dir / f"backend_startup_{env_mode}.log"

        # Configure file handler
        file_handler = logging.FileHandler(log_file, mode='w', encoding='utf-8')
        file_handler.setLevel(logging.DEBUG)
        file_handler.setFormatter(logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
        ))

        # Add to root logger
        logging.getLogger().addHandler(file_handler)
        logging.getLogger().setLevel(logging.DEBUG)

        logging.info(f"[SIDECAR] Log file: {log_file}")
        logging.info(f"[SIDECAR] Working directory: {os.getcwd()}")
        logging.info(f"[SIDECAR] sys.frozen: {getattr(sys, 'frozen', False)}")
        logging.info(f"[SIDECAR] sys.executable: {sys.executable}")

        return str(log_file)
    except Exception as e:
        print(f"[WARN] Could not setup file logging: {e}")
        return None

# Setup logging first
LOG_FILE = setup_file_logging()

# SOTA: Use centralized config loader (replaces scattered load_dotenv calls)
from src.config_loader import load_config, get_config
CONFIG = load_config()

# Log config loading result
import logging
logger = logging.getLogger(__name__)
logger.info(f"[STARTUP] Config loaded: first_run={CONFIG.first_run}, env_mode={CONFIG.env_mode}")
logger.info(f"[STARTUP] Config path: {CONFIG.config_path}")


def validate_startup():
    """
    Validate environment configuration before starting server.

    SOTA: Fails fast if configuration is invalid.
    """
    # Get environment - STRIP to handle trailing whitespace from .env files
    env = os.getenv("ENV", "").lower().strip()

    # SOTA: Require explicit ENV for production safety
    if not env:
        print("\n" + "=" * 60)
        print("[ERROR] ENV variable not set!")
        print("=" * 60)
        print("\nUsage:")
        print("  set ENV=paper && python run_backend.py    (Windows)")
        print("  ENV=paper python run_backend.py           (Linux/Mac)")
        print("\nOptions: paper, testnet, live")
        print("=" * 60 + "\n")
        sys.exit(1)

    if env not in ["paper", "testnet", "live"]:
        print(f"\n[ERROR] Invalid ENV '{env}'")
        print("Valid options: paper, testnet, live")
        sys.exit(1)

    # Validate keys for environment
    if env == "testnet":
        key = os.getenv("BINANCE_TESTNET_API_KEY", "")
        if not key:
            print("[ERROR] BINANCE_TESTNET_API_KEY not set!")
            sys.exit(1)
    elif env == "live":
        key = os.getenv("BINANCE_API_KEY", "")
        if not key:
            print("[ERROR] BINANCE_API_KEY not set for live mode!")
            sys.exit(1)

        # SOTA: Skip confirmation in Docker/non-interactive mode
        # Check if running in Docker or non-interactive terminal
        is_docker = os.path.exists('/.dockerenv') or os.getenv('DOCKER_CONTAINER', '') == 'true'
        is_interactive = sys.stdin.isatty()

        if is_docker or not is_interactive:
            print("\n" + "[!]" * 20)
            print("[WARNING] LIVE MODE - REAL MONEY!")
            print("[!]" * 20)
            print("[AUTO-CONFIRM] Running in Docker/non-interactive mode")
        else:
            # Extra confirmation for production (interactive mode only)
            print("\n" + "[!]" * 20)
            print("[WARNING] LIVE MODE - REAL MONEY!")
            print("[!]" * 20)
            confirm = input("\nType 'CONFIRM' to continue: ").strip()
            if confirm != "CONFIRM":
                print("[ABORTED]")
                sys.exit(0)

    # Show startup banner
    banners = {
        "paper": ("[PAPER]", "Simulated trading - No real money"),
        "testnet": ("[TESTNET]", "Binance Testnet - Demo money"),
        "live": ("[LIVE]", "PRODUCTION - Real money at risk!")
    }

    icon, desc = banners[env]

    print("\n" + "=" * 60)
    print(f"{icon} - {desc}")
    print(f"Database: data/{env}/trading_system.db")
    print("=" * 60 + "\n")

    return env


if __name__ == "__main__":
    import traceback
    try:
        print("Starting backend initialization...")
        print("Importing modules...")
        import uvicorn
        import argparse

        # Parse command line args
        print("Parsing arguments...")
        parser = argparse.ArgumentParser(description="Hinto Backend Server")
        parser.add_argument("--reload", action="store_true",
                           help="Enable hot reload (development mode, unstable WS)")
        args = parser.parse_args()

        # Validate before starting - ENABLED for safety
        env = validate_startup()

        # SOTA FIX: Default NO RELOAD for stability
        # Only enable reload if explicitly requested
        use_reload = args.reload

        if use_reload:
            print("[WARN] Hot reload enabled (WebSocket may be unstable)")
            print("Starting uvicorn (reload mode)...")
            # Reload requires string import
            uvicorn.run(
                "src.api.main:app",
                host="0.0.0.0",
                port=8000,
                reload=True,
                log_level="info"
            )
        else:
            print("[OK] Production mode: stable WebSocket connections")

            # SOTA FIX: Force logging config BEFORE importing app
            # This ensures app logs are visible in console
            import logging
            import sys

            # Force all loggers to INFO level with console output
            logging.basicConfig(
                level=logging.INFO,
                format='%(asctime)s - %(levelname)s - %(message)s',
                handlers=[logging.StreamHandler(sys.stdout)],
                force=True  # Override any existing config!
            )

            # Ensure app-specific loggers work
            for logger_name in ['src.api.main', 'uvicorn', 'uvicorn.access', 'uvicorn.error']:
                logging.getLogger(logger_name).setLevel(logging.INFO)

            print("[OK] Logging configured")
            print("Importing app...")
            # Import app directly for stability (like run_real_backend.py)
            from src.api.main import app
            print("[OK] App imported successfully")
            print("Starting uvicorn (production mode)...")
            uvicorn.run(
                app,
                host="0.0.0.0",  # SOTA: Allow network access
                port=8000,
                log_level="info",
                log_config=None  # SOTA FIX: Don't override app logging
            )
    except Exception as e:
        print("\n[FATAL ERROR] Backend crashed on startup:")
        traceback.print_exc()
        input("Press Enter to exit...")
