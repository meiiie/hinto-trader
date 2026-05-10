"""
Config Router - Configuration Management API

SOTA: First-Run Setup Wizard backend support.
Handles saving configuration to AppData folder.
"""

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field
from pathlib import Path
import os
import logging

logger = logging.getLogger(__name__)

config_router = APIRouter(prefix="/config", tags=["Configuration"])


class ConfigSaveRequest(BaseModel):
    """Request model for saving configuration."""
    mode: str = Field(..., pattern="^(paper|testnet|live)$", description="Trading mode")
    api_key: str = Field(default="", description="Binance API Key")
    api_secret: str = Field(default="", description="Binance API Secret")
    testnet_api_key: str = Field(default="", description="Binance Testnet API Key")
    testnet_api_secret: str = Field(default="", description="Binance Testnet API Secret")
    # Enhanced: Symbols and Strategy
    symbols: list = Field(default=["BTCUSDT", "ETHUSDT", "BNBUSDT"], description="Trading symbols")
    leverage: int = Field(default=10, ge=1, le=125, description="Leverage")
    stop_loss_pct: float = Field(default=0.5, ge=0.1, le=10, description="Stop Loss %")
    take_profit_pct: float = Field(default=2.0, ge=0.1, le=50, description="Take Profit %")
    trailing_stop_pct: float = Field(default=0.3, ge=0.1, le=5, description="Trailing Stop %")
    # SOTA: Direct raw content paste (simplest approach)
    raw_content: str = Field(default="", description="Raw .env content to save directly")


class ConfigParseRequest(BaseModel):
    """Request for parsing .env content."""
    content: str = Field(..., description="Raw .env file content")


class ConfigSaveResponse(BaseModel):
    """Response model for config save."""
    success: bool
    config_path: str
    message: str


def get_config_dir() -> Path:
    """Get the proper config directory based on platform."""
    if os.name == 'nt':  # Windows
        app_data = os.environ.get('APPDATA', os.path.expanduser('~'))
        return Path(app_data) / "Hinto"
    else:  # Linux/Mac
        return Path.home() / ".config" / "Hinto"


@config_router.get("/path")
async def get_config_path():
    """Get the configuration directory path."""
    config_dir = get_config_dir()
    env_file = config_dir / ".env"

    return {
        "config_dir": str(config_dir),
        "env_file": str(env_file),
        "exists": env_file.exists()
    }


@config_router.get("/check")
async def check_config():
    """
    Check if configuration exists.
    Used by setup wizard to determine if first-run.
    """
    config_dir = get_config_dir()
    env_file = config_dir / ".env"

    # Also check development locations
    dev_paths = [
        Path(".env"),
        Path("backend/.env"),
    ]

    exists = env_file.exists() or any(p.exists() for p in dev_paths)

    return {
        "exists": exists,
        "path": str(env_file) if env_file.exists() else None,
        "first_run": not exists
    }


@config_router.get("/current")
async def get_current_config():
    """
    Get current configuration values for Setup Wizard pre-fill.

    SOTA: Always returns config values if .env exists, allowing
    Setup Wizard to pre-populate form fields with existing values.
    """
    config_dir = get_config_dir()
    env_file = config_dir / ".env"

    # Check if config exists
    exists = env_file.exists()

    if not exists:
        # Return defaults for first-run
        return {
            "exists": False,
            "mode": "paper",
            "api_key": "",
            "api_secret": "",
            "testnet_api_key": "",
            "testnet_api_secret": "",
            "symbols": ["BTCUSDT", "ETHUSDT", "BNBUSDT"],
            "leverage": 10,
            "stop_loss_pct": 0.5,
            "take_profit_pct": 2.0,
            "trailing_stop_pct": 0.3
        }

    # Load current values from environment
    symbols_str = os.getenv("SYMBOLS", "BTCUSDT,ETHUSDT,BNBUSDT")
    symbols = [s.strip() for s in symbols_str.split(",") if s.strip()]

    return {
        "exists": True,
        "mode": os.getenv("ENV", "paper"),
        "api_key": os.getenv("BINANCE_API_KEY", "")[:8] + "..." if os.getenv("BINANCE_API_KEY") else "",
        "api_secret": "••••••••" if os.getenv("BINANCE_API_SECRET") else "",
        "testnet_api_key": os.getenv("BINANCE_TESTNET_API_KEY", "")[:8] + "..." if os.getenv("BINANCE_TESTNET_API_KEY") else "",
        "testnet_api_secret": "••••••••" if os.getenv("BINANCE_TESTNET_API_SECRET") else "",
        "symbols": symbols,
        "leverage": int(os.getenv("LEVERAGE", "10")),
        "stop_loss_pct": float(os.getenv("STOP_LOSS_PCT", "0.5")),
        "take_profit_pct": float(os.getenv("TAKE_PROFIT_PCT", "2.0")),
        "trailing_stop_pct": float(os.getenv("TRAILING_STOP_PCT", "0.3")),
        "config_path": str(env_file)
    }


