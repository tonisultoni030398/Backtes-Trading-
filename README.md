# GoldLab Backtester (MVP)

Website backtest Forex/XAU/USD dengan FastAPI, Twelve Data, Lightweight Charts, mode auto dan manual awal.

## Fitur MVP
- Backend proxy Twelve Data; API key hanya dibaca dari environment variable `TWELVE_DATA_API_KEY`.
- Instrumen awal: XAU/USD, EUR/USD, GBP/USD, USD/JPY, AUD/USD, USD/CAD, NZD/USD, USD/CHF, EUR/JPY, GBP/JPY.
- Timeframe M1, M5, M15, M30, H1, H2, H4, D1.
- Rentang tanggal, validasi OHLC, sorting kronologis, deduplikasi candle.
- Auto backtest EMA crossover dan RSI reversal; hasil net profit, return, win rate, profit factor, max drawdown, equity curve, trade CSV.
- Mode manual awal: candle replay satu demi satu dan jurnal transaksi lokal yang dapat diekspor CSV.
- Responsive untuk browser Android.

## Penting tentang kualitas hasil
Ini MVP edukasi, belum merupakan simulator broker-grade. Posisi otomatis adalah satu unit harga, tidak menghitung ukuran lot kontrak Forex/XAU, leverage, margin, swap, slippage, dan aturan bid/ask. Spread dan komisi merupakan pengurangan sederhana per trade. Eksekusi strategi memakai close candle, dan hasil tidak menjamin performa masa depan. Jangan gunakan untuk keputusan uang nyata sebelum mesin divalidasi.

Twelve Data membatasi akses sesuai paket, simbol, jumlah kredit, dan rentang data. Endpoint `/time_series` memakai `symbol`, `interval`, `start_date`, `end_date`, `timezone=UTC`. Untuk rentang intraday panjang, periksa jumlah candle dan limit provider. Jika data tidak tersedia, UI menampilkan pesan error; jangan menganggap data kosong sebagai hasil backtest.

## Jalankan lokal di Android dengan Termux
1. Install Python di Termux: `pkg update && pkg install python git`
2. Ekstrak folder proyek lalu masuk ke folder `goldlab_backtester`.
3. Install dependensi: `pip install -r requirements.txt`
4. Set key di sesi Termux (jangan kirim ke chat atau commit ke Git):
   `export TWELVE_DATA_API_KEY='API_KEY_MILIKMU'`
5. Jalankan: `uvicorn app.main:app --host 0.0.0.0 --port 8000`
6. Buka `http://127.0.0.1:8000` pada browser HP yang sama.

## Deploy online gratis untuk uji coba (Render)
1. Buat repository GitHub baru dan upload isi folder proyek. Pastikan file `.env` dan API key asli tidak ikut di repository.
2. Di Render pilih **New + → Blueprint** dan hubungkan repository yang berisi `render.yaml`, atau buat Web Service dengan build command `pip install -r requirements.txt` dan start command `uvicorn app.main:app --host 0.0.0.0 --port $PORT`.
3. Di Environment Variables tambahkan `TWELVE_DATA_API_KEY` dan tempel key di dashboard hosting, bukan di kode.
4. Deploy dan buka URL `https://nama-layanan.onrender.com`.
5. Cek `/api/health`; `api_key_configured` harus `true`.

Catatan hosting gratis Render: service bisa tidur setelah idle, cold start bisa lambat, filesystem lokal tidak persisten, dan layanan gratis ditujukan untuk eksperimen. Jangan menyimpan data pengguna penting di filesystem lokal. Lihat dokumentasi Render untuk ketentuan terbaru.

## API
- `GET /api/health`
- `GET /api/config`
- `GET /api/data?symbol=XAU/USD&interval=5min&start_date=2026-01-01&end_date=2026-01-31`
- `POST /api/backtest` JSON contoh:
```json
{
  "symbol": "EUR/USD",
  "interval": "15min",
  "start_date": "2026-01-01",
  "end_date": "2026-01-31",
  "strategy": "ema_crossover",
  "initial_balance": 1000,
  "fast_ema": 9,
  "slow_ema": 21,
  "rsi_period": 14,
  "spread": 0,
  "commission_per_trade": 0
}
```

## Arsitektur strategi
Fungsi indikator dan mesin berada di `app/main.py` untuk MVP. Untuk pengembangan selanjutnya pindahkan menjadi modul `app/strategies/` dengan interface `generate_signal(candles, params)` dan modul `app/engine/` untuk fill, sizing, spread, commission, slippage, dan equity. Jangan menambahkan strategi dengan mengevaluasi candle masa depan.
