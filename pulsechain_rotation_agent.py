import json
import os
import re
import time
import statistics
import html
from datetime import datetime, timezone
from urllib.parse import parse_qs, urlparse, unquote
import xml.etree.ElementTree as ET

import httpx

# =========================================================
# CONFIG
# =========================================================
DISCORD_WEBHOOK = "YOUR_WEBHOOK_HERE"

POLL_SECONDS = 600
MACRO_CACHE_SECONDS = 900
SCAN_CACHE_SECONDS = 1800
SENTIMENT_CACHE_SECONDS = 1800
STATE_SAVE_SECONDS = 120

TOKEN_ALERT_COOLDOWN_SECONDS = 60 * 25
ROTATION_ALERT_COOLDOWN_SECONDS = 60 * 45
MACRO_ALERT_COOLDOWN_SECONDS = 60 * 60

SENTIMENT_TRIGGER_PRICE_PCT = 4.0
SENTIMENT_TRIGGER_VOL_LIQ = 0.035
SENTIMENT_TRIGGER_LIQ_DELTA = 6.0
SENTIMENT_MAX_NEWS_ITEMS = 5
SENTIMENT_MAX_X_ITEMS = 5

DEX_SEARCH_URL = "https://api.dexscreener.com/latest/dex/search"
PULSESCAN_API = "https://api.scan.pulsechain.com/api"
COINGECKO_MARKETS = "https://api.coingecko.com/api/v3/coins/markets"
GOOGLE_NEWS_RSS = "https://news.google.com/rss/search"
DDG_HTML_SEARCH = "https://duckduckgo.com/html/"

DEBUG = True
STATE_FILE = "pulsechain_rotation_state.json"
TRANSFER_TOPIC0 = "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"

client = httpx.Client(
    timeout=httpx.Timeout(20.0, connect=10.0),
    follow_redirects=True,
    headers={"User-Agent": "PulseChainRotationAgent/9.0"},
)


import json
import os
import re
import time
import statistics
import html
from datetime import datetime, timezone
from urllib.parse import quote_plus, parse_qs, urlparse, unquote
import xml.etree.ElementTree as ET

import httpx

# =========================================================
# CONFIG
# =========================================================
DISCORD_WEBHOOK = "https://discord.com/api/webhooks/1483880814537216100/gM_wVR-G6zJrh05I30pkkVDLQ9YH-alYSWLR-f-4-MITMx7YR4RiVX-1qrSaN2sWM9or"

POLL_SECONDS = 600                    # 10 minutes
MACRO_CACHE_SECONDS = 900             # 15 minutes
SCAN_CACHE_SECONDS = 1800             # 30 minutes
SENTIMENT_CACHE_SECONDS = 1800        # 30 minutes
STATE_SAVE_SECONDS = 120              # save every 2 minutes max

TOKEN_ALERT_COOLDOWN_SECONDS = 60 * 25
ROTATION_ALERT_COOLDOWN_SECONDS = 60 * 45
MACRO_ALERT_COOLDOWN_SECONDS = 60 * 60

SENTIMENT_TRIGGER_PRICE_PCT = 4.0
SENTIMENT_TRIGGER_VOL_LIQ = 0.035
SENTIMENT_TRIGGER_LIQ_DELTA = 6.0
SENTIMENT_MAX_NEWS_ITEMS = 5
SENTIMENT_MAX_X_ITEMS = 5

DEX_SEARCH_URL = "https://api.dexscreener.com/latest/dex/search"
PULSESCAN_API = "https://api.scan.pulsechain.com/api"
COINGECKO_MARKETS = "https://api.coingecko.com/api/v3/coins/markets"
GOOGLE_NEWS_RSS = "https://news.google.com/rss/search"
DDG_HTML_SEARCH = "https://duckduckgo.com/html/"

DEBUG = True
STATE_FILE = "pulsechain_rotation_state.json"
TRANSFER_TOPIC0 = "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"

BULLISH_WORDS = {
    "bull", "bullish", "buy", "buys", "bought", "accumulate", "accumulation",
    "surge", "spike", "breakout", "breaks", "launch", "deployed", "deploys",
    "liquidity", "whale", "burn", "partnership", "listing", "trend", "trending",
    "volume", "adoption", "upgrade", "boost", "pumps", "pump"
}

BEARISH_WORDS = {
    "bear", "bearish", "sell", "sells", "dump", "dumps", "rug", "hack", "exploit",
    "drain", "down", "collapse", "liquidation", "fear", "panic", "red", "drop",
    "crash", "lawsuit", "warn", "warning", "scam", "weak", "outflow"
}

CATALYST_WORDS = {
    "deployed", "deploy", "liquidity", "listing", "launch", "burn", "bridge",
    "partnership", "upgrade", "buyback", "boost", "trend", "trending", "whale"
}

client = httpx.Client(
    timeout=20.0,
    follow_redirects=True,
    headers={"User-Agent": "PulseChainRotationAgent/9.0"}
)

# =========================================================
# TOKENS
# =========================================================
TOKENS = [
    {
        "symbol": "PLS",
        "label": "🟢 PLS",
        "search": "PLS pulsechain",
        "contract": "0xa1077a294dde1b09bb078844df40758a5d0f9a27",
        "news_query": '"PLS" PulseChain OR "PulseChain PLS"',
        "x_query": 'site:x.com ("PLS" "PulseChain" OR "PulseChain PLS")',
    },
    {
        "symbol": "PLSX",
        "label": "🟣 PLSX",
        "search": "PLSX pulsechain",
        "contract": "0x95b303987a60c71504d99aa1b13b4da07b0790ab",
        "news_query": '"PLSX" PulseChain OR "PulseX"',
        "x_query": 'site:x.com ("PLSX" OR "PulseX") PulseChain',
    },
    {
        "symbol": "PRVX",
        "label": "🧪 PRVX",
        "search": "PRVX pulsechain",
        "contract": "0xF6f8Db0aBa00007681F8fAF16A0FDa1c9B030b11",
        "news_query": '"PRVX" PulseChain OR "Provex" OR "ProveX"',
        "x_query": 'site:x.com ("PRVX" OR "Provex" OR "ProveX") PulseChain',
    },
]

