import os
from datetime import date
from typing import Literal
import httpx
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from workers import asgi

app = FastAPI(title="GoldLab Backtester", version="0.1.0")
API_KEY = os.getenv("TWELVE_DATA_API_KEY", "").strip()
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATIC_DIR = os.path.join(BASE_DIR, "static")
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

SYMBOLS = {"XAU/USD", "EUR/USD", "GBP/USD", "USD/JPY", "AUD/USD", "USD/CAD", "NZD/USD", "USD/CHF", "EUR/JPY", "GBP/JPY"}
INTERVALS = {"1min", "5min", "15min", "30min", "1h", "2h", "4h", "1day"}

class BacktestRequest(BaseModel):
    symbol: str = "XAU/USD"
    interval: str = "5min"
    start_date: date
    end_date: date
    strategy: Literal["ema_crossover", "rsi"] = "ema_crossover"
    initial_balance: float = Field(default=1000, gt=0)
    fast_ema: int = Field(default=9, ge=2, le=200)
    slow_ema: int = Field(default=21, ge=3, le=500)
    rsi_period: int = Field(default=14, ge=2, le=100)
    spread: float = Field(default=0.0, ge=0)
    commission_per_trade: float = Field(default=0.0, ge=0)

@app.get("/")
def home():
    return FileResponse(os.path.join(STATIC_DIR, "index.html"))

@app.get("/api/health")
def health():
    return {"ok": True, "service": "GoldLab Backtester", "api_key_configured": bool(API_KEY)}

@app.get("/api/config")
def config():
    return {"symbols": sorted(SYMBOLS), "intervals": sorted(INTERVALS), "strategies": [
        {"id": "ema_crossover", "name": "EMA Crossover"},
        {"id": "rsi", "name": "RSI Reversal"}
    ], "api_key_configured": bool(API_KEY)}

@app.get("/api/data")
async def get_data(symbol: str = "XAU/USD", interval: str = "5min",
                   start_date: date = date(2026, 1, 1), end_date: date = date(2026, 1, 31)):
    symbol = symbol.strip().upper()
    if symbol not in SYMBOLS:
        raise HTTPException(400, "Simbol belum didukung pada MVP ini.")
    if interval not in INTERVALS:
        raise HTTPException(400, "Timeframe tidak valid.")
    if start_date > end_date:
        raise HTTPException(400, "Tanggal mulai harus sebelum atau sama dengan tanggal selesai.")
    if not API_KEY:
        raise HTTPException(503, "API key belum dikonfigurasi. Tambahkan TWELVE_DATA_API_KEY di Environment Variables hosting.")
    params = {
        "symbol": symbol, "interval": interval,
        "start_date": start_date.isoformat(), "end_date": end_date.isoformat(),
        "timezone": "UTC", "apikey": API_KEY
    }
    try:
        async with httpx.AsyncClient(timeout=35) as client:
            response = await client.get("https://api.twelvedata.com/time_series", params=params)
        payload = response.json()
    except (httpx.HTTPError, ValueError):
        raise HTTPException(502, "Tidak dapat menghubungi Twelve Data. Coba lagi nanti.")
    if response.status_code >= 400 or payload.get("status") == "error" or "values" not in payload:
        message = payload.get("message", "Data tidak tersedia atau paket API tidak mengizinkan permintaan ini.")
        # Avoid reflecting key or request URL to the client.
        raise HTTPException(502, f"Twelve Data: {message}")
    candles = []
    bad = 0
    for item in payload.get("values", []):
        try:
            dt = item["datetime"]
            o, h, l, c = [float(item[k]) for k in ("open", "high", "low", "close")]
            if not all(map(lambda x: x == x and abs(x) != float("inf"), [o,h,l,c])): raise ValueError()
            if min(o,h,l,c) <= 0 or h < max(o,l,c) or l > min(o,h,c): raise ValueError()
            candles.append({"time": dt, "open": o, "high": h, "low": l, "close": c})
        except (KeyError, TypeError, ValueError):
            bad += 1
    # API commonly returns newest first; strategy engine expects oldest first.
    candles.sort(key=lambda x: x["time"])
    deduped = []
    seen = set()
    for candle in candles:
        if candle["time"] not in seen:
            deduped.append(candle); seen.add(candle["time"])
    if not deduped:
        raise HTTPException(502, "Tidak ada candle valid pada periode tersebut.")
    return {"symbol": symbol, "interval": interval, "start_date": start_date.isoformat(),
            "end_date": end_date.isoformat(), "count": len(deduped), "invalid_rows_skipped": bad,
            "data_source": "Twelve Data", "candles": deduped,
            "note": "Cek batas data, credits, dan entitlement paket Twelve Data. Respons historis dapat dibatasi provider."}

def ema(values, period):
    result = [None] * len(values)
    if len(values) < period: return result
    alpha = 2 / (period + 1)
    seed = sum(values[:period]) / period
    result[period-1] = seed
    current = seed
    for i in range(period, len(values)):
        current = values[i] * alpha + current * (1-alpha)
        result[i] = current
    return result

def rsi(values, period):
    out = [None] * len(values)
    if len(values) <= period: return out
    gains = [max(values[i]-values[i-1], 0) for i in range(1, len(values))]
    losses = [max(values[i-1]-values[i], 0) for i in range(1, len(values))]
    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period
    def calc(g, l):
        if l == 0: return 100.0 if g > 0 else 50.0
        return 100 - 100/(1 + g/l)
    out[period] = calc(avg_gain, avg_loss)
    for i in range(period+1, len(values)):
        avg_gain = (avg_gain*(period-1) + gains[i-1]) / period
        avg_loss = (avg_loss*(period-1) + losses[i-1]) / period
        out[i] = calc(avg_gain, avg_loss)
    return out

