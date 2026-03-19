import time
from datetime import datetime, timezone
import httpx

# =========================
# Discord Webhook
# =========================
DISCORD_WEBHOOK = "https://discord.com/api/webhooks/1483880814537216100/gM_wVR-G6zJrh05I30pkkVDLQ9YH-alYSWLR-f-4-MITMx7YR4RiVX-1qrSaN2sWM9or"

client = httpx.Client(timeout=20.0)

# =========================
# State
# =========================
last_richard_status = None
last_richard_daily_date = None
last_market_insight_date = None
last_btc_eth_signals = {"bitcoin": None, "ethereum": None}
last_token_signals = {"PLS": None, "PLSX": None, "PROVEX": None}

# =========================
# Token Config
# IMPORTANT:
# إذا عندك addresses أدق من هدول، بدّلهم لاحقاً
# =========================
TOKENS = [
    {"symbol": "PLS", "search": "PLS pulsechain"},
    {"symbol": "PLSX", "search": "PLSX pulsechain"},
    {"symbol": "PROVEX", "search": "PROVEX pulsechain"},
]

# =========================
# Helpers
# =========================
def send(msg: str):
    try:
        client.post(DISCORD_WEBHOOK, json={"content": msg})
    except Exception as e:
        print("Webhook send error:", e)

def fmt_pct(v):
    sign = "+" if v > 0 else ""
    return f"{sign}{v:.2f}%"

def fmt_money(v):
    try:
        v = float(v)
    except Exception:
        return "$0"
    if v >= 1_000_000_000:
        return f"${v/1_000_000_000:.2f}B"
    if v >= 1_000_000:
        return f"${v/1_000_000:.2f}M"
    if v >= 1_000:
        return f"${v/1_000:.2f}K"
    return f"${v:.2f}"

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
            liq = float((p.get("liquidity") or {}).get("usd") or 0)
            vol = float((p.get("volume") or {}).get("h24") or 0)
            buys = float((((p.get("txns") or {}).get("h1") or {}).get("buys")) or 0)
            sells = float((((p.get("txns") or {}).get("h1") or {}).get("sells")) or 0)
            return liq * 0.6 + vol * 0.3 + (buys + sells) * 50

        best = sorted(pairs, key=score, reverse=True)[0]

        txns_h1 = (best.get("txns") or {}).get("h1") or {}
        liquidity = best.get("liquidity") or {}
        volume = best.get("volume") or {}
        price_change = best.get("priceChange") or {}

        buys_h1 = float(txns_h1.get("buys") or 0)
        sells_h1 = float(txns_h1.get("sells") or 0)
        ratio_h1 = buys_h1 / max(1.0, sells_h1)

        liq_usd = float(liquidity.get("usd") or 0)
        vol_h1 = float(volume.get("h1") or 0)

        h1_change = float(price_change.get("h1") or 0)
        h6_change = float(price_change.get("h6") or 0)
        h24_change = float(price_change.get("h24") or 0)

        flow_score = 0
        flow_score += min(4, ratio_h1) * 1.8
        flow_score += 1.5 if vol_h1 > 0 and liq_usd > 0 and (vol_h1 / max(liq_usd, 1)) > 0.04 else 0
        flow_score += 1.0 if h1_change > -4 else 0
        flow_score = min(flow_score, 10)

        return {
            "symbol": best.get("baseToken", {}).get("symbol") or search_term.split()[0],
            "liq_usd": liq_usd,
            "vol_h1": vol_h1,
            "buys_h1": buys_h1,
            "sells_h1": sells_h1,
            "ratio_h1": ratio_h1,
            "h1_change": h1_change,
            "h6_change": h6_change,
            "h24_change": h24_change,
            "flow_score": flow_score,
        }

    except Exception as e:
        print("Dex fetch error:", search_term, e)
        return None

# =========================
# Token signal logic
# =========================
def classify_token_signal(m):
    ratio = m["ratio_h1"]
    flow = m["flow_score"]
    h1 = m["h1_change"]
    h6 = m["h6_change"]

    # هبوط قوي + شراء واضح = فرصة شراء
    if (h1 <= -8 or h6 <= -15) and ratio >= 1.4 and flow >= 6.5:
        return "buy_now", "هبوط قوي مع شراء واضح من السوق", "شراء الآن"

    # قوة واضحة = عزز تدريجي
    if flow >= 7 and ratio >= 1.35 and h1 <= 5:
        return "strong", "سيولة وشراء واضح — في قوة بالسوق", "عزّز بشكل تدريجي"

    # هبوط يحتاج مراقبة
    if h1 <= -6 or h6 <= -10:
        if ratio >= 1.1:
            return "dip_watch", "هبوط واضح لكن في ناس عم تشتري", "راقب الارتداد — لا تستعجل"
        return "risk", "ضغط بيع واضح وما في تأكيد شراء كافي", "لا دخول — انتبه"

    # حركة وتجميع
    if flow >= 5.8 and ratio >= 1.15:
        return "watch", "في حركة وتجميع يستحق المتابعة", "راقب — دخول تدريجي"

    return "none", "الوضع محايد — ما في إشارة قوية", "خليك كاش — انتظار"

def build_token_message(symbol, m, level, summary_ar, action_ar):
    icon = {
        "watch": "🟡",
        "strong": "🟢",
        "dip_watch": "🔻",
        "buy_now": "🚨",
        "risk": "🔴",
    }.get(level, "⚪")

    buy_power = min(10, m["ratio_h1"] * 4.2)

    return (
        f"{icon} **{symbol}**\n"
        f"**الزبدة:** {summary_ar}\n"
        f"**تدفق السيولة:** {m['flow_score']:.1f}/10\n"
        f"**قوة الشراء:** {buy_power:.1f}/10\n"
        f"**التغيّر 1س:** {fmt_pct(m['h1_change'])}\n"
        f"**السيولة:** {fmt_money(m['liq_usd'])}\n"
        f"👉 **Take Action:** {action_ar}"
    )