# =========================================================
# COLORS
# =========================================================
GREEN = 0x2ECC71
RED = 0xE74C3C
YELLOW = 0xF1C40F
BLUE = 0x3498DB
PURPLE = 0x8E44AD

# =========================================================
# STATE
# =========================================================
last_token_states = {t["symbol"]: "neutral" for t in TOKENS}
last_token_signals = {t["symbol"]: None for t in TOKENS}
last_token_alert_time = {t["symbol"]: 0 for t in TOKENS}

last_rotation_state = None
last_rotation_alert_time = 0

last_macro_signal = None
last_macro_alert_time = 0

market_cache = {
    "bias": "neutral",
    "btc_24h": 0.0,
    "eth_24h": 0.0,
    "updated_at": 0.0,
}

latest_token_market = {}
last_liquidity_by_symbol = {}
last_state_save_ts = 0.0

scan_cache = {
    t["symbol"]: {
        "updated_at": 0.0,
        "recent_tx_count": 0,
        "unique_from_count": 0,
        "activity_score": 0.0,
        "transfer_count": 0,
        "unique_wallets": 0,
        "big_transfer_score": 0.0,
    }
    for t in TOKENS
}

sentiment_cache = {
    t["symbol"]: {
        "updated_at": 0.0,
        "sentiment_score": 0.0,
        "mood": "quiet",
        "summary": "📰 لا يوجد تأكيد اجتماعي واضح",
        "bullish_hits": 0,
        "bearish_hits": 0,
        "news_hits": 0,
        "x_hits": 0,
        "catalyst_hits": 0,
        "news_headlines": [],
        "x_headlines": [],
    }
    for t in TOKENS
}

scan_cursor = 0

# =========================================================
# HELPERS
# =========================================================
def log(*args):
    if DEBUG:
        print("[DEBUG]", *args, flush=True)


def safe_float(v, default=0.0):
    try:
        return float(v or 0)
    except Exception:
        return default


def safe_int(v, default=0):
    try:
        if isinstance(v, str) and v.startswith("0x"):
            return int(v, 16)
        return int(v or 0)
    except Exception:
        return default


def clamp(v, lo, hi):
    return max(lo, min(hi, v))


def can_send_again(last_ts, cooldown_seconds):
    return (time.time() - float(last_ts or 0)) >= cooldown_seconds


def utc_now():
    return datetime.now(timezone.utc)


def footer_stamp():
    return utc_now().strftime("%Y-%m-%d %H:%M UTC")


def strip_html(text):
    text = re.sub(r"<[^>]+>", " ", text or "")
    text = html.unescape(text)
    return re.sub(r"\s+", " ", text).strip()


def shorten(text, limit=110):
    text = (text or "").strip()
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 1)].rstrip() + "…"


def token_symbols():
    return [t["symbol"] for t in TOKENS]


def send_embed(title, description, color=PURPLE, url=None):
    if not DISCORD_WEBHOOK.startswith("https://discord.com/api/webhooks/"):
        print("Webhook not set correctly. Put your Discord webhook in DISCORD_WEBHOOK.", flush=True)
        return

    embed = {
        "title": title,
        "description": description,
        "color": color,
        "footer": {"text": f"PulseChain Rotation Agent • {footer_stamp()}"},
    }
    if url:
        embed["url"] = url

    payload = {"embeds": [embed]}

    try:
        r = client.post(DISCORD_WEBHOOK, json=payload)
        r.raise_for_status()
        print(f"[SEND] {title}", flush=True)
    except Exception as e:
        print("Webhook error:", e, flush=True)


def parse_topic_address(topic_value):
    if not topic_value or len(topic_value) < 42:
        return ""
    return "0x" + topic_value[-40:].lower()


def get_token_by_symbol(symbol):
    for t in TOKENS:
        if t["symbol"] == symbol:
            return t
    return None


def ensure_symbol_dict(base, default_value):
    return {symbol: base.get(symbol, default_value) for symbol in token_symbols()}


def save_state(force=False):
    global last_state_save_ts

    if not force and (time.time() - last_state_save_ts) < STATE_SAVE_SECONDS:
        return

    payload = {
        "last_token_states": last_token_states,
        "last_token_signals": last_token_signals,
        "last_token_alert_time": last_token_alert_time,
        "last_rotation_state": last_rotation_state,
        "last_rotation_alert_time": last_rotation_alert_time,
        "last_macro_signal": last_macro_signal,
        "last_macro_alert_time": last_macro_alert_time,
        "market_cache": market_cache,
        "last_liquidity_by_symbol": last_liquidity_by_symbol,
        "scan_cache": scan_cache,
        "sentiment_cache": sentiment_cache,
        "scan_cursor": scan_cursor,
    }

    try:
        with open(STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
        last_state_save_ts = time.time()
    except Exception as e:
        print("State save error:", e, flush=True)


def load_state():
    global last_rotation_state, last_rotation_alert_time
    global last_macro_signal, last_macro_alert_time
    global scan_cursor

    if not os.path.exists(STATE_FILE):
        return

    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)

        last_token_states.update(ensure_symbol_dict(data.get("last_token_states", {}), "neutral"))
        last_token_signals.update(ensure_symbol_dict(data.get("last_token_signals", {}), None))
        last_token_alert_time.update(ensure_symbol_dict(data.get("last_token_alert_time", {}), 0))

        last_rotation_state = data.get("last_rotation_state")
        last_rotation_alert_time = safe_float(data.get("last_rotation_alert_time"), 0.0)
        last_macro_signal = data.get("last_macro_signal")
        last_macro_alert_time = safe_float(data.get("last_macro_alert_time"), 0.0)

        if isinstance(data.get("market_cache"), dict):
            market_cache.update(data["market_cache"])

        if isinstance(data.get("last_liquidity_by_symbol"), dict):
            last_liquidity_by_symbol.update(data["last_liquidity_by_symbol"])

        if isinstance(data.get("scan_cache"), dict):
            for symbol in token_symbols():
                if isinstance(data["scan_cache"].get(symbol), dict):
                    scan_cache[symbol].update(data["scan_cache"][symbol])

        if isinstance(data.get("sentiment_cache"), dict):
            for symbol in token_symbols():
                if isinstance(data["sentiment_cache"].get(symbol), dict):
                    sentiment_cache[symbol].update(data["sentiment_cache"][symbol])

        scan_cursor = safe_int(data.get("scan_cursor"), 0)
        print("State loaded", flush=True)
    except Exception as e:
        print("State load error:", e, flush=True)


