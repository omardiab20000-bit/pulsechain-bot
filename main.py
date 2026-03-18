import asyncio
from pulsechain_rotation_agent import PulsechainRotationAgent


async def main():
    print("BOT STARTING", flush=True)
    agent = PulsechainRotationAgent()

    # startup test message
    await agent.send_discord("✅ Bot LIVE - scanning PulseChain...")
    print("DISCORD TEST SENT", flush=True)

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

            await asyncio.sleep(300)

        except Exception as e:
            print(f"Error: {e}", flush=True)
            await asyncio.sleep(60)


if __name__ == "__main__":
    asyncio.run(main())
