
from datetime import date
from typing import Literal

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import Response
from pydantic import BaseModel, Field
from workers import asgi

app = FastAPI(
    title="GoldLab Backtester",
    version="1.0.0",
)


# ==========================================
# KONFIGURASI CLOUDFLARE
# ==========================================

def get_env(request: Request):
    return request.scope.get("env")


def get_api_key(request: Request) -> str:
    env = get_env(request)
    if env is None:
        return ""
    return str(
        getattr(env, "TWELVE_DATA_API_KEY", "") or ""
    ).strip()


async def fetch_asset(request: Request, path: str):
    env = get_env(request)

    if env is None:
        raise HTTPException(
            status_code=500,
            detail="Environment Cloudflare tidak tersedia.",
        )

    assets = getattr(env, "ASSETS", None)

    if assets is None:
        raise HTTPException(
            status_code=500,
            detail="Binding ASSETS belum dikonfigurasi.",
        )

    safe_path = path.lstrip("/")

    if not safe_path:
        safe_path = "index.html"

    response = await assets.fetch(
        f"https://assets.local/{safe_path}"
    )

    return Response(
        content=await response.bytes(),
        status_code=response.status,
        headers={
            key: value
            for key, value in response.headers.items()
            if key.lower() not in {
                "content-length",
                "content-encoding",
                "transfer-encoding",
            }
        },
    )


# ==========================================
# HALAMAN WEBSITE
# ==========================================

@app.get("/")
async def home(request: Request):
    return await fetch_asset(request, "index.html")


@app.get("/static/{path:path}")
async def static_files(path: str, request: Request):
    return await fetch_asset(request, path)


@app.get("/favicon.ico")
async def favicon(request: Request):
    try:
        return await fetch_asset(request, "favicon.ico")
    except HTTPException:
        return Response(status_code=204)


@app.get("/api/health")
def health(request: Request):
    return {
        "ok": True,
        "service": "GoldLab Backtester",
        "api_key_configured": bool(get_api_key(request)),
    }


@app.get("/api/config")
def config(request: Request):
    return {
        "symbols": [
            "XAU/USD",
            "EUR/USD",
            "GBP/USD",
            "USD/JPY",
            "AUD/USD",
            "USD/CAD",
            "NZD/USD",
            "USD/CHF",
            "EUR/JPY",
            "GBP/JPY",
        ],
        "intervals": [
            "1min",
            "5min",
            "15min",
            "30min",
            "1h",
            "2h",
            "4h",
            "1day",
        ],
        "api_key_configured": bool(get_api_key(request)),
    }


# ==========================================
# VALIDASI BACKTEST
# ==========================================

class BacktestRequest(BaseModel):
    symbol: Literal[
        "XAU/USD",
        "EUR/USD",
        "GBP/USD",
        "USD/JPY",
        "AUD/USD",
        "USD/CAD",
        "NZD/USD",
        "USD/CHF",
        "EUR/JPY",
        "GBP/JPY",
    ] = "XAU/USD"

    interval: Literal[
        "1min",
        "5min",
        "15min",
        "30min",
        "1h",
        "2h",
        "4h",
        "1day",
    ] = "5min"

    start_date: date
    end_date: date

    strategy: Literal[
        "ema_crossover",
        "rsi",
    ] = "ema_crossover"

    initial_balance: float = Field(
        default=10000,
        gt=0,
        le=100000000,
    )

    fast_ema: int = Field(
        default=9,
        ge=2,
        le=100,
    )

    slow_ema: int = Field(
        default=21,
        ge=3,
        le=300,
    )

    rsi_period: int = Field(
        default=14,
        ge=2,
        le=100,
    )

    spread: float = Field(
        default=0.3,
        ge=0,
        le=1000,
    )

    commission: float = Field(
        default=0,
        ge=0,
        le=10000,
    )


# ==========================================
# MENGAMBIL DATA TWELVE DATA
# ==========================================