# =========================================================
# HTTP FETCHERS
# =========================================================
def get_json(url, params=None, timeout=10.0):
    r = client.get(url, params=params, timeout=timeout)
    r.raise_for_status()
    return r.json()


def get_text(url, params=None, timeout=10.0):
    r = client.get(url, params=params, timeout=timeout)
    r.raise_for_status()
    return r.text


# =========================================================
# MACRO
# =========================================================
def refresh_macro():
    if (time.time() - market_cache.get("updated_at", 0)) < MACRO_CACHE_SECONDS:
        return

    try:
        data = get_json(
            COINGECKO_MARKETS,
            params={
                "vs_currency": "usd",
                "ids": "bitcoin,ethereum",
                "price_change_percentage": "24h",
            },
            timeout=10.0,
        )

        coin_map = {c["id"]: c for c in data}
        btc = coin_map.get("bitcoin")
        eth = coin_map.get("ethereum")

        if not btc or not eth:
            print("Macro refresh: BTC or ETH missing", flush=True)
            return

        btc_24 = safe_float(btc.get("price_change_percentage_24h"))
        eth_24 = safe_float(eth.get("price_change_percentage_24h"))
        avg = (btc_24 + eth_24) / 2.0

        if avg >= 2.0:
            bias = "bullish"
        elif avg <= -2.0:
            bias = "bearish"
        else:
            bias = "neutral"

        market_cache.update(
            {
                "bias": bias,
                "btc_24h": btc_24,
                "eth_24h": eth_24,
                "updated_at": time.time(),
            }
        )
        print("Macro refreshed", flush=True)

    except Exception as e:
        print("Macro refresh error:", e, flush=True)


# =========================================================
# DEXSCREENER
# =========================================================
def fetch_token_dex(search_term):
    try:
        data = get_json(DEX_SEARCH_URL, params={"q": search_term}, timeout=10.0)
        pairs = data.get("pairs", [])
        if not pairs:
            return None

        pulse_pairs = [p for p in pairs if (p.get("chainId") or "").lower() == "pulsechain"]
        if pulse_pairs:
            pairs = pulse_pairs

        def score(p):
            liq = safe_float((p.get("liquidity") or {}).get("usd"))
            vol_h24 = safe_float((p.get("volume") or {}).get("h24"))
            tx_h1 = (p.get("txns") or {}).get("h1") or {}
            buys = safe_float(tx_h1.get("buys"))
            sells = safe_float(tx_h1.get("sells"))
            price_change = p.get("priceChange") or {}
            h1_change = abs(safe_float(price_change.get("h1")))
            s = liq * 0.58 + vol_h24 * 0.30 + (buys + sells) * 50 + h1_change * 220
            if liq < 25_000:
                s *= 0.70
            return s

        best = sorted(pairs, key=score, reverse=True)[0]

        tx1 = (best.get("txns") or {}).get("h1") or {}
        tx24 = (best.get("txns") or {}).get("h24") or {}
        liquidity = best.get("liquidity") or {}
        volume = best.get("volume") or {}
        price_change = best.get("priceChange") or {}

        buys_h1 = safe_float(tx1.get("buys"))
        sells_h1 = safe_float(tx1.get("sells"))
        buys_h24 = safe_float(tx24.get("buys"))
        sells_h24 = safe_float(tx24.get("sells"))

        ratio_h1 = buys_h1 / max(1.0, sells_h1)
        ratio_h24 = buys_h24 / max(1.0, sells_h24)

        liq_usd = safe_float(liquidity.get("usd"))
        vol_h1 = safe_float(volume.get("h1"))
        vol_h6 = safe_float(volume.get("h6"))
        vol_h24 = safe_float(volume.get("h24"))

        h1_change = safe_float(price_change.get("h1"))
        h6_change = safe_float(price_change.get("h6"))
        h24_change = safe_float(price_change.get("h24"))

        vol_liq_ratio = vol_h1 / max(liq_usd, 1.0)

        pair_address = best.get("pairAddress") or ""
        pair_url = best.get("url") or ""

        base_token = best.get("baseToken") or {}
        quote_token = best.get("quoteToken") or {}

        return {
            "pair_address": pair_address,
            "url": pair_url,
            "base_symbol": base_token.get("symbol") or "",
            "quote_symbol": quote_token.get("symbol") or "",
            "liq_usd": liq_usd,
            "vol_h1": vol_h1,
            "vol_h6": vol_h6,
            "vol_h24": vol_h24,
            "ratio_h1": ratio_h1,
            "ratio_h24": ratio_h24,
            "buys_h1": buys_h1,
            "sells_h1": sells_h1,
            "h1_change": h1_change,
            "h6_change": h6_change,
            "h24_change": h24_change,
            "vol_liq_ratio": vol_liq_ratio,
        }

    except Exception as e:
        print(f"Dex fetch error ({search_term}):", e, flush=True)
        return None


