"""
Learning Hub backend routes.

Drop these into app.py (or a blueprint if you've split routes out).
Mirrors the same pattern roadmap generation already uses: ask Gemini
for structured JSON, parse it, fail soft with a clear error if it
breaks. Adjust the Gemini call itself (`call_gemini_json`) to match
whatever helper you already built for roadmap generation — if you
already have a working "ask Gemini for JSON" function, use that one
instead of duplicating it here.
"""

import json
import os

import google.generativeai as genai
from flask import jsonify, request, session

genai.configure(api_key=os.getenv("GEMINI_API_KEY"))
GEMINI_MODEL = "gemini-2.5-flash"


def call_gemini_json(prompt):
    """
    Sends `prompt` to Gemini and parses the response as JSON.
    Raises on any failure — callers are expected to catch and
    respond with a clean error, same as youtube_helper.py's
    fail-soft pattern.
    """
    model = genai.GenerativeModel(GEMINI_MODEL)
    response = model.generate_content(
        prompt,
        generation_config={"response_mime_type": "application/json"},
    )
    return json.loads(response.text)


# =====================================================================
# POST /api/learning-hub/subjects
# body: { "domain": "Engineering & Technology" }
# returns: { "subjects": [ { "name", "description", "tags": [...] }, ... ] }
# =====================================================================
@app.route("/api/learning-hub/subjects", methods=["POST"])
def learning_hub_subjects():
    data = request.get_json(silent=True) or {}
    domain = (data.get("domain") or "").strip()

    if not domain:
        return jsonify({"error": "Missing domain"}), 400

    prompt = f"""You are helping build a study syllabus browser for Indian students and job-seekers.

Domain: "{domain}"

Return 6 to 8 core subjects/specializations that fall under this domain in the
Indian education/career context. For each subject give a short 1-sentence
description and 2-3 short tag words (e.g. difficulty, category).

Respond with ONLY raw JSON, no markdown fences, no commentary, in exactly
this shape:

{{
  "subjects": [
    {{
      "name": "Data Structures & Algorithms",
      "description": "Core problem-solving skills tested in every tech interview.",
      "tags": ["Core", "Interview-critical"]
    }}
  ]
}}
"""

    try:
        result = call_gemini_json(prompt)
        subjects = result.get("subjects", [])
        if not isinstance(subjects, list):
            raise ValueError("Malformed subjects response")
        return jsonify({"subjects": subjects})
    except Exception as e:
        print(f"Learning Hub subjects generation failed for domain {domain!r}: {e}")
        return jsonify({"error": "Could not generate subjects right now."}), 502


# =====================================================================
# POST /api/learning-hub/material
# body: { "domain": "...", "subject": "..." }
# returns: {
#   "overview": str,
#   "topics": [ { "title", "explanation" }, ... ],
#   "resources": [ { "label", "url" }, ... ]
# }
# =====================================================================
@app.route("/api/learning-hub/material", methods=["POST"])
def learning_hub_material():
    data = request.get_json(silent=True) or {}
    domain = (data.get("domain") or "").strip()
    subject = (data.get("subject") or "").strip()

    if not domain or not subject:
        return jsonify({"error": "Missing domain or subject"}), 400

    prompt = f"""You are building a study guide for an Indian student learning
"{subject}" within the "{domain}" domain.

Return:
1. A 2-3 sentence overview of what this subject covers and why it matters.
2. 5 to 7 key topics within this subject, each with a 1-2 sentence plain-English
   explanation a beginner could follow.
3. 3 to 5 real, generally well-known learning resources (official docs,
   well-known free course platforms, NPTEL/SWAYAM for Indian academic
   subjects, etc.) as a label and URL. Only include resource types that are
   safe to link (do not invent a URL you are not confident is a real,
   existing page — prefer a platform's homepage/search page over a guessed
   deep link if unsure).

Respond with ONLY raw JSON, no markdown fences, no commentary, in exactly
this shape:

{{
  "overview": "...",
  "topics": [
    {{ "title": "...", "explanation": "..." }}
  ],
  "resources": [
    {{ "label": "...", "url": "..." }}
  ]
}}
"""

    try:
        result = call_gemini_json(prompt)
        return jsonify({
            "overview": result.get("overview", ""),
            "topics": result.get("topics", []),
            "resources": result.get("resources", []),
        })
    except Exception as e:
        print(f"Learning Hub material generation failed for {domain!r}/{subject!r}: {e}")
        return jsonify({"error": "Could not generate study material right now."}), 502


# =====================================================================
# Page route
# =====================================================================
@app.route("/learning-hub")
def learning_hub():
    # Reuses whatever pattern your other pages use for `user` context
    # (login_required decorator, session lookup, etc.) — wire this up
    # the same way dashboard/profile/roadmap already do.
    return render_template("learning-hub.html", user=current_user, stats={})
