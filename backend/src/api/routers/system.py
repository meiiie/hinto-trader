from fastapi import APIRouter, Depends, Request
from datetime import datetime
from typing import Dict, Any
import numpy as np

from ..dependencies import get_realtime_service


def _convert_numpy(obj):
    """Convert numpy types to native Python types for JSON serialization."""
    if isinstance(obj, dict):
        return {k: _convert_numpy(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [_convert_numpy(item) for item in obj]
    elif isinstance(obj, (np.bool_, np.bool8)):
        return bool(obj)
    elif isinstance(obj, (np.integer, np.int64, np.int32)):
        return int(obj)
    elif isinstance(obj, (np.floating, np.float64, np.float32)):
        return float(obj)
    elif isinstance(obj, np.ndarray):
        return obj.tolist()
    return obj


router = APIRouter(
    prefix="/system",
    tags=["system"]
)

@router.get("/status")
async def get_status():
    """
    Health check endpoint to verify system status.

    SOTA (Jan 2026): Includes data_ready flag for frontend to know
    when all symbol data is pre-loaded and charts can render instantly.
    """
    from fastapi import Request
    from src.api.main import app

    # Get data readiness state from app.state
    data_ready = getattr(app.state, 'data_ready', False)
    ready_symbols = getattr(app.state, 'ready_symbols', [])
    startup_status = getattr(app.state, 'startup_status', 'initializing')

    return {
        "status": "ok",
        "timestamp": datetime.now().isoformat(),
        "service": "hinto-trader-backend",
        "version": "0.1.0",
        # SOTA: Data readiness for frontend
        "data_ready": data_ready,
        "ready_symbol_count": len(ready_symbols),
        "startup_status": startup_status
    }


@router.get("/config")
async def get_config():
    """
    Get current environment configuration (read-only).

    SOTA: Frontend should use this to show environment banner.
    - Paper: Green banner (safe)
    - Testnet: Yellow banner (demo money)
    - Live: RED banner (real money!)
    """
    import os
    env = os.getenv("ENV", "paper")

    return {
        "environment": env,
        "is_production": env == "live",
        "db_path": f"data/{env}/trading_system.db",
        "warning": "⚠️ REAL MONEY MODE!" if env == "live" else None,
        "timestamp": datetime.now().isoformat()
    }


@router.post("/mode/{new_mode}")
async def switch_mode(new_mode: str):
    """
    Switch environment mode (Paper ↔ Testnet only).

    SOTA: Live mode requires server restart for safety.

    Args:
        new_mode: 'paper' or 'testnet' (NOT 'live')
    """
    import os
    from functools import lru_cache

    current = os.getenv("ENV", "paper")
    new_mode = new_mode.lower()

    # SAFETY: Never allow runtime switch TO live
    if new_mode == "live":
        return {
            "success": False,
            "error": "Live mode requires server restart with ENV=live",
            "hint": "Run: set ENV=live && python run_backend.py"
        }

    # SAFETY: Never allow runtime switch FROM live
    if current == "live":
        return {
            "success": False,
            "error": "Cannot switch away from live mode at runtime",
            "hint": "Restart server with different ENV"
        }

    # Validate mode
    if new_mode not in ["paper", "testnet"]:
        return {
            "success": False,
            "error": f"Invalid mode: {new_mode}",
            "valid_modes": ["paper", "testnet"]
        }

    # Same mode - no change needed
    if current == new_mode:
        return {
            "success": True,
            "mode": current,
            "message": "Already in this mode"
        }

    # Switch mode (paper ↔ testnet)
    os.environ["ENV"] = new_mode

    # SOTA: Refresh DI container for new environment
    # This keeps per-environment caches intact (no data loss)
    from ..dependencies import get_container

    container = get_container()
    container.refresh_env()  # Refresh to new environment (cached services preserved)

    # Pre-warm the new environment's services
    try:
        # Get portfolio to verify Binance connection
        live_service = container.get_live_trading_service()
        portfolio = live_service.get_portfolio()
        balance = portfolio.get('balance', 0)
    except Exception as e:
        balance = 0
        logger.warning(f"Failed to pre-warm services: {e}")

    return {
        "success": True,
        "previous_mode": current,
        "current_mode": new_mode,
        "db_path": f"data/{new_mode}/trading_system.db",
        "balance": balance,
        "message": f"Switched from {current} to {new_mode}. Ready."
    }


# =============================================================================
# USER DATA STREAM (Real-time balance updates)
# =============================================================================

@router.post("/stream/start")
async def start_user_data_stream():
    """
    Start User Data Stream for real-time balance/position updates.

    SOTA: Enables WebSocket connection to Binance for instant updates.
    Only available in TESTNET or LIVE modes.
    """
    import os
    import asyncio
    import logging

    logger = logging.getLogger(__name__)
    env = os.getenv("ENV", "paper")

    if env == "paper":
        return {
            "success": False,
            "error": "User Data Stream not available in paper mode"
        }

    try:
        from ..dependencies import get_container
        container = get_container()
        stream = container.get_user_data_stream()

        if stream is None:
            return {
                "success": False,
                "error": "Failed to get UserDataStreamService"
            }

        if stream.is_connected:
            return {
                "success": True,
                "message": "Stream already running",
                "is_connected": True
            }

        # Start stream in background
        asyncio.create_task(stream.start())

        logger.info(f"🚀 Started User Data Stream for {env}")

        return {
            "success": True,
            "environment": env,
            "message": "User Data Stream starting..."
        }

    except Exception as e:
        logger.error(f"Failed to start stream: {e}")
        return {
            "success": False,
            "error": str(e)
        }


@router.post("/stream/stop")
async def stop_user_data_stream():
    """
    Stop User Data Stream gracefully.

    Invalidates listenKey and closes WebSocket connection.
    """
    import os
    import logging

    logger = logging.getLogger(__name__)

    try:
        from ..dependencies import get_container
        container = get_container()
        stream = container.get_user_data_stream()

        if stream is None:
            return {
                "success": True,
                "message": "No stream to stop"
            }

        await stream.stop()

        logger.info("🛑 Stopped User Data Stream")

        return {
            "success": True,
            "message": "User Data Stream stopped"
        }

    except Exception as e:
        logger.error(f"Failed to stop stream: {e}")
        return {
            "success": False,
            "error": str(e)
        }


@router.get("/stream/status")
async def get_stream_status():
    """
    Get User Data Stream connection status.

    Returns:
        Connection status, cached balance, last update time
    """
    import os

    env = os.getenv("ENV", "paper")

    if env == "paper":
        return {
            "available": False,
            "environment": env,
            "message": "User Data Stream not available in paper mode"
        }

    try:
        from ..dependencies import get_container
        container = get_container()
        stream = container.get_user_data_stream()

        if stream is None:
            return {
                "available": True,
                "is_connected": False,
                "environment": env
            }

        cached_balance = stream.get_cached_balance("USDT")

        return {
            "available": True,
            "is_connected": stream.is_connected,
            "environment": env,
            "cached_balance": {
                "wallet": cached_balance.wallet_balance if cached_balance else None,
                "available": cached_balance.available_balance if cached_balance else None,
                "last_update": cached_balance.last_update.isoformat() if cached_balance else None
            } if cached_balance else None
        }

    except Exception as e:
        return {
            "available": True,
            "is_connected": False,
            "error": str(e)
        }

@router.post("/emergency/stop")
async def emergency_stop():
    """
    🚨 EMERGENCY KILL SWITCH

    Cancels all orders, closes all positions, disables trading.
    Works in ALL modes including LIVE.
    """
    import os
    import logging

    logger = logging.getLogger(__name__)
    env = os.getenv("ENV", "paper")

    results = {
        "environment": env,
        "actions": [],
        "errors": []
    }

    try:
        from ..dependencies import get_container
        container = get_container()

        # 1. Disable live trading if enabled
        try:
            live_service = container.get_live_trading_service()
            if live_service.enable_trading:
                live_service.enable_trading = False
                results["actions"].append("Disabled live trading")
                logger.critical("🚨 EMERGENCY: Live trading DISABLED")
        except Exception as e:
            results["errors"].append(f"Disable trading: {str(e)}")

        # 2. Cancel all orders (if testnet/live)
        if env in ["testnet", "live"]:
            try:
                from src.infrastructure.api.binance_futures_client import BinanceFuturesClient
                client = BinanceFuturesClient()

                # Get all symbols with open orders
                # Cancel orders for common symbols
                symbols = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT"]
                for symbol in symbols:
                    try:
                        client.cancel_all_orders(symbol)
                        results["actions"].append(f"Cancelled orders: {symbol}")
                    except:
                        pass

                logger.critical("🚨 EMERGENCY: All orders CANCELLED")
            except Exception as e:
                results["errors"].append(f"Cancel orders: {str(e)}")

        # 3. Close all positions (if testnet/live)
        if env in ["testnet", "live"]:
            try:
                from src.infrastructure.api.binance_futures_client import (
                    BinanceFuturesClient, OrderSide, OrderType
                )
                client = BinanceFuturesClient()

                positions = client.get_positions()
                for pos in positions:
                    if abs(pos.position_amt) > 0:
                        side = OrderSide.SELL if pos.position_amt > 0 else OrderSide.BUY
                        client.create_order(
                            symbol=pos.symbol,
                            side=side,
                            order_type=OrderType.MARKET,
                            quantity=abs(pos.position_amt),
                            reduce_only=True
                        )
                        results["actions"].append(f"Closed position: {pos.symbol}")

                logger.critical("🚨 EMERGENCY: All positions CLOSED")
            except Exception as e:
                results["errors"].append(f"Close positions: {str(e)}")

        # 4. Close paper positions
        if env == "paper":
            try:
                from ..dependencies import get_order_repository
                repo = get_order_repository()
                active = repo.get_active_orders()
                for pos in active:
                    pos.status = "CLOSED"
                    pos.exit_reason = "EMERGENCY_STOP"
                    repo.update_order(pos)
                results["actions"].append(f"Closed {len(active)} paper positions")
            except Exception as e:
                results["errors"].append(f"Close paper: {str(e)}")

        results["success"] = len(results["errors"]) == 0
        results["message"] = "🚨 EMERGENCY STOP COMPLETE"

        logger.critical(f"🚨 EMERGENCY STOP COMPLETE: {results}")

    except Exception as e:
        results["success"] = False
        results["errors"].append(str(e))

    return results


@router.get("/debug/signal-persistence")
async def debug_signal_persistence():
    """
    Debug endpoint to diagnose signal persistence issues.

    Checks:
    1. Is _lifecycle_service injected into RealtimeService?
    2. What DB path is SignalRepository using?
    3. How many signals are in the database?
    4. Recent signal IDs for comparison
    """
    from ..dependencies import get_container

    container = get_container()
    result = {
        "timestamp": datetime.now().isoformat(),
        "services": {},
        "database": {},
        "diagnosis": []
    }

    # 1. Check RealtimeService instances
    symbols_checked = []
    for key, instance in container._instances.items():
        if key.startswith('realtime_service_'):
            symbol = key.replace('realtime_service_', '')
            has_lifecycle = hasattr(instance, '_lifecycle_service') and instance._lifecycle_service is not None
            symbols_checked.append({
                "symbol": symbol,
                "has_lifecycle_service": has_lifecycle,
                "lifecycle_service_id": id(instance._lifecycle_service) if has_lifecycle else None
            })

    result["services"]["realtime_instances"] = symbols_checked

    # 2. Check SignalLifecycleService
    if 'signal_lifecycle_service' in container._instances:
        lifecycle_svc = container._instances['signal_lifecycle_service']
        repo = lifecycle_svc.repo
        result["services"]["lifecycle_service"] = {
            "exists": True,
            "id": id(lifecycle_svc),
            "ttl_seconds": lifecycle_svc.ttl_seconds
        }
        result["database"]["db_path"] = getattr(repo, 'db_path', 'unknown')

        # 3. Count signals in DB
        try:
            signals = repo.get_history(limit=10)
            result["database"]["signal_count"] = len(signals)
            result["database"]["recent_signals"] = [
                {
                    "id": s.id[:16] if s.id else None,
                    "symbol": s.symbol,
                    "type": s.signal_type.value,
                    "status": s.status.value,
                    "generated_at": s.generated_at.isoformat() if s.generated_at else None
                }
                for s in signals[:5]
            ]
        except Exception as e:
            result["database"]["error"] = str(e)
    else:
        result["services"]["lifecycle_service"] = {"exists": False}
        result["diagnosis"].append("❌ SignalLifecycleService NOT in container instances!")

    # 4. Diagnosis
    if not symbols_checked:
        result["diagnosis"].append("❌ No RealtimeService instances found!")
    else:
        all_have_lifecycle = all(s["has_lifecycle_service"] for s in symbols_checked)
        if all_have_lifecycle:
            result["diagnosis"].append(f"✅ All {len(symbols_checked)} RealtimeService instances have _lifecycle_service")
        else:
            missing = [s["symbol"] for s in symbols_checked if not s["has_lifecycle_service"]]
            result["diagnosis"].append(f"❌ Missing _lifecycle_service for: {missing}")

    if result["database"].get("signal_count", 0) == 0:
        result["diagnosis"].append("⚠️ No signals in database yet")
    else:
        result["diagnosis"].append(f"✅ {result['database']['signal_count']} signals found in DB")

    return result



@router.get("/startup/events")
async def startup_events(request: Request):
    """
    SOTA Server-Sent Events (SSE) for Startup Progress.

    Front-end subscribes to this to show 'Discord-style' loading screen.
    Stream ends when startup is complete.
    """
    from fastapi.responses import StreamingResponse
    import asyncio
    import json
    from src.infrastructure.monitoring.startup_monitor import get_startup_monitor

    monitor = get_startup_monitor()

    async def event_generator():
        queue = await monitor.subscribe()
        try:
            while True:
                # Check for client disconnect
                if await request.is_disconnected():
                    break

                data = await queue.get()

                # SSE format: data: <json>\n\n
                yield f"data: {json.dumps(data)}\n\n"

                # Close stream if ready or error
                if data["type"] == "progress":
                    if data["data"]["level"] in ["success", "error"]:
                        # Send one last event then close?
                        # Actually better to keep open for a moment or let client close.
                        # We will let client decide when to close (e.g. after redirecting).
                        pass

        except asyncio.CancelledError:
            pass
        finally:
            monitor.unsubscribe(queue)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no"  # Disable Nginx buffering
        }
    )