@app.get("/api/data")
async def get_data(
    request: Request,
    symbol: str = "XAU/USD",
    interval: str = "5min",
    start_date: date | None = None,
    end_date: date | None = None,
    outputsize: int = 5000,
):
    allowed_symbols = {
        "XAU/USD",
        "EUR/USD",
        "GBP/USD",
        "USD/JPY",
        "AUD/USD",
        "USD/CAD",
        "NZD/USD",
        "USD/CHF",
        "EUR/JPY",
        "GBP/JPY",
    }

    allowed_intervals = {
        "1min",
        "5min",
        "15min",
        "30min",
        "1h",
        "2h",
        "4h",
        "1day",
    }

    if symbol not in allowed_symbols:
        raise HTTPException(
            status_code=400,
            detail="Simbol tidak didukung.",
        )

    if interval not in allowed_intervals:
        raise HTTPException(
            status_code=400,
            detail="Timeframe tidak didukung.",
        )

    if start_date and end_date and start_date > end_date:
        raise HTTPException(
            status_code=400,
            detail="Tanggal mulai melebihi tanggal akhir.",
        )

    api_key = get_api_key(request)

    if not api_key:
        raise HTTPException(
            status_code=503,
            detail=(
                "API key belum dikonfigurasi. "
                "Tambahkan TWELVE_DATA_API_KEY "
                "di Secrets Cloudflare."
            ),
        )

    params = {
        "symbol": symbol,
        "interval": interval,
        "outputsize": max(1, min(outputsize, 5000)),
        "apikey": api_key,
        "format": "JSON",
        "timezone": "UTC",
    }

    if start_date:
        params["start_date"] = start_date.isoformat()

    if end_date:
        params["end_date"] = end_date.isoformat()

    try:
        async with httpx.AsyncClient(timeout=25.0) as client:
            response = await client.get(
                "https://api.twelvedata.com/time_series",
                params=params,
            )

        response.raise_for_status()
        data = response.json()

    except httpx.TimeoutException:
        raise HTTPException(
            status_code=504,
            detail="Permintaan data Twelve Data melewati batas waktu.",
        )

    except httpx.HTTPError:
        raise HTTPException(
            status_code=502,
            detail="Gagal menghubungi penyedia data.",
        )

    if data.get("status") == "error" or data.get("code"):
        message = str(
            data.get("message", "Penyedia data menolak permintaan.")
        )

        raise HTTPException(
            status_code=502,
            detail=message,
        )

    values = data.get("values")

    if not isinstance(values, list):
        raise HTTPException(
            status_code=502,
            detail="Data candle tidak tersedia dari penyedia.",
        )

    candles = []

    for item in reversed(values):
        try:
            candles.append({
                "time": item["datetime"],
                "open": float(item["open"]),
                "high": float(item["high"]),
                "low": float(item["low"]),
                "close": float(item["close"]),
            })
        except (KeyError, TypeError, ValueError):
            continue

    return {
        "symbol": symbol,
        "interval": interval,
        "count": len(candles),
        "source": "Twelve Data",
        "candles": candles,
    }


# ==========================================
# PERHITUNGAN EMA DAN RSI
# ==========================================

def calculate_ema(values: list[float], period: int):
    if not values:
        return []

    alpha = 2 / (period + 1)
    result = [values[0]]

    for value in values[1:]:
        result.append(
            value * alpha + result[-1] * (1 - alpha)
        )

    return result


def calculate_rsi(values: list[float], period: int):
    result = [50.0] * len(values)

    for i in range(period, len(values)):
        gains = 0.0
        losses = 0.0

        for j in range(i - period + 1, i + 1):
            change = values[j] - values[j - 1]

            if change > 0:
                gains += change
            else:
                losses -= change

        if losses == 0:
            result[i] = 100.0 if gains > 0 else 50.0
        else:
            relative_strength = gains / losses
            result[i] = (
                100 - 100 / (1 + relative_strength)
            )

    return result


# ==========================================
# MESIN BACKTEST SEDERHANA
# ==========================================

