"""
Shark Tank Router - API Layer

Endpoints for the Shark Tank Dashboard.
Manages the "Elite Portfolio" of 10 coins.
"""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from typing import List, Dict, Optional
from datetime import datetime
import json
import random
from fastapi import WebSocket, WebSocketDisconnect
from ..websocket_manager import get_websocket_manager

from ..dependencies import get_container

router = APIRouter(prefix="/shark-tank", tags=["Shark Tank"])

# --- Data Models ---
class Shark(BaseModel):
    symbol: str
    price: float
    change_24h: float
    score: float       # 0-100 (Confidence)
    status: str        # HUNTING, IN_POSITION, COOLDOWN
    active_pnl: float  # Unr. PnL of current trade
    signal_type: Optional[str] = None # BUY/SELL
    timestamp: Optional[datetime] = None

class SharkTankStatus(BaseModel):
    mode: str          # SAFE / AGGRESSIVE
    total_equity: float
    daily_pnl: float
    active_sharks: int # Number of active positions
    sharks: List[Shark]

# --- Endpoints ---

@router.get("/status", response_model=SharkTankStatus)
async def get_status(container = Depends(get_container)):
    """
    Get the real-time status of the Shark Tank.
    Aggregates data from all RealtimeServices.
    """
    # 1. Get List of Sharks (Configured Symbols)
    # We assume multi_token_config is loaded in container or main
    # For now, we fetch from DI container's active services

    # This is a mock implementation for Phase 1 Frontend Dev
    # In Phase 2, we will hook into RealtimeService actual state

    mock_sharks = [
        Shark(symbol="BTCUSDT", price=98500.0, change_24h=2.5, score=95.0, status="IN_POSITION", active_pnl=15.5, signal_type="BUY"),
        Shark(symbol="BNBUSDT", price=650.0, change_24h=-1.2, score=80.0, status="HUNTING", active_pnl=0.0),
        Shark(symbol="SOLUSDT", price=145.0, change_24h=5.0, score=88.0, status="HUNTING", active_pnl=0.0),
        Shark(symbol="TAOUSDT", price=450.0, change_24h=-3.5, score=40.0, status="COOLDOWN", active_pnl=0.0),
        # Add others...
    ]

    return SharkTankStatus(
        mode="AGGRESSIVE",
        total_equity=1150.50,
        daily_pnl=25.50,
        active_sharks=1,
        sharks=mock_sharks
    )

@router.post("/mode")
async def set_mode(mode: str):
    """Switch between SAFE (5x+CB) and AGGRESSIVE (10x+NoCB)."""
    # TODO: Implement logic
    return {"status": "success", "mode": mode}

@router.websocket("/ws")
async def shark_tank_feed(websocket: WebSocket):
    """
    WebSocket feed for Shark Tank Dashboard.
    Pushes real-time updates of all sharks.
    """
    manager = get_websocket_manager()
    connection = await manager.connect(websocket, "shark_tank")

    try:
        # Start a dedicated task for this connection to send mock updates (Simulator Mode)
        # In production, this would be a global broadcaster.
        while True:
            # Mock Data Update
            mock_update = {
                "type": "SHARK_UPDATE",
                "timestamp": datetime.now().isoformat(),
                "sharks": [
                    {
                        "symbol": "BTCUSDT",
                        "price": 98500 + random.uniform(-50, 50),
                        "change_24h": 2.5 + random.uniform(-0.1, 0.1),
                        "score": 95,
                        "status": "IN_POSITION",
                        "active_pnl": 155.20 + random.uniform(-5, 5)
                    },
                    {
                        "symbol": "BNBUSDT",
                        "price": 650 + random.uniform(-1, 1),
                        "change_24h": -1.2,
                        "score": 80,
                        "status": "HUNTING",
                        "active_pnl": 0
                    },
                    {
                        "symbol": "SOLUSDT",
                        "price": 145 + random.uniform(-0.5, 0.5),
                        "change_24h": 5.0,
                        "score": 88,
                        "status": "HUNTING",
                        "active_pnl": 0
                    },
                    {
                        "symbol": "TAOUSDT",
                        "price": 450 + random.uniform(-2, 2),
                        "change_24h": -3.5,
                        "score": 40,
                        "status": "COOLDOWN",
                        "active_pnl": 0
                    }
                ]
            }

            await websocket.send_text(json.dumps(mock_update))
            await asyncio.sleep(1) # 1Hz update

    except WebSocketDisconnect:
        await manager.disconnect(connection)
    except Exception as e:
        # logger.error(f"WS Error: {e}")
        await manager.disconnect(connection)
