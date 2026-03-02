"""
One-time setup script: creates the Vapi voice assistant via the Vapi REST API.

Usage:
    python create_vapi_assistant.py --url https://your-app.onrender.com

The --url argument is the public base URL of your deployed FastAPI backend.
The script will patch that URL into the tool config before creating the assistant.

Requires VAPI_API_KEY in your .env file.
"""

import argparse
import copy
import json
import os
import sys

import httpx
from dotenv import load_dotenv

VAPI_API_BASE = "https://api.vapi.ai"
CONFIG_FILE = "vapi_config.json"


def load_config(deployed_url: str) -> dict:
    with open(CONFIG_FILE) as f:
        config = json.load(f)

    # Patch the tool server URL with the real deployed URL
    tools = config.get("model", {}).get("tools", [])
    for tool in tools:
        if tool.get("server", {}).get("url") == "YOUR_DEPLOYED_URL/vapi/tool-call":
            tool["server"]["url"] = f"{deployed_url.rstrip('/')}/vapi/tool-call"

    return config


def create_assistant(config: dict, api_key: str) -> dict:
    with httpx.Client() as client:
        response = client.post(
            f"{VAPI_API_BASE}/assistant",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json=config,
            timeout=30,
        )

    if response.status_code not in (200, 201):
        print(f"Error {response.status_code}: {response.text}")
        sys.exit(1)

    return response.json()


def main():
    load_dotenv()

    parser = argparse.ArgumentParser(description="Create the Vapi scheduling assistant.")
    parser.add_argument(
        "--url",
        required=True,
        help="Public base URL of your deployed backend (e.g. https://my-app.onrender.com)",
    )
    args = parser.parse_args()

    api_key = os.environ.get("VAPI_API_KEY")
    if not api_key:
        print("Error: VAPI_API_KEY is not set in your .env file.")
        sys.exit(1)

    print(f"Loading config from {CONFIG_FILE}...")
    config = load_config(args.url)

    print("Creating assistant on Vapi...")
    assistant = create_assistant(config, api_key)

    assistant_id = assistant.get("id")
    print("\nAssistant created successfully!")
    print(f"  ID   : {assistant_id}")
    print(f"  Name : {assistant.get('name')}")
    print(f"\nNext steps:")
    print(f"  1. Go to https://dashboard.vapi.ai and open the assistant '{assistant.get('name')}'")
    print(f"  2. Assign a phone number (Buy > Phone Numbers) and link it to this assistant")
    print(f"  3. Call the number — the voice agent is live!")
    print(f"\nTo test via web widget, use assistant ID: {assistant_id}")


if __name__ == "__main__":
    main()
