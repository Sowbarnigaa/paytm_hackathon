"""Minimal Sarvam AI check: one chat completion with sarvam-105b-conversations."""
import os
from pathlib import Path

from sarvamai import SarvamAI

# Load SARVAM_API_KEY from .env if it is not already in the environment (no extra dependency).
env_file = Path(__file__).with_name(".env")
if "SARVAM_API_KEY" not in os.environ and env_file.exists():
    for line in env_file.read_text().splitlines():
        name, _, value = line.partition("=")
        if name.strip() == "SARVAM_API_KEY":
            os.environ["SARVAM_API_KEY"] = value.strip().strip("\"'")

api_key = os.environ.get("SARVAM_API_KEY")
if not api_key:
    raise SystemExit("SARVAM_API_KEY is not set - add it to .env")

client = SarvamAI(api_subscription_key=api_key)

response = client.chat.completions(
    model="sarvam-105b-conversations",
    messages=[{"role": "user", "content": "In one sentence, what can you help a kirana store owner with?"}],
    max_tokens=1024,
)
print(response.choices[0].message.content)
