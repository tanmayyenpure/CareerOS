"""
train_classifier.py
--------------------
Trains the resume-category classifier used by analyzer.py.

Pipeline: TF-IDF (word n-grams) -> Logistic Regression (multinomial,
class-balanced). This is a real, offline-trained scikit-learn model —
not an LLM call.

Run this once (and again whenever you get a bigger/better labeled
dataset) to regenerate the artifacts in models/:
    python train_classifier.py

Dataset: resume_dataset.csv (columns: Category, Resume). Swap in a
larger labeled set (e.g. a bigger Kaggle resume corpus) by pointing
DATA_PATH at it — the schema just needs Category + Resume columns.
"""

import json
import os
import sys

import joblib
import pandas as pd
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.model_selection import train_test_split
from sklearn.metrics import accuracy_score, classification_report

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from feature_engineering import clean_for_tfidf as clean_resume_text  # noqa: E402

DATA_PATH = os.path.join(HERE, "resume_dataset.csv")
MODELS_DIR = os.path.join(HERE, "models")

os.makedirs(MODELS_DIR, exist_ok=True)


def main():
    df = pd.read_csv(DATA_PATH)
    df = df.dropna(subset=["Category", "Resume"])
    df["clean_resume"] = df["Resume"].apply(clean_resume_text)

    # Drop categories with fewer than 2 samples so stratified split works
    counts = df["Category"].value_counts()
    df = df[df["Category"].isin(counts[counts >= 2].index)]

    X_train, X_test, y_train, y_test = train_test_split(
        df["clean_resume"], df["Category"],
        test_size=0.2, random_state=42, stratify=df["Category"]
    )

    vectorizer = TfidfVectorizer(
        stop_words="english",
        max_features=4000,
        ngram_range=(1, 2),
        sublinear_tf=True,
    )
    X_train_vec = vectorizer.fit_transform(X_train)
    X_test_vec = vectorizer.transform(X_test)

    clf = LogisticRegression(
        max_iter=2000, class_weight="balanced", C=2.0
    )
    clf.fit(X_train_vec, y_train)

    preds = clf.predict(X_test_vec)
    acc = accuracy_score(y_test, preds)
    report = classification_report(y_test, preds, zero_division=0)
    print(f"Held-out accuracy: {acc:.3f}\n")
    print(report)

    # Build a per-category "expected keyword" bank from TF-IDF weights,
    # trained on the FULL corpus (used later for keyword-gap detection).
    full_vec = vectorizer.transform(df["clean_resume"])
    terms = vectorizer.get_feature_names_out()
    category_keywords = {}
    for category in df["Category"].unique():
        idx = df.index[df["Category"] == category]
        rows = [df.index.get_loc(i) for i in idx]
        mean_tfidf = full_vec[rows].mean(axis=0).A1
        top_idx = mean_tfidf.argsort()[::-1][:25]
        category_keywords[category] = [
            terms[i] for i in top_idx if mean_tfidf[i] > 0
        ]

    joblib.dump(vectorizer, os.path.join(MODELS_DIR, "tfidf_vectorizer.joblib"))
    joblib.dump(clf, os.path.join(MODELS_DIR, "category_classifier.joblib"))
    with open(os.path.join(MODELS_DIR, "category_keywords.json"), "w") as f:
        json.dump(category_keywords, f, indent=2)
    with open(os.path.join(MODELS_DIR, "metrics.json"), "w") as f:
        json.dump({"held_out_accuracy": acc, "n_train": len(X_train), "n_test": len(X_test)}, f, indent=2)

    print(f"\nSaved model artifacts to {MODELS_DIR}")


if __name__ == "__main__":
    main()