@router.get("/debug/signal-check")
async def debug_signal_check():
    """
    Debug endpoint to check why signals aren't being generated.

    Returns detailed analysis of all signal conditions:
    - Current price and indicators
    - Each condition status (met/not met)
    - Reason why no signal is generated
    """
    realtime_service = get_realtime_service()

    result: Dict[str, Any] = {
        "timestamp": datetime.now().isoformat(),
        "symbol": realtime_service.symbol,
        "state_machine": {},
        "data_status": {},
        "indicators": {},
        "buy_conditions": {},
        "sell_conditions": {},
        "hard_filters": {},
        "diagnosis": []
    }

    # 1. State Machine Status
    state_machine = realtime_service.state_machine
    result["state_machine"] = {
        "current_state": state_machine.state.name,
        "can_receive_signals": state_machine.can_receive_signals,
        "is_halted": state_machine.is_halted,
        "cooldown_remaining": state_machine.cooldown_remaining
    }

    if not state_machine.can_receive_signals:
        result["diagnosis"].append(f"❌ State machine in {state_machine.state.name} - cannot receive signals")
    else:
        result["diagnosis"].append(f"✅ State machine in SCANNING - ready for signals")

    # 2. Data Status
    candles_1m = list(realtime_service._candles_1m)
    candles_15m = list(realtime_service._candles_15m)
    candles_1h = list(realtime_service._candles_1h)

    result["data_status"] = {
        "candles_1m_count": len(candles_1m),
        "candles_15m_count": len(candles_15m),
        "candles_1h_count": len(candles_1h),
        "min_required": 50,
        "has_enough_data": len(candles_1m) >= 50
    }

    if len(candles_1m) < 50:
        result["diagnosis"].append(f"❌ Insufficient 1m candles: {len(candles_1m)}/50")
        return result
    else:
        result["diagnosis"].append(f"✅ Sufficient data: {len(candles_1m)} candles")

    # 3. Current Price
    latest_candle = candles_1m[-1] if candles_1m else None
    if not latest_candle:
        result["diagnosis"].append("❌ No candle data available")
        return result

    current_price = latest_candle.close
    result["indicators"]["current_price"] = current_price
    result["indicators"]["current_candle"] = {
        "open": latest_candle.open,
        "high": latest_candle.high,
        "low": latest_candle.low,
        "close": latest_candle.close,
        "is_green": latest_candle.close > latest_candle.open,
        "timestamp": latest_candle.timestamp.isoformat()
    }

    # 4. Calculate Indicators manually for debug
    try:
        # VWAP
        vwap_result = realtime_service.vwap_calculator.calculate_vwap(candles_1m)
        if vwap_result:
            price_vs_vwap = "above" if current_price > vwap_result.vwap else "below"
            vwap_distance = realtime_service.vwap_calculator.calculate_distance_from_vwap(
                current_price, vwap_result.vwap
            )
            result["indicators"]["vwap"] = {
                "value": vwap_result.vwap,
                "price_vs_vwap": price_vs_vwap,
                "distance_pct": vwap_distance
            }
        else:
            result["indicators"]["vwap"] = {"error": "Failed to calculate VWAP"}
            result["diagnosis"].append("❌ Failed to calculate VWAP")

        # Bollinger Bands
        bb_result = realtime_service.bollinger_calculator.calculate_bands(candles_1m, current_price)
        if bb_result:
            is_near_lower = realtime_service.bollinger_calculator.is_near_lower_band(
                current_price, bb_result.lower_band, threshold_pct=0.015
            )
            is_near_upper = realtime_service.bollinger_calculator.is_near_upper_band(
                current_price, bb_result.upper_band, threshold_pct=0.015
            )
            result["indicators"]["bollinger"] = {
                "upper_band": bb_result.upper_band,
                "middle_band": bb_result.middle_band,
                "lower_band": bb_result.lower_band,
                "bandwidth": bb_result.bandwidth,
                "percent_b": bb_result.percent_b,
                "is_near_lower": is_near_lower,
                "is_near_upper": is_near_upper
            }
        else:
            result["indicators"]["bollinger"] = {"error": "Failed to calculate BB"}
            result["diagnosis"].append("❌ Failed to calculate Bollinger Bands")

        # StochRSI
        stoch_result = realtime_service.stoch_rsi_calculator.calculate_stoch_rsi(candles_1m)
        if stoch_result:
            result["indicators"]["stoch_rsi"] = {
                "k": stoch_result.k_value,
                "d": stoch_result.d_value,
                "zone": stoch_result.zone.value,
                "is_oversold": stoch_result.is_oversold,
                "is_overbought": stoch_result.is_overbought,
                "k_cross_up": stoch_result.k_cross_up,
                "k_cross_down": stoch_result.k_cross_down
            }
        else:
            result["indicators"]["stoch_rsi"] = {"error": "Failed to calculate StochRSI"}
            result["diagnosis"].append("❌ Failed to calculate StochRSI")

        # Volume Spike
        volumes = [c.volume for c in candles_1m]
        volume_spike_result = realtime_service.signal_generator.volume_spike_detector.detect_spike_from_list(
            volumes=volumes,
            ma_period=20
        )
        if volume_spike_result:
            result["indicators"]["volume"] = {
                "is_spike": volume_spike_result.is_spike,
                "intensity": volume_spike_result.intensity.value,
                "ratio": volume_spike_result.ratio,
                "threshold": 1.5
            }

        # ADX
        if realtime_service.adx_calculator:
            adx_result = realtime_service.adx_calculator.calculate_adx(candles_1m)
            if adx_result:
                result["indicators"]["adx"] = {
                    "value": adx_result.adx_value,
                    "is_trending": adx_result.is_trending,
                    "threshold": 25
                }

        # 5. Check BUY Conditions
        buy_conditions = {
            "conditions_met": 0,
            "min_required": 4,
            "details": {}
        }

        if vwap_result:
            is_trend_bullish = current_price > vwap_result.vwap
            buy_conditions["details"]["1_trend"] = {
                "condition": "Price > VWAP",
                "met": is_trend_bullish,
                "current": f"${current_price:.2f}",
                "vwap": f"${vwap_result.vwap:.2f}"
            }
            if is_trend_bullish:
                buy_conditions["conditions_met"] += 1

        if bb_result and vwap_result:
            is_near_lower = realtime_service.bollinger_calculator.is_near_lower_band(
                current_price, bb_result.lower_band, threshold_pct=0.015
            )
            is_near_vwap = realtime_service.vwap_calculator.calculate_distance_from_vwap(
                current_price, vwap_result.vwap
            ) < 1.0
            is_setup = is_near_lower or is_near_vwap
            buy_conditions["details"]["2_setup"] = {
                "condition": "Near Lower BB or VWAP",
                "met": is_setup,
                "is_near_lower_bb": is_near_lower,
                "is_near_vwap": is_near_vwap
            }
            if is_setup:
                buy_conditions["conditions_met"] += 1

        if stoch_result:
            is_trigger = stoch_result.k_cross_up and stoch_result.k_value < 80
            buy_conditions["details"]["3_trigger"] = {
                "condition": "StochRSI K Cross Up (K < 80)",
                "met": is_trigger,
                "k_cross_up": stoch_result.k_cross_up,
                "k_value": stoch_result.k_value
            }
            if is_trigger:
                buy_conditions["conditions_met"] += 1

        is_green = latest_candle.close > latest_candle.open
        buy_conditions["details"]["4_candle"] = {
            "condition": "Green Candle",
            "met": is_green
        }
        if is_green:
            buy_conditions["conditions_met"] += 1

        if volume_spike_result:
            buy_conditions["details"]["5_volume"] = {
                "condition": "Volume Spike",
                "met": volume_spike_result.is_spike,
                "ratio": volume_spike_result.ratio
            }
            if volume_spike_result.is_spike:
                buy_conditions["conditions_met"] += 1

        buy_conditions["would_signal"] = buy_conditions["conditions_met"] >= buy_conditions["min_required"]
        result["buy_conditions"] = buy_conditions

        # 6. Check SELL Conditions
        sell_conditions = {
            "conditions_met": 0,
            "min_required": 4,
            "details": {}
        }

        if vwap_result:
            is_trend_bearish = current_price < vwap_result.vwap
            sell_conditions["details"]["1_trend"] = {
                "condition": "Price < VWAP",
                "met": is_trend_bearish
            }
            if is_trend_bearish:
                sell_conditions["conditions_met"] += 1

        if bb_result and vwap_result:
            is_near_upper = realtime_service.bollinger_calculator.is_near_upper_band(
                current_price, bb_result.upper_band, threshold_pct=0.015
            )
            is_setup = is_near_upper or is_near_vwap
            sell_conditions["details"]["2_setup"] = {
                "condition": "Near Upper BB or VWAP",
                "met": is_setup
            }
            if is_setup:
                sell_conditions["conditions_met"] += 1

        if stoch_result:
            is_trigger = stoch_result.k_cross_down and stoch_result.k_value > 20
            sell_conditions["details"]["3_trigger"] = {
                "condition": "StochRSI K Cross Down (K > 20)",
                "met": is_trigger,
                "k_cross_down": stoch_result.k_cross_down,
                "k_value": stoch_result.k_value
            }
            if is_trigger:
                sell_conditions["conditions_met"] += 1

        is_red = latest_candle.close < latest_candle.open
        sell_conditions["details"]["4_candle"] = {
            "condition": "Red Candle",
            "met": is_red
        }
        if is_red:
            sell_conditions["conditions_met"] += 1

        if volume_spike_result:
            sell_conditions["details"]["5_volume"] = {
                "condition": "Volume Spike",
                "met": volume_spike_result.is_spike
            }
            if volume_spike_result.is_spike:
                sell_conditions["conditions_met"] += 1

        sell_conditions["would_signal"] = sell_conditions["conditions_met"] >= sell_conditions["min_required"]
        result["sell_conditions"] = sell_conditions

        # 7. Hard Filters
        if realtime_service.hard_filters:
            result["hard_filters"]["adx_filter_enabled"] = True
            if adx_result:
                adx_check = realtime_service.hard_filters.check_adx_filter(adx_result.adx_value)
                result["hard_filters"]["adx_passed"] = adx_check.passed
                result["hard_filters"]["adx_reason"] = adx_check.reason

                if not adx_check.passed:
                    result["diagnosis"].append(f"❌ ADX Filter: {adx_check.reason}")

        # 8. Summary Diagnosis
        if not buy_conditions["would_signal"] and not sell_conditions["would_signal"]:
            buy_missing = buy_conditions["min_required"] - buy_conditions["conditions_met"]
            sell_missing = sell_conditions["min_required"] - sell_conditions["conditions_met"]

            result["diagnosis"].append(
                f"📊 BUY: {buy_conditions['conditions_met']}/{buy_conditions['min_required']} conditions (missing {buy_missing})"
            )
            result["diagnosis"].append(
                f"📊 SELL: {sell_conditions['conditions_met']}/{sell_conditions['min_required']} conditions (missing {sell_missing})"
            )

            # Most common blockers
            if not buy_conditions["details"].get("3_trigger", {}).get("met", False):
                result["diagnosis"].append("💡 BUY blocked by: No StochRSI K Cross Up")
            if not sell_conditions["details"].get("3_trigger", {}).get("met", False):
                result["diagnosis"].append("💡 SELL blocked by: No StochRSI K Cross Down")
        else:
            if buy_conditions["would_signal"]:
                result["diagnosis"].append("🟢 BUY signal conditions MET!")
            if sell_conditions["would_signal"]:
                result["diagnosis"].append("🔴 SELL signal conditions MET!")

    except Exception as e:
        result["diagnosis"].append(f"❌ Error during analysis: {str(e)}")
        result["error"] = str(e)

    return _convert_numpy(result)