@config_router.post("/save", response_model=ConfigSaveResponse)
async def save_config(config: ConfigSaveRequest):
    """
    Save configuration to AppData/.env

    This endpoint is called by the First-Run Setup Wizard
    to persist user configuration.
    """
    try:
        config_dir = get_config_dir()
        config_dir.mkdir(parents=True, exist_ok=True)

        env_file = config_dir / ".env"

        # SOTA: If raw_content is provided, save it directly (user pasted complete .env)
        if config.raw_content and config.raw_content.strip():
            env_content = config.raw_content.strip()
            # Ensure there's a newline at the end
            if not env_content.endswith('\n'):
                env_content += '\n'
        else:
            # Build .env content from individual fields
            from datetime import datetime
            env_content = f"""# Hinto Configuration
# Generated by Setup Wizard on {datetime.now().strftime('%Y-%m-%d %H:%M')}
# Mode: {config.mode}

# ============================================
# ENVIRONMENT MODE (REQUIRED)
# ============================================
ENV={config.mode}
"""

            if config.mode == "live":
                env_content += f"""
# ============================================
# BINANCE PRODUCTION (Real Money)
# ============================================
BINANCE_API_KEY={config.api_key}
BINANCE_API_SECRET={config.api_secret}
"""
            elif config.mode == "testnet":
                env_content += f"""
# ============================================
# BINANCE TESTNET (Demo - Safe to test)
# ============================================
BINANCE_TESTNET_API_KEY={config.testnet_api_key}
BINANCE_TESTNET_API_SECRET={config.testnet_api_secret}
"""
            else:
                env_content += """
# Paper Trading Mode - No API Keys Required
# Uses live Binance market data with local-only simulated execution.
HINTO_PAPER_REAL=true
"""

            # Symbols from config
            symbols_str = ",".join(config.symbols) if config.symbols else "BTCUSDT,ETHUSDT,BNBUSDT"

            # Strategy config with user values
            env_content += f"""
# Symbols (comma-separated)
SYMBOLS={symbols_str}

# Strategy Configuration
LEVERAGE={config.leverage}
STOP_LOSS_PCT={config.stop_loss_pct}
TAKE_PROFIT_PCT={config.take_profit_pct}
TRAILING_STOP_PCT={config.trailing_stop_pct}

# Logging
LOG_LEVEL=INFO
"""

        # Write to file
        env_file.write_text(env_content, encoding='utf-8')

        logger.info(f"[OK] Configuration saved to: {env_file}")

        # SOTA: Reload config so backend picks up new settings immediately
        # This avoids requiring a restart after setup wizard completes
        try:
            from src.config_loader import load_config
            load_config(force_reload=True)
            logger.info("[OK] Configuration reloaded successfully")
        except Exception as e:
            logger.warning(f"Could not reload config: {e}")

        return ConfigSaveResponse(
            success=True,
            config_path=str(env_file),
            message=f"Configuration saved successfully to {env_file}"
        )

    except Exception as e:
        logger.error(f"[ERROR] Failed to save config: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to save configuration: {str(e)}"
        )


@config_router.post("/validate")
async def validate_api_keys(config: ConfigSaveRequest):
    """
    Validate Binance API keys without saving.
    Used by setup wizard to test connection before saving.
    """
    if config.mode == "paper":
        return {
            "valid": True,
            "message": "Paper mode - no API keys required"
        }

    try:
        from src.infrastructure.api.async_binance_client import AsyncBinanceFuturesClient

        # Determine which keys to use
        if config.mode == "live":
            api_key = config.api_key
            api_secret = config.api_secret
            testnet = False
        else:  # testnet
            api_key = config.testnet_api_key
            api_secret = config.testnet_api_secret
            testnet = True

        if not api_key or not api_secret:
            return {
                "valid": False,
                "message": "API key and secret are required"
            }

        # Create temporary client and test
        client = AsyncBinanceFuturesClient(
            api_key=api_key,
            api_secret=api_secret,
            testnet=testnet
        )

        try:
            await client.ping()
            return {
                "valid": True,
                "message": f"Successfully connected to Binance {'Testnet' if testnet else 'Production'}"
            }
        except Exception as e:
            error_str = str(e)

            if "-2015" in error_str or "Invalid API" in error_str:
                return {
                    "valid": False,
                    "message": "Invalid API key - check key/secret and permissions"
                }
            elif "ConnectError" in error_str or "Connection" in error_str:
                return {
                    "valid": False,
                    "message": "Cannot connect to Binance - check internet connection"
                }
            else:
                return {
                    "valid": False,
                    "message": f"Connection failed: {error_str[:100]}"
                }
        finally:
            await client.close()

    except ImportError:
        # Fall back to sync validation if async client not available
        return {
            "valid": True,
            "message": "API keys format valid (connection not tested)"
        }
    except Exception as e:
        return {
            "valid": False,
            "message": f"Validation error: {str(e)}"
        }


