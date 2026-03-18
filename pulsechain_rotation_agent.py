import os
import httpx

DEX_URL = "https://api.dexscreener.com/latest/dex/tokens/{}"


class PulsechainRotationAgent:
    WATCH_TOKENS = {
        "PLS": "0xa1077a294dde1b09bb078844df40758a5d0f9a27",
        "PLSX": "0x95b303987a60c71504d99aa1b13b4da07b0790ab",
        "PROVEX": "0xf6f8db0aba00007681f8faf16a0fda1c9b030b11",
    }

    def __init__(self):
        self.client = httpx.AsyncClient(timeout=30.0)
        self.history = {}
        self.webhook = os.getenv("DISCORD_WEBHOOK_URL", "").strip()

    async def fetch_token_pairs(self, address):
        response = await self.client.get(DEX_URL.format(address))
        response.raise_for_status()
        data = response.json()
        return data.get("pairs", [])

    def choose_primary_pair(self, pairs):
        if not pairs:
            return None

        pulse_pairs = [p for p in pairs if p.get("chainId") == "pulsechain"]
        if not pulse_pairs:
            return None

        return max(
            pulse_pairs,
            key=lambda p: float((p.get("liquidity") or {}).get("usd") or 0),
        )

    def append_history(self, symbol, pair):
        self.history[symbol] = pair

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

    def should_alert(self, symbol):
        pair = self.history.get(symbol)
        if not pair:
            return False

        return self.volume_liq(pair) > 1.0

    def format_money(self, value):
        value = float(value or 0)

        if value >= 1_000_000_000:
            return f"${value / 1_000_000_000:.1f}B"
        if value >= 1_000_000:
            return f"${value / 1_000_000:.1f}M"
        if value >= 1_000:
            return f"${value / 1_000:.1f}K"
        return f"${value:.0f}"

    def format_signal(self, symbol):
        pair = self.history[symbol]

        liquidity = float((pair.get("liquidity") or {}).get("usd") or 0)
        volume = float((pair.get("volume") or {}).get("h24") or 0)
        vol_liq = self.volume_liq(pair)
        pressure = self.pressure(pair)
        price_change_1h = float((pair.get("priceChange") or {}).get("h1") or 0)

        if vol_liq > 1.5 and pressure > 1.1:
            emoji = "🔥"
            title = "High Conviction"
            action = "🎯 Action: Consider entry / scale in"
        elif vol_liq > 1.0:
            emoji = "🟡"
            title = "Watch"
            action = "🎯 Action: Wait for confirmation"
        else:
            emoji = "🔴"
            title = "Weak"
            action = "🎯 Action: Stay patient / watch list"

        return (
            f"{emoji} **{symbol} {title}**\n\n"
            f"💧 Liq: {self.format_money(liquidity)}\n"
            f"📊 Vol/Liq: {vol_liq:.2f}\n"
            f"💰 Vol: {self.format_money(volume)}\n"
            f"⚖️ Pressure: {pressure:.2f}\n"
            f"📈 1H Price: {price_change_1h:+.2f}%\n\n"
            f"{action}"
        )

    async def send_discord(self, message):
        if not self.webhook:
            print("DISCORD_WEBHOOK_URL missing", flush=True)
            return

        response = await self.client.post(
            self.webhook,
            json={"content": message},
        )

        print(f"Discord status: {response.status_code}", flush=True)
        if response.status_code >= 400:
            print(f"Discord response: {response.text}", flush=True)
