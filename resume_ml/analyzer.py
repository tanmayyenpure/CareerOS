"""
analyzer.py
-----------
Drop-in replacement for app.py's generate_resume_analysis_with_ai().
Returns the exact same schema (selection_chance, ats_score, summary,
missing_sections, keyword_gaps, strengths, suggestions) but computed
from a trained scikit-learn classifier + deterministic rule-based
features, instead of an LLM call.

Usage in app.py:
    from resume_ml.analyzer import MLResumeAnalyzer
    ml_analyzer = MLResumeAnalyzer()
    ...
    data = ml_analyzer.analyze(resume_text, user.target_role)
"""

import json
import os
import re

import joblib

from .feature_engineering import extract_features, clean_for_tfidf

HERE = os.path.dirname(os.path.abspath(__file__))
MODELS_DIR = os.path.join(HERE, "models")


class MLResumeAnalyzer:
    def __init__(self, models_dir: str = MODELS_DIR):
        vec_path = os.path.join(models_dir, "tfidf_vectorizer.joblib")
        clf_path = os.path.join(models_dir, "category_classifier.joblib")
        kw_path = os.path.join(models_dir, "category_keywords.json")

        if not (os.path.exists(vec_path) and os.path.exists(clf_path)):
            raise FileNotFoundError(
                "Model artifacts not found. Run `python resume_ml/train_classifier.py` first."
            )

        self.vectorizer = joblib.load(vec_path)
        self.clf = joblib.load(clf_path)
        self.categories = list(self.clf.classes_)

        with open(kw_path) as f:
            self.category_keywords = json.load(f)

    # ---------- role -> trained category mapping ----------
    def _map_role_to_category(self, target_role: str):
        if not target_role:
            return None
        role_l = target_role.lower()
        for cat in self.categories:
            if cat.lower() in role_l or role_l in cat.lower():
                return cat
        role_tokens = set(re.findall(r"[a-z]+", role_l))
        best, best_score = None, 0
        for cat in self.categories:
            cat_tokens = set(re.findall(r"[a-z]+", cat.lower()))
            overlap = len(role_tokens & cat_tokens)
            if overlap > best_score:
                best, best_score = cat, overlap
        return best

    # ---------- scoring ----------
    @staticmethod
    def _structural_score(features: dict) -> int:
        score = 0.0
        score += features["section_coverage"] * 40
        score += min(1.0, features["action_verb_count"] / 8) * 20
        score += min(1.0, features["quantified_achievement_count"] / 6) * 20
        score += 5 if features["has_email"] else 0
        score += 5 if features["has_phone"] else 0
        score += 5 if features["has_linkedin"] else 0
        score += 5 if features["has_github"] else 0
        return round(max(0.0, min(100.0, score)))

    def _keyword_gaps(self, clean_text: str, category: str) -> list:
        if not category:
            return []
        candidates = self.category_keywords.get(category, [])
        gaps = []
        for term in candidates:
            # skip generic single-char/short noise terms
            if len(term) < 3:
                continue
            if not re.search(rf"\b{re.escape(term)}\b", clean_text):
                gaps.append(term)
        return gaps

    @staticmethod
    def _strengths(features: dict) -> list:
        out = []
        if features["quantified_achievement_count"] >= 3:
            out.append(f"Uses quantified achievements ({features['quantified_achievement_count']} numeric/percentage results found)")
        if features["action_verb_count"] >= 5:
            out.append(f"Strong action-verb usage ({features['action_verb_count']} instances)")
        if features["has_linkedin"] or features["has_github"]:
            out.append("Includes professional profile links (LinkedIn/GitHub)")
        if features["section_coverage"] >= 0.75:
            out.append("Well-structured resume covering most standard sections")
        if features["bullet_count"] >= 6:
            out.append("Good use of bullet points for scannability")
        if not out:
            out.append("Resume text was successfully parsed and contains readable content")
        return out

    @staticmethod
    def _suggestions(features: dict, missing_sections: list, keyword_gaps: list) -> list:
        out = []
        for sec in missing_sections:
            out.append(f"Add a '{sec}' section")
        if features["quantified_achievement_count"] < 3:
            out.append("Quantify achievements with numbers, percentages, or metrics (e.g. 'improved performance by 20%')")
        if features["action_verb_count"] < 5:
            out.append("Start bullet points with strong action verbs (led, built, improved, launched...)")
        if not features["has_email"] or not features["has_phone"]:
            out.append("Make sure contact info (email and phone) is clearly visible")
        if keyword_gaps:
            out.append(f"Add relevant keywords for this role: {', '.join(keyword_gaps[:5])}")
        if not out:
            out.append("Resume looks solid structurally — focus on tailoring content per job description")
        return out

    def _summary(self, selection_chance, ats_score, mapped_category, predicted_category, target_role) -> str:
        role_label = target_role or predicted_category
        closeness = (
            f"reads closest to a {predicted_category} profile"
            if predicted_category != mapped_category
            else f"aligns with the {mapped_category} profile"
        )
        tone = "are solid" if selection_chance >= 60 else "need work"
        return (
            f"This resume {closeness} and scores {selection_chance}/100 for {role_label} roles, "
            f"with an ATS parseability score of {ats_score}/100. Structure and keyword coverage {tone}."
        )

    # ---------- public API ----------
    def analyze(self, resume_text: str, target_role: str = None) -> dict:
        features = extract_features(resume_text)
        clean = clean_for_tfidf(resume_text)

        vec = self.vectorizer.transform([clean])
        proba = self.clf.predict_proba(vec)[0]
        predicted_category = self.categories[proba.argmax()]

        mapped_category = self._map_role_to_category(target_role)
        if mapped_category and mapped_category in self.categories:
            role_fit_proba = proba[self.categories.index(mapped_category)]
        else:
            mapped_category = predicted_category
            role_fit_proba = proba.max()

        structural_score = self._structural_score(features)
        ats_score = round(0.7 * structural_score + 0.3 * min(100, features["word_count"] / 4))
        ats_score = int(max(0, min(100, ats_score)))

        selection_chance = round(0.6 * (role_fit_proba * 100) + 0.4 * structural_score)
        selection_chance = int(max(0, min(100, selection_chance)))

        missing_sections = [
            name.replace("_", " ").title()
            for name, found in features["sections_found"].items()
            if not found
        ]
        keyword_gaps = self._keyword_gaps(clean, mapped_category)
        strengths = self._strengths(features)
        suggestions = self._suggestions(features, missing_sections, keyword_gaps)
        summary = self._summary(selection_chance, ats_score, mapped_category, predicted_category, target_role)

        return {
            "selection_chance": selection_chance,
            "ats_score": ats_score,
            "summary": summary,
            "missing_sections": missing_sections[:6] if missing_sections else [],
            "keyword_gaps": keyword_gaps[:6],
            "strengths": strengths[:6],
            "suggestions": suggestions[:6],
        }