# =========================================================
# PULSESCAN
# =========================================================
def pulsescan_get(params, timeout=6.0):
    try:
        data = get_json(PULSESCAN_API, params=params, timeout=timeout)
        result = data.get("result", [])
        return result if isinstance(result, list) else result
    except Exception as e:
        print(f"PulseScan error ({params.get('action')}): {e}", flush=True)
        return [] if params.get("action") in ("getLogs", "txlist") else None


def get_latest_block():
    result = pulsescan_get({"module": "block", "action": "eth_block_number"}, timeout=5.0)
    if isinstance(result, str):
        return safe_int(result, 0)
    return 0


def get_logs(address, from_block, to_block, topic0=None):
    params = {
        "module": "logs",
        "action": "getLogs",
        "fromBlock": str(from_block),
        "toBlock": str(to_block),
        "address": address,
    }
    if topic0:
        params["topic0"] = topic0

    result = pulsescan_get(params, timeout=6.0)
    return result if isinstance(result, list) else []


def txlist_address(address, offset=25):
    result = pulsescan_get(
        {
            "module": "account",
            "action": "txlist",
            "address": address,
            "page": 1,
            "offset": offset,
            "sort": "desc",
        },
        timeout=6.0,
    )
    return result if isinstance(result, list) else []


# =========================================================
# SCAN ANALYSIS
# =========================================================
def analyze_contract_activity(contract_address):
    txs = txlist_address(contract_address, offset=25)
    if not txs:
        return None

    now_ts = int(time.time())
    recent_30m = 0
    recent_2h = 0
    unique_from = set()

    for tx in txs:
        ts = safe_int(tx.get("timeStamp"))
        from_addr = (tx.get("from") or "").lower()

        if from_addr:
            unique_from.add(from_addr)

        age = now_ts - ts
        if 0 <= age <= 1800:
            recent_30m += 1
        if 0 <= age <= 7200:
            recent_2h += 1

    activity_score = 0.0
    activity_score += clamp(recent_30m / 5.0, 0, 4.0)
    activity_score += clamp(recent_2h / 12.0, 0, 3.0)
    activity_score += clamp(len(unique_from) / 12.0, 0, 2.5)
    activity_score = clamp(activity_score, 0, 10)

    return {
        "recent_tx_count": recent_30m,
        "unique_from_count": len(unique_from),
        "activity_score": activity_score,
    }


def analyze_transfer_logs(token_contract, latest_block, blocks_back=350):
    if latest_block <= 0:
        return None

    from_block = max(0, latest_block - blocks_back)
    logs = get_logs(token_contract, from_block, latest_block, topic0=TRANSFER_TOPIC0)
    if not logs:
        return None

    amounts = []
    wallets = set()

    for log_item in logs:
        topics = log_item.get("topics") or []
        data_hex = log_item.get("data") or "0x0"

        if len(topics) >= 3:
            from_addr = parse_topic_address(topics[1])
            to_addr = parse_topic_address(topics[2])
            if from_addr:
                wallets.add(from_addr)
            if to_addr:
                wallets.add(to_addr)

        amounts.append(safe_int(data_hex, 0))

    amounts = [a for a in amounts if a > 0]
    if not amounts:
        return {
            "transfer_count": len(logs),
            "unique_wallets": len(wallets),
            "big_transfer_score": 0.0,
        }

    amounts_sorted = sorted(amounts)
    median_amt = statistics.median(amounts_sorted)
    max_amt = amounts_sorted[-1]
    p90_amt = amounts_sorted[max(0, int(len(amounts_sorted) * 0.9) - 1)]

    big_transfer_score = 0.0
    if median_amt > 0:
        if max_amt >= median_amt * 25:
            big_transfer_score += 3.0
        elif max_amt >= median_amt * 10:
            big_transfer_score += 1.8

        if p90_amt >= median_amt * 6:
            big_transfer_score += 1.2

    if len(logs) >= 18:
        big_transfer_score += 0.8
    if len(wallets) >= 12:
        big_transfer_score += 0.9

    big_transfer_score = clamp(big_transfer_score, 0, 6.0)

    return {
        "transfer_count": len(logs),
        "unique_wallets": len(wallets),
        "big_transfer_score": big_transfer_score,
    }


def analyze_liquidity_shift(symbol, current_liq):
    prev_liq = last_liquidity_by_symbol.get(symbol)

    if prev_liq is None or prev_liq <= 0:
        last_liquidity_by_symbol[symbol] = current_liq
        return {
            "liq_delta_pct": 0.0,
            "lp_add_hint": 0.0,
            "lp_remove_hint": 0.0,
        }

    delta_pct = ((current_liq - prev_liq) / prev_liq) * 100.0
    last_liquidity_by_symbol[symbol] = current_liq

    lp_add_hint = 0.0
    lp_remove_hint = 0.0

    if delta_pct >= 6:
        lp_add_hint = clamp(delta_pct / 4.0, 0, 4.0)
    elif delta_pct <= -6:
        lp_remove_hint = clamp(abs(delta_pct) / 4.0, 0, 4.0)

    return {
        "liq_delta_pct": delta_pct,
        "lp_add_hint": lp_add_hint,
        "lp_remove_hint": lp_remove_hint,
    }


def refresh_one_scan_layer(latest_block):
    global scan_cursor

    token = TOKENS[scan_cursor % len(TOKENS)]
    scan_cursor += 1

    symbol = token["symbol"]
    cached = scan_cache[symbol]

    if (time.time() - cached["updated_at"]) < SCAN_CACHE_SECONDS:
        return

    contract_activity = analyze_contract_activity(token["contract"])
    transfer_stats = analyze_transfer_logs(token["contract"], latest_block)

    if contract_activity is None and transfer_stats is None:
        print(f"[SCAN] {symbol} failed, keeping previous cache", flush=True)
        return

    new_data = dict(cached)

    if contract_activity is not None:
        new_data.update(contract_activity)

    if transfer_stats is not None:
        new_data.update(transfer_stats)

    new_data["updated_at"] = time.time()
    scan_cache[symbol] = new_data
    print(f"[SCAN] refreshed {symbol}", flush=True)


