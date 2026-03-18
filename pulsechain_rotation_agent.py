import os
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

        self.history = defaultdict(lambda: deque(maxlen=20))
        self.last_signal_time = {}
        self.last_signal_type = {}

    async def fetch_token_pairs(self, address):
        res = await self.client.get(DEX_URL.format(address))
        return res.json().get("pairs", [])

    def choose_primary_pair(self, pairs):
        if not pairs:
            return None
        return max(pairs, key=lambda p: float((p.get("liquidity") or {}).get("usd") or 0))

    def append_history(self, symbol, pair):
        self.history[symbol].append(pair)

    def get_pair(self, symbol):
        return self.history[symbol][-1] if self.history[symbol] else None

    def liquidity_usd(self, pair):
        return float((pair.get("liquidity") or {}).get("usd") or 0)

    def volume_24h(self, pair):
        return float((pair.get("volume") or {}).get("h24") or 0)

    def volume_liq(self, pair):
        liq = self.liquidity_usd(pair)
        vol = self.volume_24h(pair)
        return vol / liq if liq > 0 else 0

    def pressure(self, pair):
        txns = pair.get("txns") or {}
        h1 = txns.get("h1") or {}
        buys = h1.get("buys", 0)
        sells = h1.get("sells", 1)
        return buys / sells if sells else buys

    def price_change_1h(self, pair):
        return float((pair.get("priceChange") or {}).get("h1") or 0)

    def liquidity_growth_pct(self, symbol):
        hist = list(self.history[symbol])
        if len(hist) < 2:
            return 0
        first = float((hist[0].get("liquidity") or {}).get("usd") or 0)
        last = float((hist[-1].get("liquidity") or {}).get("usd") or 0)
        return ((last - first) / first) * 100 if first > 0 else 0

    def get_chart_link(self, pair):
        return f"https://dexscreener.com/pulsechain/{pair.get('pairAddress')}"

    def build_signal(self,