def run_engine(req: BacktestRequest, candles: list[dict]):
    if len(candles) < max(
        30,
        req.fast_ema,
        req.slow_ema,
        req.rsi_period,
    ) + 1:
        raise HTTPException(
            status_code=422,
            detail="Jumlah candle tidak cukup untuk backtest.",
        )

    if req.fast_ema >= req.slow_ema:
        raise HTTPException(
            status_code=400,
            detail="EMA cepat harus lebih kecil dari EMA lambat.",
        )

    closes = [c["close"] for c in candles]

    fast = calculate_ema(closes, req.fast_ema)
    slow = calculate_ema(closes, req.slow_ema)
    rsi_values = calculate_rsi(closes, req.rsi_period)

    balance = req.initial_balance
    equity = []
    trades = []
    position = None

    peak = balance
    max_drawdown = 0.0

    risk_fraction = 0.01
    stop_distance = max(req.spread * 3, 0.01)
    target_distance = stop_distance * 2

    for i in range(1, len(candles)):
        candle = candles[i]
        signal = 0

        if req.strategy == "ema_crossover":
            if (
                fast[i] > slow[i]
                and fast[i - 1] <= slow[i - 1]
                and rsi_values[i] > 50
            ):
                signal = 1

            elif (
                fast[i] < slow[i]
                and fast[i - 1] >= slow[i - 1]
                and rsi_values[i] < 50
            ):
                signal = -1

        elif req.strategy == "rsi":
            if rsi_values[i] < 30:
                signal = 1
            elif rsi_values[i] > 70:
                signal = -1

        if position:
            direction = position["direction"]
            entry = position["entry"]
            exit_price = None
            reason = ""

            if direction == 1:
                if candle["low"] <= entry - stop_distance:
                    exit_price = entry - stop_distance
                    reason = "SL"
                elif candle["high"] >= entry + target_distance:
                    exit_price = entry + target_distance
                    reason = "TP"
            else:
                if candle["high"] >= entry + stop_distance:
                    exit_price = entry + stop_distance
                    reason = "SL"
                elif candle["low"] <= entry - target_distance:
                    exit_price = entry - target_distance
                    reason = "TP"

            if exit_price is None and signal == -direction:
                exit_price = candle["close"]
                reason = "Signal"

            if exit_price is not None:
                pnl = (
                    (exit_price - entry)
                    * direction
                    * position["units"]
                )

                pnl -= req.spread * position["units"]
                pnl -= req.commission

                balance += pnl

                trades.append({
                    "time": candle["time"],
                    "direction": (
                        "BUY" if direction == 1 else "SELL"
                    ),
                    "entry": round(entry, 5),
                    "exit": round(exit_price, 5),
                    "pnl": round(pnl, 2),
                    "reason": reason,
                })

                position = None

        if position is None and signal != 0:
            units = (
                balance * risk_fraction / stop_distance
            )

            position = {
                "direction": signal,
                "entry": candle["close"],
                "units": units,
            }

        peak = max(peak, balance)

        if peak > 0:
            max_drawdown = max(
                max_drawdown,
                (peak - balance) / peak,
            )

        equity.append(round(balance, 2))

    if position:
        last_candle = candles[-1]
        exit_price = last_candle["close"]

        pnl = (
            (exit_price - position["entry"])
            * position["direction"]
            * position["units"]
        )

        pnl -= req.spread * position["units"]
        pnl -= req.commission
        balance += pnl

        trades.append({
            "time": last_candle["time"],
            "direction": (
                "BUY"
                if position["direction"] == 1
                else "SELL"
            ),
            "entry": round(position["entry"], 5),
            "exit": round(exit_price, 5),
            "pnl": round(pnl, 2),
            "reason": "End of data",
        })

    winners = [t for t in trades if t["pnl"] > 0]
    losers = [t for t in trades if t["pnl"] < 0]

    gross_profit = sum(t["pnl"] for t in winners)
    gross_loss = abs(sum(t["pnl"] for t in losers))

    net_profit = balance - req.initial_balance

    return {
        "symbol": req.symbol,
        "interval": req.interval,
        "strategy": req.strategy,
        "source": "Twelve Data",
        "candles": len(candles),
        "initial_balance": round(req.initial_balance, 2),
        "final_balance": round(balance, 2),
        "net_profit": round(net_profit, 2),
        "return_percent": round(
            net_profit / req.initial_balance * 100,
            2,
        ),
        "total_trades": len(trades),
        "winning_trades": len(winners),
        "losing_trades": len(losers),
        "win_rate": round(
            len(winners) / len(trades) * 100,
            2,
        ) if trades else 0,
        "profit_factor": round(
            gross_profit / gross_loss, 2
        ) if gross_loss else None,
        "max_drawdown_percent": round(
            max_drawdown * 100, 2
        ),
        "equity": equity,
        "trades": trades,
        "note": (
            "Hasil simulasi historis, bukan jaminan "
            "hasil trading di masa depan."
        ),
    }


# ==========================================
# ENDPOINT BACKTEST
# ==========================================

@app.post("/api/backtest")
async def backtest(
    req: BacktestRequest,
    request: Request,
):
    if req.start_date > req.end_date:
        raise HTTPException(
            status_code=400,
            detail="Tanggal mulai harus sebelum tanggal akhir.",
        )

    data = await get_data(
        request=request,
        symbol=req.symbol,
        interval=req.interval,
        start_date=req.start_date,
        end_date=req.end_date,
        outputsize=5000,
    )

    return run_engine(req, data["candles"])


# ==========================================
# FALLBACK UNTUK FILE FRONTEND
# ==========================================

@app.get("/{path:path}")
async def frontend_assets(
    path: str,
    request: Request,
):
    if path.startswith("api/"):
        raise HTTPException(
            status_code=404,
            detail="Endpoint API tidak ditemukan.",
        )

    return await fetch_asset(request, path)


# WAJIB UNTUK CLOUDFLARE PYTHON WORKERS
Default = asgi.entrypoint(app)