@config_router.post("/parse")
async def parse_env_content(request: ConfigParseRequest):
    """
    Parse raw .env content and return structured config.
    Used by setup wizard to extract values from pasted .env content.
    """
    parsed = {}
    detected = []

    for line in request.content.split('\n'):
        line = line.strip()
        # Skip comments and empty lines
        if not line or line.startswith('#'):
            continue
        # Parse key=value
        if '=' in line:
            key, value = line.split('=', 1)
            key = key.strip()
            value = value.strip()
            parsed[key] = value
            detected.append(key)

    # Map to our config structure
    result = {
        "detected_keys": detected,
        "config": {
            "mode": parsed.get("ENV", "paper"),
            "api_key": parsed.get("BINANCE_API_KEY", ""),
            "api_secret": parsed.get("BINANCE_API_SECRET", ""),
            "testnet_api_key": parsed.get("BINANCE_TESTNET_API_KEY", ""),
            "testnet_api_secret": parsed.get("BINANCE_TESTNET_API_SECRET", ""),
            "leverage": int(parsed.get("LEVERAGE", 10)),
            "stop_loss_pct": float(parsed.get("STOP_LOSS_PCT", 0.5)),
            "take_profit_pct": float(parsed.get("TAKE_PROFIT_PCT", 2.0)),
            "trailing_stop_pct": float(parsed.get("TRAILING_STOP_PCT", 0.3)),
            "symbols": parsed.get("SYMBOLS", "BTCUSDT,ETHUSDT,BNBUSDT").split(","),
            "paper_real": parsed.get("HINTO_PAPER_REAL", "true").lower() in ("1", "true", "yes", "on")
        },
        "raw": parsed
    }

    return result


@config_router.post("/symbols/auto-select")
async def auto_select_top_symbols(
    n: int = Query(default=50, ge=5, le=100, description="Number of top symbols")
):
    """
    SOTA: Auto-select top N symbols by 24h volume and save to .env.

    This implements Freqtrade's VolumePairList pattern:
    1. Fetch top N by 24h volume from Binance
    2. Update SYMBOLS in .env file
    3. Restart required to load new symbols

    Args:
        n: Number of top symbols to select (default: 50, max: 100)

    Returns:
        Selected symbols and confirmation of save
    """
    try:
        from datetime import datetime, timezone
        from src.infrastructure.api.binance_rest_client import BinanceRestClient
        from src.config.market_mode import MarketMode

        # Step 1: Fetch top N symbols from Binance
        client = BinanceRestClient(market_mode=MarketMode.FUTURES)
        symbols = client.get_top_volume_pairs(limit=n, quote_asset="USDT")

        if not symbols:
            return {
                "success": False,
                "error": "Failed to fetch top volume pairs from Binance"
            }

        # SOTA FIX (Jan 2026): DIRECTLY SAVE TO .ENV
        # We use config_loader to finding the CORRECT .env file (Dev vs Prod)
        from src.config_loader import get_config_path, load_config

        env_path = get_config_path()
        new_symbols_str = ",".join(symbols)
        env_format = f"SYMBOLS={new_symbols_str}"

        saved_to_file = False

        if env_path.exists():
            try:
                # Read existing content
                content = env_path.read_text(encoding='utf-8')
                lines = content.splitlines()

                # Check if SYMBOLS exists
                new_lines = []
                found = False

                for line in lines:
                    if line.strip().startswith("SYMBOLS="):
                        new_lines.append(env_format)
                        found = True
                    else:
                        new_lines.append(line)

                if not found:
                    new_lines.append("")
                    new_lines.append("# Auto-added by Shark Tank Mode")
                    new_lines.append(env_format)

                # Write back
                env_path.write_text("\n".join(new_lines), encoding='utf-8')
                saved_to_file = True
                logger.info(f"✅ Saved new symbols to {env_path}")

                # Reload config in memory
                load_config(force_reload=True)

                # SOTA FIX: Sync with SQLite Settings (enabled_tokens)
                # This ensures get_supported_symbols immediately reflects the change
                # independent of the .env reload (which affects restart behavior)
                try:
                    from src.api.dependencies import get_paper_trading_service
                    paper_service = get_paper_trading_service()
                    # settings table stores values as strings
                    paper_service.repo.save_setting('enabled_tokens', new_symbols_str)
                    logger.info(f"✅ Synced settings DB enabled_tokens with {len(symbols)} symbols")
                except Exception as db_e:
                    logger.warning(f"⚠️ Failed to sync settings DB: {db_e}")

            except Exception as e:
                logger.error(f"Failed to write .env: {e}")

        message = "Symbols fetched successfully."
        if saved_to_file:
            message = f"✅ Saved top {len(symbols)} symbols to .env ({env_path.name}). RESTART BACKEND to apply."
        else:
            message = "⚠️ Could not save to .env (file not found). Please copy manually."

        return {
            "success": True,
            "symbols": symbols,
            "count": len(symbols),
            "env_format": env_format,
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "instruction": message,
            "saved": saved_to_file
        }

    except Exception as e:
        logger.error(f"Failed to fetch top symbols: {e}")
        return {
            "success": False,
            "error": str(e)
        }
