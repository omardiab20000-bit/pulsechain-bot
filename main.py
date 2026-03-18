import asyncio
from pulsechain_rotation_agent import PulsechainRotationAgent

async def main():
    agent = PulsechainRotationAgent()

    await agent.send_discord("✅ Bot LIVE - scanning PulseChain...")

    while True:
        try:
            for symbol, address in agent.WATCH_TOKENS.items():
                pairs = await agent.fetch_token_pairs(address)
                primary = agent.choose_primary_pair(pairs)

                if primary:
                    agent.append_history(symbol, primary)

                    if agent.should_alert(symbol):
                        msg = agent.format_signal(symbol)
                        if msg:
                            await agent.send_discord(msg)
                            agent.last_alert_at[symbol] = asyncio.get_event_loop().time()

            await asyncio.sleep(300)

        except Exception as e:
            print("Error:", e)
            await asyncio.sleep(60)

asyncio.run(main())
