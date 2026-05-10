#!/usr/bin/env python3
"""
Simple Backend Test Server

Test basic FastAPI functionality with mock data.
"""

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
import uvicorn
import asyncio
import time
import json
from typing import List

app = FastAPI(title="Hinto Trading Dashboard API", version="1.0.0")

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# WebSocket connections
active_connections: List[WebSocket] = []

@app.get("/")
async def root():
    return {"message": "Hinto Trading Dashboard API", "status": "running"}

@app.get("/system/status")
async def system_status():
    return {
        "status": "healthy",
        "service": "Hinto Trading API",
        "version": "1.0.0",
        "uptime": 0,
        "connections": len(active_connections)
    }

@app.get("/trades/portfolio")
async def get_portfolio():
    return {
        "balance": 10000.0,
        "equity": 10000.0,
        "unrealized_pnl": 0.0,
        "realized_pnl": 0.0,
        "open_positions": []
    }

@app.get("/trades/history")
async def get_trade_history(page: int = 1, limit: int = 10):
    return {
        "trades": [],
        "total": 0,
        "page": page,
        "limit": limit,
        "total_pages": 0
    }

@app.get("/trades/performance")
async def get_performance(days: int = 30):
    return {
        "days": days,
        "total_pnl": 0.0,
        "total_trades": 0,
        "winning_trades": 0,
        "losing_trades": 0,
        "win_rate": 0.0,
        "avg_win": 0.0,
        "avg_loss": 0.0,
        "profit_factor": 0.0,
        "max_drawdown": 0.0,
        "largest_win": 0.0,
        "largest_loss": 0.0
    }

@app.get("/settings")
async def get_settings():
    return {
        "risk_percent": 1.5,
        "rr_ratio": 1.5,
        "max_positions": 3,
        "leverage": 1,
        "auto_execute": False
    }

@app.post("/settings")
async def update_settings(settings: dict):
    return {"message": "Settings updated successfully", "settings": settings}

@app.get("/ws/history/{symbol}")
async def get_historical_data(symbol: str, timeframe: str = "15m"):
    """Return mock historical candle data with indicators."""
    current_time = int(time.time())
    interval_seconds = 900 if timeframe == "15m" else 3600 if timeframe == "1h" else 60

    candles = []
    base_price = 95000.0

    for i in range(100):
        timestamp = current_time - ((99 - i) * interval_seconds)
        # Simulate price movement
        price_change = (i % 20 - 10) * 50
        price = base_price + price_change

        candles.append({
            "time": timestamp,
            "open": price,
            "high": price + 150,
            "low": price - 100,
            "close": price + 50,
            "volume": 100.0 + (i % 10) * 10,
            "vwap": price + 25,
            "bb_upper": price + 300,
            "bb_lower": price - 200,
            "bb_middle": price + 50
        })

    return candles

@app.websocket("/ws/stream/{symbol}")
async def websocket_stream(websocket: WebSocket, symbol: str):
    """WebSocket endpoint for real-time price streaming."""
    await websocket.accept()
    active_connections.append(websocket)

    try:
        base_price = 95000.0
        tick = 0

        while True:
            # Simulate price movement
            tick += 1
            price_change = (tick % 100 - 50) * 10
            current_price = base_price + price_change

            data = {
                "type": "candle",
                "symbol": symbol,
                "timestamp": time.time(),
                "open": current_price,
                "high": current_price + 50,
                "low": current_price - 30,
                "close": current_price + 20,
                "volume": 50.0 + (tick % 10) * 5,
                "vwap": current_price + 10,
                "bollinger": {
                    "upper_band": current_price + 200,
                    "middle_band": current_price,
                    "lower_band": current_price - 200
                },
                "stoch_rsi": {
                    "k": 50 + (tick % 30),
                    "d": 45 + (tick % 25)
                }
            }

            await websocket.send_json(data)
            await asyncio.sleep(1)  # Send update every second

    except WebSocketDisconnect:
        active_connections.remove(websocket)
    except Exception as e:
        print(f"WebSocket error: {e}")
        if websocket in active_connections:
            active_connections.remove(websocket)

if __name__ == "__main__":
    print("🚀 Starting Hinto Trading Dashboard Backend...")
    print("📡 API: http://127.0.0.1:8000")
    print("📊 WebSocket: ws://127.0.0.1:8000/ws/stream/{symbol}")
    uvicorn.run(app, host="127.0.0.1", port=8000, log_level="info")