# =========================================================
# SENTIMENT / CATALYST INVESTIGATION
# =========================================================
def count_keywords(text, words):
    found = 0
    lowered = re.sub(r"[^a-z0-9\s]", " ", (text or "").lower())
    for word in words:
        if re.search(rf"\b{re.escape(word)}\b", lowered):
            found += 1
    return found


def parse_google_news_rss(xml_text, max_items=5):
    items = []
    try:
        root = ET.fromstring(xml_text)
        for item in root.findall(".//item")[:max_items]:
            title = strip_html(item.findtext("title", default=""))
            link = (item.findtext("link", default="") or "").strip()
            description = strip_html(item.findtext("description", default=""))
            if not title:
                continue
            items.append({
                "title": title,
                "link": link,
                "snippet": description,
                "text": f"{title} {description}".strip(),
            })
    except Exception as e:
        print("Google News parse error:", e, flush=True)
    return items


def fetch_google_news_items(query, max_items=5):
    try:
        xml_text = get_text(
            GOOGLE_NEWS_RSS,
            params={
                "q": query,
                "hl": "en-US",
                "gl": "US",
                "ceid": "US:en",
            },
            timeout=10.0,
        )
        return parse_google_news_rss(xml_text, max_items=max_items)
    except Exception as e:
        print("Google News fetch error:", e, flush=True)
        return []


def normalize_ddg_url(raw_href):
    href = html.unescape(raw_href or "")
    parsed = urlparse(href)

    if parsed.netloc.endswith("duckduckgo.com") and parsed.path.startswith("/l/"):
        qs = parse_qs(parsed.query)
        uddg = qs.get("uddg")
        if uddg:
            return unquote(uddg[0])

    if href.startswith("//"):
        return "https:" + href

    return href


def parse_duckduckgo_x_results(html_text, max_items=5):
    items = []
    pattern = re.compile(
        r'<a[^>]+class="result__a"[^>]+href="(?P<href>[^"]+)"[^>]*>(?P<title>.*?)</a>',
        re.IGNORECASE | re.DOTALL,
    )
    matches = list(pattern.finditer(html_text))

    for match in matches:
        href = normalize_ddg_url(match.group("href"))
        if "x.com/" not in href and "twitter.com/" not in href:
            continue

        title = strip_html(match.group("title"))
        trailer = html_text[match.end(): match.end() + 500]
        snippet = ""

        snippet_match = re.search(r'<a[^>]+class="result__snippet"[^>]*>(.*?)</a>', trailer, re.IGNORECASE | re.DOTALL)
        if snippet_match:
            snippet = strip_html(snippet_match.group(1))
        else:
            snippet_match = re.search(r'<div[^>]+class="result__snippet"[^>]*>(.*?)</div>', trailer, re.IGNORECASE | re.DOTALL)
            if snippet_match:
                snippet = strip_html(snippet_match.group(1))

        if title:
            items.append({
                "title": title,
                "link": href,
                "snippet": snippet,
                "text": f"{title} {snippet}".strip(),
            })
        if len(items) >= max_items:
            break

    return items


def fetch_x_mentions_via_search(query, max_items=5):
    try:
        html_text = get_text(DDG_HTML_SEARCH, params={"q": query}, timeout=12.0)
        return parse_duckduckgo_x_results(html_text, max_items=max_items)
    except Exception as e:
        print("DuckDuckGo X search error:", e, flush=True)
        return []


def score_items(items):
    bullish_hits = 0
    bearish_hits = 0
    catalyst_hits = 0
    headlines = []

    for item in items:
        text = item.get("text", "")
        bullish_hits += count_keywords(text, BULLISH_WORDS)
        bearish_hits += count_keywords(text, BEARISH_WORDS)
        catalyst_hits += count_keywords(text, CATALYST_WORDS)
        headlines.append(shorten(item.get("title", ""), 95))

    return {
        "bullish_hits": bullish_hits,
        "bearish_hits": bearish_hits,
        "catalyst_hits": catalyst_hits,
        "headlines": headlines[:5],
    }


def should_refresh_sentiment(symbol, market):
    cached = sentiment_cache[symbol]
    age = time.time() - safe_float(cached.get("updated_at"), 0.0)
    if age >= SENTIMENT_CACHE_SECONDS:
        return True

    if abs(market.get("h1_change", 0.0)) >= SENTIMENT_TRIGGER_PRICE_PCT:
        return True
    if market.get("vol_liq_ratio", 0.0) >= SENTIMENT_TRIGGER_VOL_LIQ:
        return True
    if abs(market.get("liq_delta_pct", 0.0)) >= SENTIMENT_TRIGGER_LIQ_DELTA:
        return True
    return False


def summarize_sentiment(score, bull, bear, catalysts, news_count, x_count):
    if news_count == 0 and x_count == 0:
        return "📰 لا يوجد تأكيد اجتماعي واضح", "quiet"
    if score >= 3.5 or (bull >= bear + 3 and catalysts >= 1):
        return "📰 الضجة إيجابية وعم تدعم الحركة", "positive"
    if score <= -3.5 or (bear >= bull + 3):
        return "📰 الضجة سلبية أو فيها خوف", "negative"
    if catalysts >= 2 and bull >= bear:
        return "📰 في catalyst خفيف بس التأكيد متوسط", "catalyst"
    return "📰 الضجة موجودة لكن مو حاسمة", "mixed"


