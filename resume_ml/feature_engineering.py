"""
feature_engineering.py
-----------------------
Deterministic, rule-based feature extraction from raw resume text.
No LLM calls here — these are regex / lexicon-based signals that feed
both the ATS-style structural score and the ML classifier's inputs.
"""

import re

SECTION_PATTERNS = {
    "contact_info": r"(email|phone|contact|linkedin|github)",
    "summary": r"\b(summary|objective|profile)\b",
    "education": r"\b(education|academic|qualification|b\.?tech|bachelor|master|university|college)\b",
    "experience": r"\b(experience|employment|work history|internship)\b",
    "skills": r"\b(skills|technical skills|technologies|proficienc)\b",
    "projects": r"\b(projects?|portfolio)\b",
    "certifications": r"\b(certifications?|licenses?)\b",
    "achievements": r"\b(achievements?|awards?|honou?rs?)\b",
}

ACTION_VERBS = [
    "led", "built", "developed", "designed", "implemented", "created",
    "managed", "improved", "increased", "reduced", "launched", "optimized",
    "automated", "architected", "engineered", "delivered", "coordinated",
    "analyzed", "researched", "mentored", "spearheaded", "streamlined",
    "deployed", "collaborated", "achieved", "initiated", "resolved",
]

EMAIL_RE = re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}")
PHONE_RE = re.compile(r"(\+?\d{1,3}[-.\s]?)?\(?\d{3,5}\)?[-.\s]?\d{3,4}[-.\s]?\d{3,4}")
LINKEDIN_RE = re.compile(r"linkedin\.com/\S+", re.IGNORECASE)
GITHUB_RE = re.compile(r"github\.com/\S+", re.IGNORECASE)
QUANTIFIED_RE = re.compile(r"(\d+(\.\d+)?\s?%|\$\s?\d+|₹\s?\d+|\b\d{2,}\+?\b)")
BULLET_RE = re.compile(r"(^|\n)\s*[•\-\*\u2022]\s+")


def clean_text(text: str) -> str:
    text = text.replace("\r", " ")
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def clean_for_tfidf(text: str) -> str:
    """Normalization used both at training time and inference time —
    must stay identical on both sides or the vectorizer's vocabulary
    mapping goes stale."""
    text = re.sub(r"http\S+", " ", str(text))
    text = re.sub(r"[^A-Za-z0-9\s.,%+#-]", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip().lower()


def extract_features(resume_text: str) -> dict:
    """Returns a dict of structural + lexical features used for scoring
    and, where noted, as auxiliary ML inputs."""
    raw = resume_text or ""
    lower = raw.lower()
    words = re.findall(r"[a-zA-Z']+", raw)
    word_count = len(words)

    sections_found = {
        name: bool(re.search(pattern, lower))
        for name, pattern in SECTION_PATTERNS.items()
    }

    action_verb_hits = sum(1 for v in ACTION_VERBS if re.search(rf"\b{v}\b", lower))
    bullet_count = len(BULLET_RE.findall(raw))
    quantified_count = len(QUANTIFIED_RE.findall(raw))

    return {
        "word_count": word_count,
        "has_email": bool(EMAIL_RE.search(raw)),
        "has_phone": bool(PHONE_RE.search(raw)),
        "has_linkedin": bool(LINKEDIN_RE.search(raw)),
        "has_github": bool(GITHUB_RE.search(raw)),
        "sections_found": sections_found,
        "section_coverage": sum(sections_found.values()) / len(sections_found),
        "action_verb_count": action_verb_hits,
        "bullet_count": bullet_count,
        "quantified_achievement_count": quantified_count,
    }
