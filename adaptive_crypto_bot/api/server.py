"""HTTP-API: простая витрина состояния."""
from __future__ import annotations
import asyncio, redis.asyncio as redis
from fastapi import FastAPI
from adaptive_crypto_bot.config import get_settings

S = get_settings()
app = FastAPI(title="Adaptive-Bot API")

@app.on_event("startup")
async def startup():
    app.state.redis = redis.Redis(host=S.REDIS_HOST, port=S.REDIS_PORT, decode_responses=True)

@app.get("/ticks/latest")
async def latest(n: int = 100):
    r: redis.Redis = app.state.redis                 # type: ignore
    msgs = await r.xrevrange(S.REDIS_STREAM, count=n)
    return [m[1] for m in msgs]

@app.get("/health")
async def health(): return {"ok": True}