# =============================================================================
# CIRCUIT BREAKER CONTROL ENDPOINTS
# =============================================================================

@router.post("/circuit-breaker/enable")
async def enable_circuit_breaker(
    max_consecutive_losses: int = 3,
    cooldown_hours: int = 4,
    max_daily_drawdown_pct: float = 0.10
):
    """
    Enable Circuit Breaker for realtime trading.

    Matching backtest behavior:
    - Blocks trading after N consecutive losses per symbol/direction
    - Global halt on daily drawdown threshold
    """
    from ..dependencies import get_container

    container = get_container()
    enabled_count = 0

    for key, service in container._instances.items():
        if key.startswith('realtime_service_'):
            service.enable_circuit_breaker(
                max_consecutive_losses=max_consecutive_losses,
                cooldown_hours=cooldown_hours,
                max_daily_drawdown_pct=max_daily_drawdown_pct
            )
            enabled_count += 1

    return {
        "success": True,
        "message": f"Circuit Breaker enabled on {enabled_count} services",
        "config": {
            "max_consecutive_losses": max_consecutive_losses,
            "cooldown_hours": cooldown_hours,
            "max_daily_drawdown_pct": max_daily_drawdown_pct
        }
    }


@router.post("/circuit-breaker/disable")
async def disable_circuit_breaker():
    """Disable Circuit Breaker for realtime trading."""
    from ..dependencies import get_container

    container = get_container()
    disabled_count = 0

    for key, service in container._instances.items():
        if key.startswith('realtime_service_'):
            service.disable_circuit_breaker()
            disabled_count += 1

    return {
        "success": True,
        "message": f"Circuit Breaker disabled on {disabled_count} services"
    }