def monitor_tokens():
    for token in TOKENS:
        market = fetch_token_market(token["search"])
        if not market:
            continue

        symbol = token["symbol"]
        level, summary_ar, action_ar = classify_token_signal(market)

        if level == "none":
            continue

        current_signal = f"{level}:{round(market['h1_change'],1)}:{round(market['ratio_h1'],2)}:{round(market['flow_score'],1)}"
        if last_token_signals.get(symbol) == current_signal:
            continue

        msg = build_token_message(symbol, market, level, summary_ar, action_ar)
        send(msg)
        last_token_signals[symbol] = current_signal

# =========================
# Richard Heart monitor
# =========================
def monitor_richard_heart():
    global last_richard_status
    try:
        r = client.get("https://richardheart.com/", follow_redirects=True)
        online = 200 <= r.status_code < 400
    except Exception:
        online = False

    if last_richard_status is None:
        last_richard_status = online
        return

    if online != last_richard_status:
        if online:
            send(
                "🟢 **RichardHeart.com**\n"
                "**الحالة:** Online\n"
                "👉 **الزبدة:** الموقع رجع — راقب لاحتمال عودة النشاط أو بث"
            )
        else:
            send(
                "🔴 **RichardHeart.com**\n"
                "**الحالة:** Offline\n"
                "👉 **الزبدة:** الموقع مطفي — لا تغيير حالياً"
            )
        last_richard_status = online

def daily_richard_heart_update():
    global last_richard_daily_date
    today = datetime.now(timezone.utc).date()

    if last_richard_daily_date == today:
        return

    try:
        r = client.get("https://richardheart.com/", follow_redirects=True)
        online = 200 <= r.status_code < 400
    except Exception:
        online = False

    if online:
        send(
            "🟢 **RichardHeart.com — Daily Update**\n"
            "**الحالة:** Online\n"
            "👉 **الزبدة:** الموقع شغال اليوم — راقب لأي نشاط أو بث"
        )
    else:
        send(
            "🔴 **RichardHeart.com — Daily Update**\n"
            "**الحالة:** Offline\n"
            "👉 **الزبدة:** الموقع ما زال متوقف اليوم"
        )

    last_richard_daily_date = today

# =========================
# BTC / ETH monitor
# =========================
def monitor_btc_eth():
    global last_btc_eth_signals

    try:
        url = "https://api.coingecko.com/api/v3/coins/markets"
        params = {
            "vs_currency": "usd",
            "ids": "bitcoin,ethereum",
            "price_change_percentage": "1h,24h"
        }
        data = client.get(url, params=params).json()

        for coin in data:
            coin_id = coin["id"]
            name = coin["name"]
            ch1 = coin.get("price_change_percentage_1h_in_currency") or 0
            ch24 = coin.get("price_change_percentage_24h") or 0

            signal = None
            if ch1 >= 3 or ch24 >= 5:
                signal = "up"
            elif ch1 <= -3 or ch24 <= -5:
                signal = "down"

            if not signal:
                continue

            if last_btc_eth_signals.get(coin_id) == signal:
                continue

            if signal == "up":
                send(
                    f"🚨 **{name}**\n"
                    f"**الزبدة:** صعود قوي {ch1:.2f}% خلال 1س / {ch24:.2f}% خلال 24س\n"
                    f"👉 **Take Action:** راقب الزخم — لا تطارد"
                )
            else:
                send(
                    f"🔻 **{name}**\n"
                    f"**الزبدة:** هبوط واضح {ch1:.2f}% خلال 1س / {ch24:.2f}% خلال 24س\n"
                    f"👉 **Take Action:** راقب الدعم — لا تستعجل"
                )

            last_btc_eth_signals[coin_id] = signal

    except Exception as e:
        print("BTC/ETH error:", e)

# =========================
# Daily Market Insight
# =========================
def daily_market_insight():
    global last_market_insight_date
    today = datetime.now(timezone.utc).date()

    if last_market_insight_date == today:
        return

    try:
        url = "https://api.coingecko.com/api/v3/coins/markets"
        params = {"vs_currency": "usd", "ids": "bitcoin,ethereum"}
        data = client.get(url, params=params).json()

        btc = data[0]
        eth = data[1]

        avg = ((btc.get("price_change_percentage_24h") or 0) + (eth.get("price_change_percentage_24h") or 0)) / 2

        if avg > 2:
            state = "صعود"
            action = "راقب — دخول تدريجي"
        elif avg < -2:
            state = "هبوط"
            action = "خليك كاش — انتظار"
        else:
            state = "حيادي"
            action = "مراقبة فقط"

        send(
            f"📊 **Market Insight**\n"
            f"**اليوم:** السوق بحالة {state}\n"
            f"👉 **الزبدة:** نظرة عامة يومية بسيطة على BTC و ETH\n"
            f"👉 **Take Action:** {action}"
        )

        last_market_insight_date = today

    except Exception as e:
        print("Insight error:", e)

# =========================
# Main bot loop
# =========================
def run_bot():
    while True:
        try:
            monitor_tokens()
            monitor_richard_heart()
            daily_richard_heart_update()
            monitor_btc_eth()
            daily_market_insight()
        except Exception as e:
            print("Main loop error:", e)

        time.sleep(300)
