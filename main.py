import asyncio
from pulsechain_rotation_agent import PulsechainRotationAgent


async def main():
    agent = PulsechainRotationAgent()

    print("BOT STARTING", flush=True)
    await agent.send_discord("✅ Bot LIVE - scanning PulseChain...")

    while True:
        try:
            # Scan all watched tokens
            for symbol, address in agent.WATCH_TOKENS.items():
                try:
                    pairs = await agent.fetch_token_pairs(address)
                    primary = agent.choose_primary_pair(pairs)
                    if primary:
                        agent.append_history(symbol, primary)
                except Exception as token_error:
                    print(f"[{symbol}] scan error: {token_error}", flush=True)

            # Send signal alerts
            for symbol in agent.WATCH_TOKENS.keys():
                try:
                    signal = agent.build_signal(symbol)
                    if signal and agent.should_send_signal(symbol, signal):
                        await agent.send_discord(agent.format_signal(symbol, signal))
                        agent.mark_signal_sent(symbol, signal)
                except Exception as signal_error:
                    print(f"[{symbol}] signal error: {signal_error}", flush=True)

            # Send 4H summary if due
            try:
                if agent.summary_due():
                    summary = agent.build_leaderboard_summary()
                    if summary:
                        await agent.send_discord(summary)
                        agent.mark_summary_sent()
            except Exception as summary_error:
                print(f"[SUMMARY] error: {summary_error}", flush=True)

            await asyncio.sleep(agent.FAST_SCAN_SECONDS)

        except Exception as loop_error:
            print(f"[LOOP] fatal error: {loop_error}", flush=True)
            await asyncio.sleep(60)


if __name__ == "__main__":
    asyncio.run(main())