def refresh_sentiment_for_token(token, market):
    symbol = token["symbol"]
    cached = sentiment_cache[symbol]

    if not should_refresh_sentiment(symbol, market):
        return cached

    news_items = fetch_google_news_items(token["news_query"], max_items=SENTIMENT_MAX_NEWS_ITEMS)
    x_items = fetch_x_mentions_via_search(token["x_query"], max_items=SENTIMENT_MAX_X_ITEMS)

    news_score = score_items(news_items)
    x_score = score_items(x_items)

    bullish_hits = news_score["bullish_hits"] + x_score["bullish_hits"]
    bearish_hits = news_score["bearish_hits"] + x_score["bearish_hits"]
    catalyst_hits = news_score["catalyst_hits"] + x_score["catalyst_hits"]

    sentiment_score = 0.0
    sentiment_score += clamp((bullish_hits - bearish_hits) * 0.9, -6.0, 6.0)
    sentiment_score += clamp(catalyst_hits * 0.7, 0.0, 3.0)
    sentiment_score += 1.2 if abs(market.get("h1_change", 0.0)) >= SENTIMENT_TRIGGER_PRICE_PCT else 0.0
    sentiment_score += 0.8 if market.get("vol_liq_ratio", 0.0) >= SENTIMENT_TRIGGER_VOL_LIQ else 0.0
    if market.get("h1_change", 0.0) < 0 and bullish_hits > bearish_hits:
        sentiment_score += 0.6
    if market.get("h1_change", 0.0) > 0 and bearish_hits > bullish_hits:
        sentiment_score -= 0.6
    sentiment_score = clamp(sentiment_score, -10.0, 10.0)

    summary, mood = summarize_sentiment(
        sentiment_score,
        bullish_hits,
        bearish_hits,
        catalyst_hits,
        len(news_items),
        len(x_items),
    )

    snapshot = {
        "updated_at": time.time(),
        "sentiment_score": sentiment_score,
        "mood": mood,
        "summary": summary,
        "bullish_hits": bullish_hits,
        "bearish_hits": bearish_hits,
        "news_hits": len(news_items),
        "x_hits": len(x_items),
        "catalyst_hits": catalyst_hits,
        "news_headlines": news_score["headlines"],
        "x_headlines": x_score["headlines"],
    }

    sentiment_cache[symbol] = snapshot
    print(f"[SENTIMENT] refreshed {symbol} mood={mood} score={round(sentiment_score, 2)}", flush=True)
    return snapshot


# =========================================================
# SNAPSHOT BUILD
# =========================================================
def build_market_snapshot(token):
    dex = fetch_token_dex(token["search"])
    if not dex:
        return None

    liq_stats = analyze_liquidity_shift(token["symbol"], dex["liq_usd"])
    scan_stats = scan_cache[token["symbol"]]
    sentiment = refresh_sentiment_for_token(token, {**dex, **liq_stats})

    whale_pressure = 0.0
    whale_pressure += clamp((dex["vol_h1"] / max(dex["liq_usd"] * 0.08, 1.0)), 0, 4.0)
    if dex["ratio_h1"] >= 1.30:
        whale_pressure += 2.0
    elif dex["ratio_h1"] >= 1.15:
        whale_pressure += 1.0
    if dex["h1_change"] < 0 and dex["ratio_h1"] >= 1.15:
        whale_pressure += 1.2
    whale_pressure += scan_stats["big_transfer_score"] * 0.6
    whale_pressure = clamp(whale_pressure, 0, 10)

    accumulation_score = 0.0
    accumulation_score += clamp(min(4.0, dex["ratio_h1"]) * 1.5, 0, 6.0)
    accumulation_score += 1.2 if dex["vol_liq_ratio"] >= 0.04 else 0.0
    accumulation_score += 1.0 if dex["h1_change"] < 0 and dex["ratio_h1"] >= 1.1 else 0.0
    accumulation_score += 0.8 if dex["h6_change"] > 0 else 0.0
    accumulation_score += 0.6 if dex["liq_usd"] >= 100_000 else 0.0
    accumulation_score += clamp(scan_stats["activity_score"] * 0.12, 0, 1.3)
    accumulation_score += liq_stats["lp_add_hint"] * 0.5
    if sentiment["mood"] in ("positive", "catalyst"):
        accumulation_score += 0.5
    accumulation_score = clamp(accumulation_score, 0, 10)

    sell_pressure = 0.0
    if dex["ratio_h1"] < 1.0:
        sell_pressure += 2.5
    if dex["h1_change"] <= -3:
        sell_pressure += 1.5
    if dex["h6_change"] <= -6:
        sell_pressure += 1.8
    if dex["vol_liq_ratio"] >= 0.04 and dex["ratio_h1"] < 1.0:
        sell_pressure += 1.2
    if scan_stats["activity_score"] >= 5.5 and dex["ratio_h1"] < 1.0:
        sell_pressure += 0.8
    sell_pressure += liq_stats["lp_remove_hint"] * 0.6
    if sentiment["mood"] == "negative":
        sell_pressure += 0.6
    sell_pressure = clamp(sell_pressure, 0, 10)

    merged = {}
    merged.update(dex)
    merged.update(scan_stats)
    merged.update(liq_stats)
    merged["whale_pressure"] = whale_pressure
    merged["accumulation_score"] = accumulation_score
    merged["sell_pressure"] = sell_pressure
    merged["sentiment"] = sentiment
    return merged


