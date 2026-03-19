import time
from datetime import datetime, timezone
import httpx

DISCORD_WEBHOOK = "YOUR_NEW_WEBHOOK_HERE"

client = httpx.Client(timeout=20.0, follow_redirects=True)

# =========================
# State
# =========================
last_richard_status = None
last_richard_daily_date = None
last_market_insight_date = None
last_btc_eth_signals = {"bitcoin": None, "ethereum": None}
last_token_signals = {"PLS": None, "PLSX": None, "PROVEX": None}
last_token_alert_time = {"PLS": 0, "PLSX": 0, "PROVEX": 0}
last_macro_alert_time = {"bitcoin": 0, "ethereum": 0}

# =========================
# Config
# =========================
TOKEN_ALERT_COOLDOWN_SECONDS = 60 * 30   # 30 minutes
MACRO_ALERT_COOLDOWN_SECONDS = 60 * 30   # 30 minutes

TOKENS = [
    {"symbol": "PLS", "search": "PLS pulsechain", "label": "🟢 PLS"},
    {"symbol": "PLSX", "search": "PLSX pulsechain", "label": "🟣 PLSX"},
    {"symbol": "PROVEX", "search": "PROVEX pulsechain", "label": "🧪 PROVEX Coin"},
]

# =========================
# Helpers
# =========================
def now_utc():
    return datetime.now(timezone.utc)

def utc_stamp():
    return now_utc().strftime("%Y-%m-%d %H:%M UTC")

def fmt_pct(v):
    v = float(v or 0)
    sign = "+" if v > 0 else ""
    return f"{sign}{v:.2f}%"

def fmt_money(v):
    try:
        v = float(v or 0)
    except Exception:
        return "$0"
    if v >= 1_000_000_000:
        return f"${v/1_000_000_000:.2f}B"
    if v >= 1_000_000:
        return f"${v/1_000_000:.2f}M"
    if v >= 1_000:
        return f"${v/1_000:.2f}K"
    return f"${v:.2f}"

def safe_float(v, default=0.0):
    try:
        return float(v or 0)
    except Exception:
        return default

def can_send_again(last_sent_ts, cooldown_seconds):
    return (time.time() - float(last_sent_ts or 0)) >= cooldown_seconds

def send_embed(title: str, description: str, color: int = 0x8E44AD):
    payload = {
        "embeds": [
            {
                "title": title,
                "description": description,
                "color": color,
                "footer": {"text": f"PulseChain Rotation Agent • {utc_stamp()}"},
            }
        ]
    }
    try:
        r = client.post(DISCORD_WEBHOOK, json=payload)
        r.raise_for_status()
    except Exception as e:
        print("Webhook embed error:", e, flush=True)

# =========================
# DexScreener token fetch
# =========================
def fetch_token_market(search_term: str):
    try:
        url = "https://api.dexscreener.com/latest/dex/search"
        r = client.get(url, params={"q": search_term})
        r.raise_for_status()
        data = r.json()
        pairs = data.get("pairs", [])

        if not pairs:
            return None

        pulse_pairs = [p for p in pairs if (p.get("chainId") or "").lower() == "pulsechain"]
        if pulse_pairs:
            pairs = pulse_pairs

        def score(p):
            liq = safe_float((p.get("liquidity") or {}).get("usd"))
            vol_h24 = safe_float((p.get("volume") or {}).get("h24"))
            buys = safe_float((((p.get("txns") or {}).get("h1") or {}).get("buys")))
            sells = safe_float((((p.get("txns") or {}).get("h1") or {}).get("sells")))
            return liq * 0.60 + vol_h24 * 0.30 + (buys + sells) * 50

        best = sorted(pairs, key=score, reverse=True)[0]

        txns_h1 = (best.get("txns") or {}).get("h1") or {}
        liquidity = best.get("liquidity") or {}
        volume = best.get("volume") or {}
        price_change = best.get("priceChange") or {}

        buys_h1 = safe_float(txns_h1.get("buys"))
        sells_h1 = safe_float(txns_h1.get("sells"))
        ratio_h1 = buys_h1 / max(1.0, sells_h1)

        liq_usd = safe_float(liquidity.get("usd"))
        vol_h1 = safe_float(volume.get("h1"))
        vol_h24 = safe_float(volume.get("h24"))

        h1_change = safe_float(price_change.get("h1"))
        h6_change = safe_float(price_change.get("h6"))
        h24_change = safe_float(price_change.get("h24"))

        # scoring
        flow_score = 0.0
        flow_score += min(4.0, ratio_h1) * 1.8
        flow_score += 1.5 if vol_h1 > 0 and liq_usd > 0 and (vol_h1 / max(liq_usd, 1.0)) > 0.04 else 0.0
        flow_score += 1.0 if h1_change > -4 else 0.0
        flow_score = min(flow_score, 10.0)

        return {
            "symbol": best.get("baseToken", {}).get("symbol") or search_term.split()[0],
            "pair_address": best.get("pairAddress") or "",
            "dex_id": best.get("dexId") or "",
            "url": best.get("url") or "",
            "liq_usd": liq_usd,
            "vol_h1": vol_h1,
            "vol_h24": vol_h24,
            "buys_h1": buys_h1,
            "sells_h1": sells_h1,
            "ratio_h1": ratio_h1,
            "h1_change": h1_change,
            "h6_change": h6_change,
            "h24_change": h24_change,
            "flow_score": flow_score,
        }

    except Exception as e:
        print("Dex fetch error:", search_term, e, flush=True)
        return None

