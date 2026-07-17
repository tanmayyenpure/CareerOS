"""
Standalone test — isolates whether the problem is the API key itself,
or how Flask/app.py is loading it.

Run: python test_key.py
Then delete this file.
"""
import os
from dotenv import load_dotenv

load_dotenv()

key = os.getenv("OPENROUTER_API_KEY")

print("─" * 50)
print("KEY REPR:  ", repr(key))
print("KEY LENGTH:", len(key) if key else 0)
print("─" * 50)

if not key:
    print("❌ No key found in .env at all. Check the .env file exists")
    print("   in the same folder as this script, and the line reads:")
    print("   OPENROUTER_API_KEY=sk-or-v1-xxxxxxxx  (no quotes)")
    raise SystemExit(1)

if key != key.strip():
    print("⚠️  WARNING: key has leading/trailing whitespace or a hidden")
    print("   newline character. Fix your .env line — retype it manually")
    print("   instead of pasting, or remove any quotes around the value.")

from openai import OpenAI

client = OpenAI(base_url="https://openrouter.ai/api/v1", api_key=key)

try:
    response = client.chat.completions.create(
        model="meta-llama/llama-3.3-70b-instruct:free",
        messages=[{"role": "user", "content": "Say hi in 3 words."}]
    )
    print("✅ SUCCESS! OpenRouter responded:")
    print(response.choices[0].message.content)
except Exception as e:
    print("❌ FAILED:", e)