# =========================================================
# TOKEN SIGNALS
# =========================================================
def derive_token_signal(symbol, m):
    ratio = m["ratio_h1"]
    h1 = m["h1_change"]
    h6 = m["h6_change"]
    whale = m["whale_pressure"]
    accumulation = m["accumulation_score"]
    sell_pressure = m["sell_pressure"]
    macro_bias = market_cache.get("bias", "neutral")
    sentiment = m.get("sentiment") or {}
    sentiment_mood = sentiment.get("mood", "quiet")

    state = "neutral"
    mood = "neutral"
    action = "خليك كاش — انتظار"

    if accumulation >= 5.8 and ratio >= 1.15:
        if h1 < 0:
            state = "accumulate"
            mood = "bullish"
            action = "راقب — دخول تدريجي"
        else:
            state = "strong"
            mood = "bullish"
            action = "عزّز بشكل تدريجي"

    if whale >= 6.2 and ratio >= 1.18:
        state = "strong"
        mood = "bullish"
        action = "راقب — لا تطارد"

    if sell_pressure >= 5.5 and ratio < 1.0:
        state = "sell"
        mood = "bearish"
        action = "خليك كاش — خطر"

    if h1 <= -8 and ratio < 0.95:
        state = "flush"
        mood = "bearish"
        action = "لا دخول — انتبه"

    if macro_bias == "bearish" and mood == "bullish" and h1 <= 0:
        state = "watch"
        mood = "watch"
        action = "راقب — لا تستعجل"

    if symbol == "PLS":
        if state in ("accumulate", "strong"):
            summary = "🧠 السوق عم يجمع بولس"
        elif state in ("sell", "flush"):
            summary = "🧠 في ضغط بيع على بولس"
        elif state == "watch":
            summary = "🧠 بولس تحت المراقبة"
        else:
            summary = "🧠 بولس هادئة"
    elif symbol == "PLSX":
        if state in ("accumulate", "strong"):
            summary = "🧠 السوق عم يجمع بولس اكس"
        elif state in ("sell", "flush"):
            summary = "🧠 في ضغط بيع على بولس اكس"
        elif state == "watch":
            summary = "🧠 بولس اكس تحت المراقبة"
        else:
            summary = "🧠 بولس اكس هادئة"
    else:
        if state in ("accumulate", "strong"):
            summary = "🧠 في تجميع على PRVX"
        elif state in ("sell", "flush"):
            summary = "🧠 PRVX تحت ضغط"
        elif state == "watch":
            summary = "🧠 PRVX تحت المراقبة"
        else:
            summary = "🧠 PRVX هادئة"

    reasons = []
    if mood == "bullish":
        reasons.append("📈 المشترين أقوى")
        if h1 < 0 and ratio >= 1.1:
            reasons.append("🛡️ الهبوط عم ينشفط")
        elif h6 > 0:
            reasons.append("⚡ الحركة تتحسن")
        if macro_bias == "bullish":
            reasons.append("🌤️ السوق العام مساعد")
    elif mood == "bearish":
        reasons.append("📉 البائعين أقوى")
        if h6 <= -6:
            reasons.append("🌧️ الضغط واضح")
        if macro_bias == "bearish":
            reasons.append("⚠️ السوق العام سلبي")
    elif mood == "watch":
        reasons.append("👀 في حركة لكن مو مؤكدة")
        reasons.append("🫥 بدها تأكيد")

    if sentiment_mood in ("positive", "catalyst"):
        reasons.append("📰 الضجة داعمة")
    elif sentiment_mood == "negative":
        reasons.append("📰 الضجة ضد الحركة")
    elif sentiment_mood == "mixed":
        reasons.append("📰 الأخبار مختلطة")

    return {
        "state": state,
        "mood": mood,
        "summary": summary,
        "reasons": reasons[:3],
        "action": action,
    }


def should_send_token_alert(symbol, signal_key, state):
    prev_state = last_token_states.get(symbol, "neutral")
    prev_signal = last_token_signals.get(symbol)
    cooldown_ok = can_send_again(last_token_alert_time.get(symbol), TOKEN_ALERT_COOLDOWN_SECONDS)

    if state == "neutral":
        return False
    if prev_state == "neutral":
        return True
    if prev_state != state:
        return True
    if prev_signal != signal_key and cooldown_ok:
        return True
    return False


def format_sentiment_block(sentiment):
    mood = sentiment.get("mood", "quiet")
    score = round(safe_float(sentiment.get("sentiment_score"), 0.0), 1)
    news_hits = safe_int(sentiment.get("news_hits"), 0)
    x_hits = safe_int(sentiment.get("x_hits"), 0)
    catalyst_hits = safe_int(sentiment.get("catalyst_hits"), 0)

    lines = [f"- {sentiment.get('summary', '📰 لا يوجد تأكيد اجتماعي واضح')} (score {score})"]
    lines.append(f"- 🔎 news={news_hits} | x-indexed={x_hits} | catalyst={catalyst_hits}")

    top_news = (sentiment.get("news_headlines") or [])[:1]
    top_x = (sentiment.get("x_headlines") or [])[:1]
    if top_news:
        lines.append(f"- 🗞️ {top_news[0]}")
    if top_x and mood != "quiet":
        lines.append(f"- 𝕏 {top_x[0]}")
    return "\n".join(lines)


