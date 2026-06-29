# Momentum — Crypto Signal Tracker

> 24/7 automated momentum tracker scanning 231 Coinbase USD pairs for high-probability pump setups before they reach mainstream visibility.

**[Live Dashboard](https://momentum-tracker-mirjjfgreydqj26dgyswz7.streamlit.app/)** · **[Telegram Channel](https://t.me/MomentumAlphaSignals)**

---

## What It Does

Momentum scans every Coinbase USD pair every 7 minutes across 4 timeframes, fuses 6 independent signal types into a unified confidence score, and manages positions automatically from entry through exit.

**The problem it solves:** By the time a pump is visible on a chart, the best entry is gone. Volume confirmation — the signal most tools wait for — typically arrives after 15–30% of the move has already happened.

---

## Live Performance · 35 days

| Metric | Value |
|---|---|
| Avg trail exit | +37.7% |
| Profitable exits | 100% (worst +21.2%) |
| Risk/reward ratio | 3.17:1 |
| Documented wins | 26 Hall of Fame trades |
| Best single exit | +115.8% (OMNI-USD) |
| TP1 success rate | 8.1% (improving post-fix) |
| Pairs monitored | 231 |

---

## Signal Pipeline

```
L1 Price Momentum → L2 Volume Confirmation → Dynamic L2 Early Detection
→ Acceleration Detection → HH/HL Multi-Leg → TP/SL Position Management
```

**Six signal types:**

1. **L1 — Price Momentum** — 4 timeframes (5min/15min/30min/1hr) simultaneously across all 231 pairs
2. **L2 — Volume Confirmation** — upgrades L1 when volume ratio exceeds 1.5x–3.0x average. Primary alert signal
3. **Dynamic L2 — Early Detection** — fires on strong 24hr momentum (≥15%) with 5 safeguards: fresh leg test, peak proximity, acceleration required, volume trend, and UNCONFIRMED label
4. **Acceleration Tracking** — consistent 24hr growth across 30min/1hr/3hr windows fires staged buildup alerts
5. **HH/HL Multi-Leg Detection** — reads daily snapshots to identify Higher Highs and Higher Lows. Returns CONFIRMED or PRE_BREAKOUT with natural support level
6. **Slow Grinder Detection** — three-tier system (Fast/Mid/Slow) for coins compounding steadily over days. Exempt from weak signal time stops

**TA Indicators (zero additional API calls):**
- RSI-14 using Wilder's smoothing
- MACD 12/26/9 with bullish cross detection
- EMA 20/50 bull structure check
- Relative Strength vs BTC (RS/BTC)
- Unified Momentum Score 0–100

---

## Automated Exit System

Five exit types managed automatically per position:

| Exit Type | Trigger | Notes |
|---|---|---|
| TP1 Partial | +20% gain | Sells 50%, seeds trailing stop |
| Trailing Stop | -12% from peak | Wick-filtered on 1-min closes, not highs |
| Dynamic Hard Stop | -8% standard / -12% grinders | Moves to -15% from peak if coin ever hit +20% |
| Breakeven Trigger | Peak ever +12% | Moves stop floor to entry — no more losing trades |
| Weak Signal Exit | 2hr no traction | Grinders exempt. Secondary 6hr check for flat positions |

Every profitable exit is automatically logged to the **Hall of Fame** table in Supabase.

---

## Key Engineering Decisions

**Wick-filtered trailing stop** — Uses `df["close"].iloc[-15:].max()` instead of candle highs. Low-cap momentum coins frequently generate rogue wicks into thin order books that instantly revert. Trailing on confirmed closes prevents false exits.

**Batch state cache** — One `SELECT` for all 231 coins per cycle instead of 231 individual queries. Reduces Supabase egress from ~65MB/day to ~2MB/day for state reads alone.

**Intra-cycle TP1 check** — Reads highest close within the current 7-minute window. Catches fast spikes that reach +20% and retrace before the next poll — the single biggest driver of TP1 rate improvement.

**RS/BTC market-beta suppression** — When BTC rises 3%+ and a coin's RS/BTC is below 5%, the L2 alert is suppressed. Prevents mass false alerts on broad market pumps (June 7 event: ~40 simultaneous false signals prevented).

**Peak-price freeze on close** — `peak_price` stops updating when a position closes. Prevents phantom peak gains from accumulating weeks after the actual exit, keeping Hall of Fame data honest.

**L2 re-entry on closed positions** — When a coin fires a new L2 after its previous position closed, `l2_fired_at` resets to now. Unlocks 194 previously blocked re-entry opportunities.

---

## Architecture

```
Coinbase Advanced API
        ↓
  main.py (Railway worker)
  ├── fetch_candles() — 250 candles per coin
  ├── check_momentum() — 4 timeframe configs × 231 coins
  ├── calculate_indicators() — RSI, MACD, EMA, RS/BTC
  ├── check_tp_sl() — 5 exit types per open position
  ├── update_coin_state() — batch upsert to Supabase
  └── send_telegram_alert() — Telegram channel
        ↓
   Supabase (PostgreSQL)
   ├── coin_state — 231 rows, full position tracking
   ├── signals — historical signal log
   ├── hall_of_fame — permanent win record
   ├── momentum_history — price history for leaderboard
   └── daily_snapshots — HH/HL multi-leg detection
        ↓
  dashboard_v2.py (Streamlit Cloud)
  ├── KPI row — L2s today, open positions, TP1 rate, last scan
  ├── Active Movers — live momentum with tier classification
  ├── Signal Feed — deduplicated L2 feed with RSI/MACD
  ├── Coin Detail — full position context + indicators
  ├── Leaderboard — 24hr gainers/losers
  └── Hall of Fame — all documented wins
```

**Egress optimization:** Original architecture generated ~16GB/month on Supabase free tier (5GB limit). After batch state cache, conditional momentum history, and reduced candle fetch: **2.5GB/month (84% reduction)**.

---

## Tech Stack

| Component | Technology |
|---|---|
| Scanner | Python 3.13 · APScheduler |
| Deployment | Railway (worker: ~$1.90/month) |
| Database | Supabase (PostgreSQL) |
| Dashboard | Streamlit Cloud |
| Alerts | Telegram Bot API |
| Market Data | Coinbase Advanced Trade API |
| External APIs | Alternative.me (Fear & Greed) · Coinbase (BTC price) |

---

## Project Structure

```
momentum-tracker/
├── main.py           # Scanner, signal detection, TP/SL (~2700 lines)
├── dashboard_v2.py   # Streamlit dashboard (~1200 lines)
├── ingestion.py      # Data ingestion utilities
├── requirements.txt  # Dependencies
└── Procfile          # Railway deployment config
```

---

## Hall of Fame · Selected Wins

All trades auto-logged from live signals. Entry and exit prices are real.

| Coin | Exit Type | Captured | Peak Detected | Date |
|---|---|---|---|---|
| OMNI-USD | TP1 + Trail | +115.8% | +115.8% | Jun 29 |
| OPN-USD | TP1 + Trail | +112.1% | +148.5% | Jun 03 |
| GWEI-USD | TP1 + Trail | +76.6% | +76.6% | Jun 29 |
| SYND-USD | TP1 + Trail | +72.5% | +87.7% | Jun 17 |
| IMU-USD | TP1 + Trail | +63.2% | +73.7% | Jun 18 |
| AGLD-USD | TP1 + Trail | +48.7% | +48.7% | Jun 26 |
| O-USD | TP1 + Trail | +47.9% | +95.0% | Jun 17 |
| EDGE-USD | TP1 + Trail | +40.4% | +40.4% | Jun 27 |
| FORTH-USD | TP1 + Trail | +37.9% | +37.9% | Jun 28 |
| JTO-USD | Time Stop | +41.9% | +49.9% | May 27 |
| WLD-USD | Time Stop | +26.9% | +93.9% | May 30 |
| UNI-USD | Dump Exit | +27.5% | +42.8% | Jun 07 |

---

## What I Learned

**Silent failures are the hardest bugs.** TA indicators were being calculated correctly but written in an unreachable `except` block — they appeared to work but never persisted. Three weeks of null RSI values before the root cause was found.

**Re-entry logic must account for closed positions.** 194 coins with stale `l2_fired_at` timestamps were permanently blocking new alerts. A 30-minute age check was silently killing every potential re-entry signal.

**Egress architecture should be designed from day one.** Retrofitting batch queries after hitting Supabase's free tier limit cost significant engineering time. Schema decisions are harder to change than logic decisions.

**Exit logic is not a feature — it's core infrastructure.** BILL-USD peaked at +63% and gave it all back. Every day the system ran without automated exits was a day real gains were left on the table.

**Candle closes beat highs for trailing stops.** Using `df["high"]` for trailing stop calculation causes false exits on thin-order-book coins that spike and immediately revert. Trailing on 1-minute closes represents agreed-upon market value, not temporary liquidity voids.

---

## Roadmap

- [x] L1/L2 signal detection across 4 timeframes
- [x] Dynamic L2 early detection with 5 safeguards
- [x] Acceleration + HH/HL multi-leg detection
- [x] RSI · MACD · EMA · RS/BTC indicators
- [x] Automated TP/SL position management (5 exit types)
- [x] Hall of Fame auto-logging on profitable exits
- [x] Unified Momentum Score 0–100
- [x] RS/BTC market-beta suppression
- [x] L2 re-entry fix for closed positions
- [x] Public Telegram channel
- [ ] L3 — Alpha Score entry filter (RSI < 65 gate)
- [ ] L3 — Widen intra-cycle TP1 detection window
- [ ] Automated performance tracker (signal outcome logging)

---

## Running Locally

```bash
git clone https://github.com/nicopxm/momentum-tracker
cd momentum-tracker
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

Create `.env`:
```
SUPABASE_URL=your-supabase-url
SUPABASE_KEY=your-supabase-key
TELEGRAM_BOT_TOKEN=your-bot-token
TELEGRAM_CHAT_ID=your-channel-id
```

Run scanner:
```bash
python main.py
```

Run dashboard:
```bash
streamlit run dashboard_v2.py
```

---

*Built and maintained by [@nicopxm](https://github.com/nicopxm) · Live since June, 2026*