# =========================
# Token signal logic
# =========================
def classify_token_signal(m):
    ratio = m["ratio_h1"]
    flow = m["flow_score"]
    h1 = m["h1_change"]
    h6 = m["h6_change"]

    if (h1 <= -8 or h6 <= -15) and ratio >= 1.4 and flow >= 6.5:
        return "buy_now", "Heavy dip with real buying pressure", "شراء الآن"

    if flow >= 7.0 and ratio >= 1.35 and h1 <= 5:
        return "strong", "Clear liquidity and buying strength", "عزّز بشكل تدريجي"

    if h1 <= -6 or h6 <= -10:
        if ratio >= 1.1:
            return "dip_watch", "Strong drop but buyers are stepping in", "راقب الارتداد — لا تستعجل"
        return "risk", "Sell pressure is stronger than demand", "لا دخول — انتبه"

    if flow >= 5.8 and ratio >= 1.15:
        return "watch", "Market activity is building", "راقب — دخول تدريجي"

    return "none", "Neutral market, no clear edge", "خليك كاش — انتظار"

def build_token_message(label, m, level, summary_en, action_ar):
    color_map = {
        "watch": 0xF1C40F,
        "strong": 0x2ECC71,
        "dip_watch": 0xE67E22,
        "buy_now": 0xE74C3C,
        "risk": 0xC0392B,
    }

    color = color_map.get(level, 0x8E44AD)
    buy_power = min(10.0, m["ratio_h1"] * 4.2)

    desc = (
        f"**Market Read:** {summary_en}\n"
        f"**Liquidity Flow:** {m['flow_score']:.1f}/10\n"
        f"**Buying Pressure:** {buy_power:.1f}/10\n"
        f"**Buy/Sell Ratio:** {m['ratio_h1']:.2f}x\n"
        f"**1H Change:** {fmt_pct(m['h1_change'])}\n"
        f"**6H Change:** {fmt_pct(m['h6_change'])}\n"
        f"**1H Volume:** {fmt_money(m['vol_h1'])}\n"
        f"**Liquidity:** {fmt_money(m['liq_usd'])}\n\n"
        f"👉 **Take Action:** {action_ar}"
    )

    return label, desc, color

def monitor_tokens():
    global last_token_signals, last_token_alert_time

    for token in TOKENS:
        market = fetch_token_market(token["search"])
        print(f"[DEBUG] {token['symbol']} market = {market}", flush=True)

        if not market:
            continue

        symbol = token["symbol"]
        label = token["label"]

        level, summary_en, action_ar = classify_token_signal(market)
        print(f"[DEBUG] {symbol} level = {level}", flush=True)

        if level == "none":
            continue

        current_signal = (
            f"{level}:"
            f"{round(market['h1_change'], 1)}:"
            f"{round(market['ratio_h1'], 2)}:"
            f"{round(market['flow_score'], 1)}:"
            f"{round(market['vol_h1'], 0)}"
        )

        same_signal = last_token_signals.get(symbol) == current_signal
        cooldown_ok = can_send_again(last_token_alert_time.get(symbol), TOKEN_ALERT_COOLDOWN_SECONDS)

        if same_signal and not cooldown_ok:
            continue

        title, desc, color = build_token_message(label, market, level, summary_en, action_ar)
        send_embed(title, desc, color)
        last_token_signals[symbol] = current_signal
        last_token_alert_time[symbol] = time.time()

# =========================
# Richard Heart monitor
# =========================
def monitor_richard_heart():
    global last_richard_status
    try:
        r = client.get("https://richardheart.com/")
        online = 200 <= r.status_code < 400
    except Exception:
        online = False

    if last_richard_status is None:
        last_richard_status = online
        return

    if online != last_richard_status:
        if online:
            send_embed(
                "🟢 RichardHeart.com",
                "**Status:** Online\n\n👉 **Take Action:** راقب لاحتمال عودة النشاط أو بث",
                0x2ECC71
            )
        else:
            send_embed(
                "🔴 RichardHeart.com",
                "**Status:** Offline\n\n👉 **Take Action:** لا تغيير حالياً",
                0xE74C3C
            )
        last_richard_status = online