def monitor_tokens():
    global latest_token_market
    latest_token_market = {}

    for token in TOKENS:
        symbol = token["symbol"]
        label = token["label"]

        market = build_market_snapshot(token)
        if not market:
            print(f"[TOKEN] {symbol} no market data", flush=True)
            continue

        latest_token_market[symbol] = market
        signal = derive_token_signal(symbol, market)
        sentiment = market.get("sentiment") or {}

        state = signal["state"]
        mood = signal["mood"]

        signal_key = (
            f"{state}|{mood}|"
            f"{round(market['ratio_h1'], 2)}|"
            f"{round(market['h1_change'], 1)}|"
            f"{round(market['h6_change'], 1)}|"
            f"{round(market['whale_pressure'], 1)}|"
            f"{round(market['accumulation_score'], 1)}|"
            f"{round(market['sell_pressure'], 1)}|"
            f"{round(market['activity_score'], 1)}|"
            f"{round(market['liq_delta_pct'], 1)}|"
            f"{round(market['big_transfer_score'], 1)}|"
            f"{sentiment.get('mood', 'quiet')}|"
            f"{round(safe_float(sentiment.get('sentiment_score'), 0.0), 1)}"
        )

        print(f"[TOKEN] {symbol} state={state} mood={mood} key={signal_key}", flush=True)

        if not should_send_token_alert(symbol, signal_key, state):
            last_token_states[symbol] = state
            last_token_signals[symbol] = signal_key
            continue

        if mood == "bullish":
            color = GREEN
            icon = "🟢"
        elif mood == "bearish":
            color = RED
            icon = "🔴"
        elif mood == "watch":
            color = YELLOW
            icon = "🟡"
        else:
            color = PURPLE
            icon = "⚪"

        lines = [signal["summary"]]
        lines.extend(signal["reasons"])

        desc = "\n".join(f"- {x}" for x in lines)
        desc += "\n"
        desc += format_sentiment_block(sentiment)
        desc += (
            f"\n- 📊 ratio={market['ratio_h1']:.2f} | h1={market['h1_change']:.1f}% | "
            f"liqΔ={market['liq_delta_pct']:.1f}% | whale={market['whale_pressure']:.1f}"
        )
        desc += f"\n\n👉 **Take Action:** {signal['action']}"

        send_embed(f"{icon} {label}", desc, color, url=market.get("url") or None)

        last_token_alert_time[symbol] = time.time()
        last_token_states[symbol] = state
        last_token_signals[symbol] = signal_key


# =========================================================
# ROTATION
# =========================================================
def detect_rotation():
    pls = latest_token_market.get("PLS")
    plsx = latest_token_market.get("PLSX")

    if not pls or not plsx:
        return None

    pls_strength = (
        pls["accumulation_score"] * 0.42 +
        pls["whale_pressure"] * 0.28 +
        clamp(pls["ratio_h1"], 0, 3) * 1.20 +
        clamp(pls["activity_score"], 0, 10) * 0.15 +
        clamp(pls["big_transfer_score"], 0, 6) * 0.22 +
        max(pls["liq_delta_pct"], 0) * 0.04 +
        clamp(safe_float((pls.get("sentiment") or {}).get("sentiment_score"), 0.0), -3.0, 3.0) * 0.18
    )

    plsx_strength = (
        plsx["accumulation_score"] * 0.42 +
        plsx["whale_pressure"] * 0.28 +
        clamp(plsx["ratio_h1"], 0, 3) * 1.20 +
        clamp(plsx["activity_score"], 0, 10) * 0.15 +
        clamp(plsx["big_transfer_score"], 0, 6) * 0.22 +
        max(plsx["liq_delta_pct"], 0) * 0.04 +
        clamp(safe_float((plsx.get("sentiment") or {}).get("sentiment_score"), 0.0), -3.0, 3.0) * 0.18
    )

    diff = plsx_strength - pls_strength

    if diff >= 2.2 and plsx["ratio_h1"] >= 1.12:
        return {
            "state": "to_plsx",
            "title": "🟣 Rotation Alert",
            "desc": "- 🧠 في انتقال سيولة نحو بولس اكس\n- ⚡ بولس اكس عم تبين أقوى من بولس\n\n👉 **Take Action:** راقب بولس اكس أكثر",
            "color": BLUE,
        }

    if diff <= -2.2 and pls["ratio_h1"] >= 1.12:
        return {
            "state": "to_pls",
            "title": "🟢 Rotation Alert",
            "desc": "- 🧠 في انتقال سيولة نحو بولس\n- ⚡ بولس عم تبين أقوى من بولس اكس\n\n👉 **Take Action:** راقب بولس أكثر",
            "color": BLUE,
        }

    return None


def monitor_rotation():
    global last_rotation_state, last_rotation_alert_time

    rotation = detect_rotation()
    if not rotation:
        return

    state = rotation["state"]
    cooldown_ok = can_send_again(last_rotation_alert_time, ROTATION_ALERT_COOLDOWN_SECONDS)

    if state == last_rotation_state and not cooldown_ok:
        return

    send_embed(rotation["title"], rotation["desc"], rotation["color"])
    last_rotation_state = state
    last_rotation_alert_time = time.time()


# =========================================================
# MACRO ALERTS
# =========================================================
def monitor_macro():
    global last_macro_signal, last_macro_alert_time

    bias = market_cache.get("bias", "neutral")
    if bias == "neutral":
        return

    if bias == last_macro_signal and not can_send_again(last_macro_alert_time, MACRO_ALERT_COOLDOWN_SECONDS):
        return

    if bias == "bullish":
        send_embed(
            "🟢 ₿ Bitcoin / ⟠ Ethereum",
            "- 🧠 السوق العام إيجابي\n- 🌤️ هذا الشي ممكن يساعد الألتات\n\n👉 **Take Action:** راقب الزخم — لا تطارد",
            GREEN,
        )
    else:
        send_embed(
            "🔴 ₿ Bitcoin / ⟠ Ethereum",
            "- 🧠 السوق العام تحت ضغط\n- ⚠️ هذا الشي يضغط على الألتات\n\n👉 **Take Action:** خفف الاندفاع — انتبه",
            RED,
        )

    last_macro_signal = bias
    last_macro_alert_time = time.time()


# =========================================================
# MAIN LOOP
# =========================================================
def run_cycle():
    refresh_macro()
    latest_block = get_latest_block()
    refresh_one_scan_layer(latest_block)
    monitor_tokens()
    monitor_rotation()
    monitor_macro()
    save_state()
    print("Loop completed successfully", flush=True)


def run_bot():
    load_state()
    print("PulseChain Rotation Agent PRO started...", flush=True)

    while True:
        try:
            run_cycle()
        except KeyboardInterrupt:
            save_state(force=True)
            raise
        except Exception as e:
            print("Main loop error:", e, flush=True)
            save_state(force=True)

        time.sleep(POLL_SECONDS)


if __name__ == "__main__":
    run_bot()
