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
        first = float((lookback.get("liquidity
