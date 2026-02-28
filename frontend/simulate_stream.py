"""Simulate LLM-style token streaming to the drawing service."""

from __future__ import annotations

import asyncio
import random
import sys

import httpx

URL = "http://localhost:8002/draw"
SESSION = "dev-session"

TEXT = (
    "The Pythagorean theorem states that for any right triangle, "
    "the square of the hypotenuse equals the sum of the squares "
    "of the other two sides. We write this as a² + b² = c². "
    "Let me draw a triangle to show you."
)


async def main() -> None:
    async with httpx.AsyncClient(timeout=10.0) as client:
        try:
            await client.get("http://localhost:8002/health")
        except httpx.ConnectError:
            print("Drawing service not running on :8002")
            sys.exit(1)

        words = TEXT.split()
        for i, word in enumerate(words):
            await client.post(URL, json={
                "command_id": f"sim-{i}",
                "session_id": SESSION,
                "operation": "draw_text",
                "payload": {
                    "text": word,
                    "x": round(0.05 + (i % 10) * 0.09, 2),
                    "y": round(0.1 + (i // 10) * 0.08, 2),
                    "font_size": 18,
                    "style": {"stroke_color": "#333"},
                },
            })
            sys.stdout.write(word + " ")
            sys.stdout.flush()

            delay = 0.3 if word[-1] in ".,!?" else random.uniform(0.04, 0.15)
            await asyncio.sleep(delay)

        print("\nDone.")


if __name__ == "__main__":
    asyncio.run(main())
