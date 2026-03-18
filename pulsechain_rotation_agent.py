import os
import math
import httpx
from collections import defaultdict, deque

DEX_URL = "https://api.dexscreener.com/latest/dex/tokens/{}"


class PulsechainRotationAgent:
    def __init__(self):
        self.client = httpx.AsyncClient(timeout=30.0)

        self.WATCH_TOKENS = {
            "PLS": "0xa1077a294dde1b09bb078844df40758a5d0f9a27",
            "PLSX": "0x95b303987a60c71504d99aa1b13b4da07b0790ab",
            "PROVEX": "0xf6f8db0aba00007681f8faf16a0fda1c9b030b11",
        }

        self.webhook = os.getenv("DISCORD_WEBHOOK_URL", "").strip()

        self.FAST_SCAN_SECONDS = int(os.getenv("FAST_SCAN_SECONDS", "300"))      # 5 min
        self.SUMMARY_SECONDS = int(os.getenv("SUMMARY_SECONDS", "14400"))        # 4 hours
        self.ALERT_COOLDOWN_SECONDS = int(os.getenv("ALERT_COOLDOWN_SECONDS", "1800"))  # 30 min
        self.MIN_LIQUIDITY_USD = float(os.getenv("MIN_LIQUIDITY_USD", "25000"))

        self.STABLE_SYMBOLS = {
            s.strip().upper()
            for s in os.getenv("STABLE_SYMBOLS", "USDC,USDT,DAI").split(",")
            if s.strip()
        }

        self.history = defaultdict(lambda: deque(maxlen=48))
        self.last_signal_time = {}
        self.last_signal_tier = {}
        self.last_summary_time = 0.0

    async def fetch_token_pairs(self, address):
        response = await self.client.get(DEX_URL.format(address))
        response.raise_for_status()
        data = response.json()
        return data.get("pairs", [])

    def choose_primary_pair(self, pairs):
        if not pairs:
            return None

        pulse_pairs = [
            p for p in pairs
            if p.get("chainId") == "pulsechain"
        ]

        if not pulse_pairs:
            return None

        filtered = []
        for p in pulse_pairs:
            liq = float((p.get("liquidity") or {}).get("usd") or 0)
            if liq >= self.MIN_LIQUIDITY_USD:
                filtered.append(p)

        if not filtered:
            filtered = pulse_pairs

        stable_quoted = [
            p for p in filtered
            if str((p.get("quoteToken") or {}).get("symbol") or "").upper() in self.STABLE_SYMBOLS
        ]

        if stable_quoted:
            return max(
                stable_quoted,
                key=lambda p: float((p.get("liquidity") or {}).get("usd") or 0)
            )

        return max(
            filtered,
            key=lambda p: float((p.get("liquidity") or {}).get("usd") or 0)
        )

    def append_history(self, symbol, pair):
        self.history[symbol].append(pair)

    def get_pair(self, symbol):
        if not self.history[symbol]:
            return None
        return self.history[symbol][-1]

    def get_chart_link(self, pair):
        pair_address = pair.get("pairAddress")
        if pair_address:
            return f"https://dexscreener.com/pulsechain/{pair_address}"
        token_address = (pair.get("baseToken") or {}).get("address", "")
        return f"https://dexscreener.com/pulsechain/{token_address}"

    def format_money(self, value):
        value = float(value or 0)
        if value >= 1_000_000_000:
            return f"${value / 1_000_000_000:.1f}B"
        if value >= 1_000_000:
            return f"${value / 1_000_000:.1f}M"
        if value >= 1_000:
            return f"${value / 1_000:.1f}K"
        return f"${value:.0f}"

    def volume_liq(self, pair):
        liquidity = float((pair.get("liquidity") or {}).get("usd") or 0)
        volume = float((pair.get("volume") or {}).get("h24") or 0)
        if liquidity <= 0:
            return 0.0
        return volume / liquidity

    def pressure(self, pair):
        txns = pair.get("txns") or {}
        h1 = txns.get("h1") or {}

        buys = int(h1.get("buys") or 0)
        sells = int(h1.get("sells") or 0)

        if sells == 0:
            return float(buys) if buys > 0 else 1.0
        return buys / sells

    def price_change_1h(self, pair):
        return float((pair.get("priceChange") or {}).get("h1") or 0)

    def liquidity_usd(self, pair):
        return float((pair.get("liquidity") or {}).get("usd") or 0)

    def volume_24h(self, pair):
        return float((pair.get("volume") or {}).get("h24") or 0)

    def quote_symbol(self, pair):
        return str((pair.get("quoteToken") or {}).get("symbol") or "").upper()

    def is_stable_quoted(self, pair):
        return self.quote_symbol(pair) in self.STABLE_SYMBOLS

    def liquidity_growth_pct(self, symbol):
        hist = list(self.history[symbol])
        if len(hist) < 2:
            return 0.0

        lookback = hist[-12] if len(hist) >= 12 else hist[0]
        first = float((lookback.get("liquidity") or {}).get("usd") or 0)
        last = float((hist[-1].get("liquidity") or {}).get("usd") or 0)

        if first <= 0:
            return 0.0
        return ((last - first) / first) * 100

    def detect_absorption(self, pair, symbol):
        vol_liq = self.volume_liq(pair)
        pressure = self.pressure(pair)
        price_1h = self.price_change_1h(pair)
        liq_growth = self.liquidity_growth_pct(symbol)

        return (
            pressure < 1.0
            and price_1h > -1.5
            and vol_liq >= 0.8
            and liq_growth >= -2.0
        )

    def compute_score(self, pair, symbol):
        vol_liq = self.volume_liq(pair)
        pressure = self.pressure(pair)
        price_1h = self.price_change_1h(pair)
        liq_growth = self.liquidity_growth_pct(symbol)

        score = 0.0
        score += min(vol_liq * 35, 50)
        score += min(max(pressure - 1.0, 0) * 20, 25)
        score += min(max(price_1h, 0) * 2.5, 15)
        score += min(max(liq_growth, 0) * 0.6, 10)
        return round(score, 1)

    def build_signal(self, symbol):
        pair = self.get_pair(symbol)
        if not pair:
            return None

        liquidity = self.liquidity_usd(pair)
        volume = self.volume_24h(pair)
        vol_liq = self.volume_liq(pair)
        pressure = self.pressure(pair)
        price_1h = self.price_change_1h(pair)
        liq_growth = self.liquidity_growth_pct(symbol)
        stable_quoted = self.is_stable_quoted(pair)
        absorption = self.detect_absorption(pair, symbol)
        chart = self.get_chart_link(pair)
        score = self.compute_score(pair, symbol)

        if volume <= 0 or liquidity <= 0:
            return None

        if absorption:
            tier = "ACCUMULATION"
            emoji = "🧲"
            title = "Absorption"
            action = "🎯 Action: Watch closely / supply may be getting absorbed"
            flow = "➡️ Flow: Selling is getting absorbed"
            note = "✅ Price holding despite sell pressure"
        elif vol_liq >= 1.5 and pressure >= 1.2 and price_1h > 0:
            tier = "CONFIRMED"
            emoji = "🔥"
            title = "High Conviction"
            action = "🎯 Action: Confirmed momentum / consider scaling in"
            flow = f"➡️ Flow: OUT of stables → Into {symbol}" if stable_quoted else f"➡️ Flow: Strong risk-on into {symbol}"
            note = "🟢 Breakout conditions look confirmed"
        elif vol_liq >= 1.2 and pressure >= 1.2 and price_1h <= 0:
            tier = "EARLY"
            emoji = "🟡"
            title = "Early Rotation"
            action = "🎯 Action: Watch for 1H flip green before entry"
            flow = f"➡️ Flow: Quiet accumulation / rotation building into {symbol}"
            note = "👀 Buyers active, but price has not confirmed yet"
        elif pressure < 0.9 and price_1h < 0:
            tier = "DEFENSIVE"
            emoji = "🔴"
            title = "Defensive"
            action = "🎯 Action: Stay patient / avoid chasing"
            flow = "➡️ Flow: Defensive / sellers still in control"
            note = "🔴 Weak pressure and price still soft"
        else:
            return None

        return {
            "symbol": symbol,
            "tier": tier,
            "emoji": emoji,
            "title": title,
            "action": action,
            "flow": flow,
            "note": note,
            "liquidity": liquidity,
            "volume": volume,
            "vol_liq": vol_liq,
            "pressure": pressure,
            "price_1h": price_1h,
            "liq_growth": liq_growth,
            "score": score,
            "chart": chart,
        }

    def should_send_signal(self, symbol, signal):
        now = self._now()
        last_time = self.last_signal_time.get(symbol, 0.0)
        last_tier = self.last_signal_tier.get(symbol)

        # Always allow new tier changes immediately
        if last_tier and signal["tier"] != last_tier:
            return True

        # Otherwise enforce cooldown
        if now - last_time < self.ALERT_COOLDOWN_SECONDS:
            return False

        return True

    def mark_signal_sent(self, symbol, signal):
        self.last_signal_time[symbol] = self._now()
        self.last_signal_tier[symbol] = signal["tier"]

    def summary_due(self):
        return self._now() - self.last_summary_time >= self.SUMMARY_SECONDS

    def mark_summary_sent(self):
        self.last_summary_time = self._now()

    def build_leaderboard_summary(self):
        rows = []

        for symbol in self.WATCH_TOKENS.keys():
            pair = self.get_pair(symbol)
            if not pair:
                continue

            signal = self.build_signal(symbol)
            score = self.compute_score(pair, symbol)
            flow = signal["flow"].replace("➡️ Flow: ", "") if signal else "No strong signal"
            rows.append((symbol, score, flow))

        if not rows:
            return None

        rows.sort(key=lambda x: x[1], reverse=True)
        top = rows[:3]

        lines = ["🏆 **4H Rotation Leaderboard**", ""]
        for i, (symbol, score, flow) in enumerate(top, start=1):
            lines.append(f"{i}️⃣ **{symbol}** — Score {score:.0f}")
            lines.append(f"   {flow}")

        return "\n".join(lines)

    def format_signal(self, symbol, signal):
        return (
            f"{signal['emoji']} **{symbol} {signal['title']}**\n\n"
            f"💧 Liq: {self.format_money(signal['liquidity'])} ({signal['liq_growth']:+.1f}%)\n"
            f"📊 Vol/Liq: {signal['vol_liq']:.2f}\n"
            f"💰 Vol: {self.format_money(signal['volume'])}\n"
            f"⚖️ Pressure: {signal['pressure']:.2f}\n"
            f"📈 1H Price: {signal['price_1h']:+.2f}%\n"
            f"🧠 Score: {signal['score']:.0f}/100\n\n"
            f"{signal['flow']}\n"
            f"{signal['note']}\n\n"
            f"{signal['action']}\n"
            f"🔗 Chart: {signal['chart']}"
        )

    async def send_discord(self, message):
        if not self.webhook:
            print("DISCORD_WEBHOOK_URL missing", flush=True)
            return

        response = await self.client.post(
            self.webhook,
            json={"content": message}
        )

        print(f"Discord status: {response.status_code}", flush=True)
        if response.status_code >= 400:
            print(f"Discord response: {response.text}", flush=True)

    def _now(self):
        # monotonic-ish enough for cooldowns in one process
        import time
        return time.monotonic()