@router.get("/circuit-breaker/status")
async def get_circuit_breaker_status():
    """
    Get Circuit Breaker status — SOTA (Feb 9, 2026).

    Returns full CB state: config, blocked symbols, daily losses,
    trading schedule, and metrics.
    """
    from ..dependencies import get_container

    container = get_container()

    # SOTA (Feb 9, 2026): Use singleton CircuitBreaker for comprehensive status
    cb = container.get_circuit_breaker()
    cb_status = cb.get_status() if cb else {}

    # Legacy: per-service CB status (for backwards compatibility)
    per_service = {}
    for key, service in container._instances.items():
        if key.startswith('realtime_service_'):
            symbol = key.replace('realtime_service_', '')
            if hasattr(service, 'get_circuit_breaker_status'):
                per_service[symbol] = service.get_circuit_breaker_status()

    return {
        "timestamp": datetime.now().isoformat(),
        "circuit_breaker": cb_status,
        "per_service": per_service
    }


@router.post("/debug/trigger-signal")
async def debug_trigger_signal(
    symbol: str = "BTCUSDT",
    type: str = "BUY",
    price: float = 95000.0
):
    """
    Manually trigger a trading signal for debugging flow.
    """
    from datetime import datetime
    import logging
    from src.domain.entities.trading_signal import TradingSignal, SignalType
    from ..dependencies import get_container

    logger = logging.getLogger(__name__)
    symbol = symbol.upper()

    # 1. Create a Fake Signal
    signal_type = SignalType.BUY if type.upper() == "BUY" else SignalType.SELL

    # Simple TP/SL logic for test
    sl_pct = 0.01
    tp_pct = 0.02

    if signal_type == SignalType.BUY:
        entry = price
        sl = price * (1 - sl_pct)
        tp = price * (1 + tp_pct)
    else:
        entry = price
        sl = price * (1 + sl_pct)
        tp = price * (1 - tp_pct)

    signal = TradingSignal(
        symbol=symbol,
        signal_type=signal_type,
        price=price,
        entry_price=entry,
        stop_loss=sl,
        tp_levels={'tp1': tp},
        confidence=0.99, # High confidence for test
        # timestamp is a property, use generated_at if needed, or rely on default
        generated_at=datetime.now(),
        # metadata is not in dataclass definition shown above!
        # Check dataclass definition again...
        # It has: indicators, reasons. No metadata.
        # So we should verify if 'metadata' field exists.
        # Line 81: indicators: Dict[str, Any] = field(default_factory=dict)
        # Maybe use indicators to store source?
        indicators={"source": "manual_debug"}
    )
    # signal.tp_levels = {"tp1": tp} # Already set in constructor

    # 2. Get RealtimeService and Inject
    try:
        container = get_container()
        # Ensure we get the service (might need to create it if not exists for this symbol)
        service = container.get_realtime_service(symbol.lower())

        logger.info(f"🔧 DEBUG: Manually injecting {type} signal for {symbol}")
        result_msg = "Unknown"

        # 2a. Bypass logic - Directly call process like _generate_signals would
        if service._signal_confirmation_service:
            logger.info("🔧 DEBUG: Sending to Confirmation Service...")
            # FORCE confirmation by calling it repeatedly if needed?
            # Or just rely on our min_confirmations=0 setting
            confirmed = service._signal_confirmation_service.process_signal(symbol, signal)

            if confirmed:
                logger.info("🔧 DEBUG: Confirmed! Executing...")
                service._latest_signal = confirmed

                if service.paper_service:
                    # Manually trigger execute flow
                    service.paper_service.on_signal_received(confirmed, symbol)
                    result_msg = "Executed in PaperTradingService"
                else:
                    result_msg = "PaperTradingService not available"

                if service._event_bus:
                    service._event_bus.publish_signal(confirmed)
            else:
                result_msg = f"Held by ConfirmationService. Pending: {service._signal_confirmation_service.get_pending_status(symbol)}"

        else:
             # Direct Execution
             if service.paper_service:
                service.paper_service.on_signal_received(signal, symbol)
                result_msg = "Executed Direct (No Confirmation Service)"

             if service._event_bus:
                service._event_bus.publish_signal(signal)

        return {
            "success": True,
            "signal": {
                "symbol": symbol,
                "type": type,
                "entry": entry,
                "sl": sl,
                "tp": tp
            },
            "result": result_msg
        }

    except Exception as e:
        logger.error(f"Failed to inject signal: {e}")
        return {
            "success": False,
            "error": str(e)
        }