def run_engine(req, candles):
    if len(candles) < 30:
        raise HTTPException(400, "Data terlalu sedikit untuk backtest. Pilih periode lebih panjang atau timeframe lebih kecil.")
    closes = [c["close"] for c in candles]
    fast = ema(closes, req.fast_ema)
    slow = ema(closes, req.slow_ema)
    rsis = rsi(closes, req.rsi_period)
    balance = req.initial_balance
    equity_peak = balance
    max_dd = 0.0
    position = None
    trades = []
    equity = []
    # One unit position for transparent MVP. No leverage/lot sizing in this first version.
    for i, candle in enumerate(candles):
        signal = None
        if req.strategy == "ema_crossover" and i > 0 and fast[i] is not None and slow[i] is not None and fast[i-1] is not None and slow[i-1] is not None:
            if fast[i-1] <= slow[i-1] and fast[i] > slow[i]: signal = "buy"
            elif fast[i-1] >= slow[i-1] and fast[i] < slow[i]: signal = "sell"
        elif req.strategy == "rsi" and rsis[i] is not None:
            if rsis[i] < 30: signal = "buy"
            elif rsis[i] > 70: signal = "sell"
        # Execute at candle close for this MVP; never use future candles.
        if position and ((position["side"] == "long" and signal == "sell") or (position["side"] == "short" and signal == "buy")):
            exit_price = candle["close"]
            gross = (exit_price-position["entry"]) if position["side"] == "long" else (position["entry"]-exit_price)
            net = gross - req.spread - req.commission_per_trade
            balance += net
            trades.append({"side": position["side"], "entry_time": position["time"], "entry": position["entry"],
                           "exit_time": candle["time"], "exit": exit_price, "pnl": round(net, 6),
                           "result": "win" if net > 0 else "loss" if net < 0 else "breakeven"})
            position = None
        if position is None and signal in ("buy", "sell"):
            position = {"side": "long" if signal == "buy" else "short", "entry": candle["close"], "time": candle["time"]}
        equity.append({"time": candle["time"], "equity": round(balance, 6)})
        equity_peak = max(equity_peak, balance)
        if equity_peak > 0: max_dd = max(max_dd, (equity_peak-balance)/equity_peak*100)
    # Close remaining position at last candle to avoid hiding open PnL.
    if position:
        last = candles[-1]
        gross = (last["close"]-position["entry"]) if position["side"] == "long" else (position["entry"]-last["close"])
        net = gross - req.spread - req.commission_per_trade
        balance += net
        trades.append({"side": position["side"], "entry_time": position["time"], "entry": position["entry"],
                       "exit_time": last["time"], "exit": last["close"], "pnl": round(net, 6),
                       "result": "win" if net > 0 else "loss" if net < 0 else "breakeven"})
        if equity: equity[-1]["equity"] = round(balance, 6)
    wins = sum(1 for t in trades if t["pnl"] > 0)
    losses = sum(1 for t in trades if t["pnl"] < 0)
    gross_profit = sum(t["pnl"] for t in trades if t["pnl"] > 0)
    gross_loss = abs(sum(t["pnl"] for t in trades if t["pnl"] < 0))
    return {"initial_balance": req.initial_balance, "final_balance": round(balance, 6),
            "net_profit": round(balance-req.initial_balance, 6),
            "return_pct": round((balance/req.initial_balance-1)*100, 4),
            "trades": len(trades), "wins": wins, "losses": losses,
            "win_rate": round(wins/len(trades)*100, 2) if trades else 0,
            "profit_factor": round(gross_profit/gross_loss, 4) if gross_loss else (None if gross_profit == 0 else "infinity"),
            "max_drawdown_pct": round(max_dd, 3), "trades_detail": trades, "equity": equity,
            "caveat": "MVP: ukuran posisi satu unit, spread/komisi sederhana, tanpa swap, slippage, margin, atau tick-level fill. Hasil bukan representasi pasti hasil broker."}

@app.post("/api/backtest")
async def backtest(req: BacktestRequest):
    if req.symbol.strip().upper() not in SYMBOLS or req.interval not in INTERVALS:
        raise HTTPException(400, "Simbol atau timeframe tidak didukung.")
    if req.start_date > req.end_date:
        raise HTTPException(400, "Tanggal mulai harus sebelum atau sama dengan tanggal selesai.")
    if req.strategy == "ema_crossover" and req.fast_ema >= req.slow_ema:
        raise HTTPException(400, "EMA cepat harus lebih kecil daripada EMA lambat.")
    data = await get_data(req.symbol, req.interval, req.start_date, req.end_date)
    result = run_engine(req, data["candles"])
    return {"request": req.model_dump(mode="json"), "data_summary": {k:data[k] for k in ("symbol","interval","start_date","end_date","count","invalid_rows_skipped","data_source")}, "result": result}

@app.post("/api/manual/trade")
def manual_trade(payload: dict):
    # Manual state is client-session only in this MVP; endpoint validates action shape.
    action = payload.get("action")
    if action not in {"buy", "sell", "close"}:
        raise HTTPException(400, "Aksi harus buy, sell, atau close.")
    return {"accepted": True, "action": action, "message": "Aksi valid. Versi MVP menyimpan jurnal manual di browser; belum ada penyimpanan akun lintas perangkat."}
Default = asgi.entrypoint(app)
