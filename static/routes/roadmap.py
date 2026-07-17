import os
import json
import time

from dotenv import load_dotenv
from google import genai
from google.genai import types

load_dotenv()

# ── GEMINI CONFIG ──
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
gemini_client = genai.Client(api_key=GEMINI_API_KEY)


class RateLimitError(Exception):
    """Raised when Gemini rate-limits us even after retries."""
    pass


def generate_roadmap_with_ai(target_role, domain, weekly_hours=10, experience_level="beginner"):
    """
    Calls Gemini to generate a personalized career roadmap as structured JSON.

    Returns a dict matching this schema:
    {
      "title": str,
      "target_role": str,
      "total_weeks": int,
      "milestones": [
        {
          "week": int,
          "title": str,
          "task": str,
          "resource_url": str,
          "estimated_hours": int
        },
        ...
      ]
    }

    Raises:
        RateLimitError: if Gemini is rate-limited after 3 retries.
        json.JSONDecodeError: if Gemini's response isn't valid JSON.
    """
    prompt = f"""
You are a career roadmap generator. Create a personalized learning roadmap.

Target Role: {target_role}
Domain: {domain}
Available Time: {weekly_hours} hours/week
Experience Level: {experience_level}

Return ONLY valid JSON matching this exact schema:
{{
  "title": "string",
  "target_role": "string",
  "total_weeks": number,
  "milestones": [
    {{
      "week": number,
      "title": "string",
      "task": "string",
      "resource_url": "string (a real, working free resource link)",
      "estimated_hours": number
    }}
  ]
}}

Generate 6-10 milestones. Keep resource_url to well-known free platforms (MDN, freeCodeCamp, official docs, YouTube).
"""

    for attempt in range(3):
        try:
            response = gemini_client.models.generate_content(
                model="gemini-2.0-flash",
                contents=prompt,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json"
                )
            )
            return json.loads(response.text)

        except Exception as e:
            is_rate_limit = "RESOURCE_EXHAUSTED" in str(e) or "429" in str(e)

            if is_rate_limit:
                if attempt < 2:
                    time.sleep(2 ** attempt)  # 1s, 2s backoff
                    continue
                raise RateLimitError("Gemini rate limit hit after retries")

            # Non-rate-limit error (network issue, bad response, etc.)
            if attempt < 2:
                time.sleep(1)
                continue
            raise