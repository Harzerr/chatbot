import asyncio
import os
from pathlib import Path

from dotenv import load_dotenv
from langgraph_sdk import get_client

PROJECT_ROOT = Path(__file__).resolve().parents[1]
load_dotenv(PROJECT_ROOT / ".env")

LANGGRAPH_API_URL = os.getenv("LANGGRAPH_API_URL", "http://127.0.0.1:2024")
LANGGRAPH_ASSISTANT_ID = os.getenv("LANGGRAPH_ASSISTANT_ID", "agent")
LANGGRAPH_TEST_MESSAGE = os.getenv("LANGGRAPH_TEST_MESSAGE", "What is LangGraph?")

client = get_client(url=LANGGRAPH_API_URL)

async def main():
    print(f"Connecting to {LANGGRAPH_API_URL} with assistant '{LANGGRAPH_ASSISTANT_ID}'")

    async for chunk in client.runs.stream(
        None,  # Threadless run
        LANGGRAPH_ASSISTANT_ID,  # Name of assistant. Defined in langgraph.json.
        input={
        "messages": [{
            "role": "human",
            "content": LANGGRAPH_TEST_MESSAGE,
            }],
        },
    ):
        print(f"Receiving new event of type: {chunk.event}...")
        print(chunk.data)
        print("\n\n")

asyncio.run(main())
