"""
Standalone reference copy of the roadmap-generation logic. app.py has its
own inline copy of this (kept there so it has access to gemini_client /
db models without an import cycle) — this file is for reference and for
seed/test scripts that want to call generate_roadmap_with_ai() directly
without booting the whole Flask app.

NOTE: keep this in sync with the version inside app.py if you change the
prompt or schema.
"""
import os
import json
import time

from dotenv import load_dotenv
from google import genai
from google.genai import types

from youtube_helper import enrich_milestones_with_videos

load_dotenv()

# ── GEMINI CONFIG ──
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
gemini_client = genai.Client(api_key=GEMINI_API_KEY)


class RateLimitError(Exception):
    """Raised when Gemini rate-limits us even after retries."""
    pass


def _call_gemini_json(prompt, model="gemini-2.0-flash"):
    for attempt in range(3):
        try:
            response = gemini_client.models.generate_content(
                model=model,
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
                    time.sleep(2 ** attempt)
                    continue
                raise RateLimitError("Gemini rate limit hit after retries")
            if attempt < 2:
                time.sleep(1)
                continue
            raise


def generate_roadmap_with_ai(target_role, domain, weekly_hours=10, experience_level="beginner"):
    """
    Calls Gemini to generate a personalized career roadmap as structured JSON,
    then replaces the AI's guessed links with real YouTube videos found via
    the YouTube Data API (youtube_helper.py) instead of trusting the model
    to invent working URLs.

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
          "resource_url": str,        # real YouTube link (added post-hoc)
          "resource_title": str,      # real video title (added post-hoc)
          "resource_channel": str,    # real channel name (added post-hoc)
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
      "search_keywords": ["2-4 words to find a real tutorial video for this milestone"],
      "estimated_hours": number
    }}
  ]
}}

Generate 6-10 milestones. Do NOT invent URLs — only provide search_keywords,
those will be used to look up a real video separately.
"""
    data = _call_gemini_json(prompt)
    data["milestones"] = enrich_milestones_with_videos(data.get("milestones", []))
    return data