def daily_richard_heart_update():
    global last_richard_daily_date
    today = now_utc().date()

    if last_richard_daily_date == today:
        return

    try:
        r = client.get("https://richardheart.com/")
        online = 200 <= r.status_code < 400
    except Exception:
        online = False

    if online:
        send_embed(
            "🟢 RichardHeart.com — Daily Update",
            "**Status:** Online\n\n👉 **Take Action:** راقب لأي نشاط أو بث",
            0x2ECC71
        )
    else:
        send_embed(
            "🔴 RichardHeart.com — Daily Update",
            "**Status:** Offline\n\n👉 **Take Action:** لا تغيير اليوم",
            0xE74C3C
        )

    last_richard_daily_date = today

# =========================
# BTC / ETH monitor
# =========================
def monitor_btc_eth():
    global last_btc_eth_signals, last_macro_alert_time

    try:
        url = "https://api.coingecko.com/api/v3/coins/markets"
        params = {
            "vs_currency": "usd",
            "ids": "bitcoin,ethereum",
            "price_change_percentage": "1h,24h"
        }
        r = client.get(url, params=params)
        r.raise_for_status()
        data = r.json()

        for coin in data:
            coin_id = coin["id"]
            ch1 = safe_float(coin.get("price_change_percentage_1h_in_currency"))
            ch24 = safe_float(coin.get("price_change_percentage_24h"))

            if coin_id == "bitcoin":
                label = "₿ Bitcoin"
            elif coin_id == "ethereum":
                label = "⟠ Ethereum"
            else:
                label = coin.get("name", coin_id.title())

            signal = None
            if ch1 >= 3 or ch24 >= 5:
                signal = "up"
            elif ch1 <= -3 or ch24 <= -5:
                signal = "down"

            if not signal:
                continue

            same_signal = last_btc_eth_signals.get(coin_id) == signal
            cooldown_ok = can_send_again(last_macro_alert_time.get(coin_id), MACRO_ALERT_COOLDOWN_SECONDS)

            if same_signal and not cooldown_ok:
                continue

            if signal == "up":
                send_embed(
                    f"🚨 {label}",
                    f"**Market Read:** Strong upside move\n"
                    f"**1H Change:** {fmt_pct(ch1)}\n"
                    f"**24H Change:** {fmt_pct(ch24)}\n\n"
                    f"👉 **Take Action:** راقب الزخم — لا تطارد",
                    0x2ECC71
                )
            else:
                send_embed(
                    f"🔻 {label}",
                    f"**Market Read:** Clear downside pressure\n"
                    f"**1H Change:** {fmt_pct(ch1)}\n"
                    f"**24H Change:** {fmt_pct(ch24)}\n\n"
                    f"👉 **Take Action:** راقب الدعم — لا تستعجل",
                    0xE67E22
                )

            last_btc_eth_signals[coin_id] = signal
            last_macro_alert_time[coin_id] = time.time()

    except Exception as e:
        print("BTC/ETH error:", e, flush=True)

# =========================
# Daily Market Insight
# =========================
def daily_market_insight():
    global last_market_insight_date
    today = now_utc().date()

    if last_market_insight_date == today:
        return

    try:
        url = "https://api.coingecko.com/api/v3/coins/markets"
        params = {"vs_currency": "usd", "ids": "bitcoin,ethereum"}
        r = client.get(url, params=params)
        r.raise_for_status()
        data = r.json()

        coin_map = {c["id"]: c for c in data}
        btc = coin_map.get("bitcoin")
        eth = coin_map.get("ethereum")

        if not btc or not eth:
            print("Insight error: BTC or ETH missing", flush=True)
            return

        btc_24 = safe_float(btc.get("price_change_percentage_24h"))
        eth_24 = safe_float(eth.get("price_change_percentage_24h"))
        avg = (btc_24 + eth_24) / 2.0

        if avg > 2:
            state = "Bullish"
            action = "راقب — دخول تدريجي"
            color = 0x2ECC71
        elif avg < -2:
            state = "Bearish"
            action = "خليك كاش — انتظار"
            color = 0xE74C3C
        else:
            state = "Neutral"
            action = "مراقبة فقط"
            color = 0x3498DB

        send_embed(
            "📊 Market Insight",
            f"**Today:** {state}\n"
            f"**₿ BTC 24H:** {fmt_pct(btc_24)}\n"
            f"**⟠ ETH 24H:** {fmt_pct(eth_24)}\n"
            f"**Focus:** BTC and ETH daily trend\n\n"
            f"👉 **Take Action:** {action}",
            color
        )

        last_market_insight_date = today

    except Exception as e:
        print("Insight error:", e, flush=True)

# =========================
# Main bot loop
# =========================
def run_bot():
    print("PulseChain Rotation Agent started...", flush=True)
    while True:
        try:
            monitor_tokens()
            monitor_richard_heart()
            daily_richard_heart_update()
            monitor_btc_eth()
            daily_market_insight()
        except Exception as e:
            print("Main loop error:", e, flush=True)

        time.sleep(300)