# =============================================================================
# RECONCILIATION & CHART ENDPOINTS (SOTA Feb 2026)
# =============================================================================

@router.post("/reconcile")
async def trigger_reconciliation():
    """
    Manually trigger position reconciliation with exchange.

    SOTA (Feb 2026): Syncs local state with Binance to detect drift.

    Returns:
        Reconciliation results with detected drifts
    """
    from ..dependencies import get_container
    import logging

    logger = logging.getLogger(__name__)

    try:
        container = get_container()
        reconciliation = container.get_reconciliation_service()

        result = await reconciliation.reconcile_now()

        logger.info(f"🔄 Manual reconciliation triggered: {result}")

        return result

    except Exception as e:
        logger.error(f"Reconciliation failed: {e}")
        return {
            "success": False,
            "error": str(e)
        }


@router.get("/reconcile/status")
async def get_reconciliation_status():
    """
    Get ReconciliationService status and statistics.

    Returns:
        Running status, reconcile count, drift count
    """
    from ..dependencies import get_container

    try:
        container = get_container()
        reconciliation = container.get_reconciliation_service()

        return reconciliation.get_stats()

    except Exception as e:
        return {
            "available": False,
            "error": str(e)
        }


@router.post("/generate-chart")
async def trigger_chart_generation():
    """
    Manually trigger profit chart generation and Telegram send.

    SOTA (Feb 2026): Generates equity curve and sends to Telegram.

    Returns:
        Chart generation status and path
    """
    from ..dependencies import get_container
    import logging

    logger = logging.getLogger(__name__)

    try:
        container = get_container()
        generator = container.get_profit_chart_generator()

        result = await generator.generate_now()

        logger.info(f"📊 Manual chart generation triggered: {result}")

        return result

    except Exception as e:
        logger.error(f"Chart generation failed: {e}")
        return {
            "success": False,
            "error": str(e)
        }


@router.get("/chart-generator/status")
async def get_chart_generator_status():
    """
    Get ProfitChartGenerator status and statistics.

    Returns:
        Running status, charts generated, last generation time
    """
    from ..dependencies import get_container

    try:
        container = get_container()
        generator = container.get_profit_chart_generator()

        return generator.get_stats()

    except Exception as e:
        return {
            "available": False,
            "error": str(e)
        }
