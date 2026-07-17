from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify
from flask_sqlalchemy import SQLAlchemy
from flask_mail import Mail, Message
from werkzeug.security import generate_password_hash, check_password_hash
import random
import os
import json
import time
import traceback
import zipfile
from datetime import datetime, timedelta

from openai import OpenAI
from google import genai
from google.genai import types
from werkzeug.utils import secure_filename
import requests

# ── RESUME TEXT EXTRACTION (used by /resume-analyzer/analyze) ──
RESUME_ALLOWED_EXTENSIONS = {'pdf', 'docx', 'txt'}


def extract_resume_text(filepath):
    """
    Pulls plain text out of a resume file so it can be handed to the AI.
    Supports .pdf, .docx and .txt. Returns (text, reason) where `text` is ""
    if nothing could be extracted and `reason` is a short machine-readable
    code the caller can use to give a specific error message instead of a
    generic one.

    reason values: None (success), "not_found", "pdf_no_text_layer",
    "pdf_error", "docx_error", "txt_error", "unsupported"
    """
    if not os.path.isfile(filepath):
        print(f"Resume text extraction: file not found at {filepath}")
        return "", "not_found"

    ext = filepath.rsplit('.', 1)[-1].lower() if '.' in filepath else ''

    if ext == 'pdf':
        try:
            import pdfplumber
            text_parts = []
            with pdfplumber.open(filepath) as pdf:
                for page in pdf.pages:
                    page_text = page.extract_text()
                    if page_text:
                        text_parts.append(page_text)
            text = "\n".join(text_parts).strip()
            if not text:
                # pdfplumber ran fine but found no embedded text — almost
                # always means the PDF is a scanned image / picture of text.
                print(f"Resume text extraction: no text layer in {filepath} "
                      f"(likely a scanned/image-only PDF)")
                return "", "pdf_no_text_layer"
            return text, None
        except Exception:
            print("Resume text extraction error (pdf):")
            traceback.print_exc()
            return "", "pdf_error"

    if ext == 'docx':
        try:
            import docx
            doc = docx.Document(filepath)
            text = "\n".join(p.text for p in doc.paragraphs).strip()
            if not text:
                return "", "pdf_no_text_layer"  # empty doc, same messaging
            return text, None
        except zipfile.BadZipFile:
            # .docx is really a zip archive under the hood. This almost
            # always means the file is actually an old binary .doc (or some
            # other format) that was just renamed to .docx, or it got
            # corrupted/truncated during upload.
            print(f"Resume text extraction: {filepath} is not a valid "
                  f"docx/zip container (likely a renamed .doc or corrupted upload)")
            return "", "docx_not_real_docx"
        except Exception:
            print("Resume text extraction error (docx):")
            traceback.print_exc()
            return "", "docx_error"

    if ext == 'txt':
        try:
            with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
                text = f.read().strip()
            if not text:
                return "", "pdf_no_text_layer"
            return text, None
        except Exception:
            print("Resume text extraction error (txt):")
            traceback.print_exc()
            return "", "txt_error"

    return "", "unsupported"


UPLOAD_FOLDER = os.path.join('static', 'uploads', 'resumes')
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
from config import Config
from youtube_helper import enrich_milestones_with_videos, enrich_with_video
from piston_helper import run_code, list_supported_languages, PistonError

print("CWD:", os.getcwd())
print("OPENROUTER_API_KEY found:", bool(Config.OPENROUTER_API_KEY))
print("GEMINI_API_KEY found:", bool(Config.GEMINI_API_KEY))

# ── CREATE APP FIRST ──
app = Flask(__name__)
app.config.from_object(Config)

db = SQLAlchemy(app)
mail = Mail(app)

# ── OPENROUTER (CARA CHAT) CONFIG ──
OPENROUTER_API_KEY = app.config['OPENROUTER_API_KEY']
client = OpenAI(
    base_url="https://openrouter.ai/api/v1",
    api_key=OPENROUTER_API_KEY,
)

# ── GEMINI (ROADMAP GENERATION) CONFIG ──
GEMINI_API_KEY = app.config['GEMINI_API_KEY']
gemini_client = genai.Client(api_key=GEMINI_API_KEY)

# CareerOS's published terms (see faq.html / pricing.html):
#   Free plan  -> 10 AI messages per day, forever
#   Pro plan   -> unlimited AI coaching
FREE_DAILY_CHAT_LIMIT = 10
DOMAIN_LABELS = {
    "engineering_tech": "Engineering & Technology",
    "medical_healthcare": "Medical & Healthcare",
    "commerce_finance": "Commerce & Finance",
    "law": "Law",
    "design_creative": "Design & Creative Arts",
    "government_public": "Government & Public Services",
    "agriculture": "Agriculture"
}
CODING_CATEGORIES = {
    "arrays_strings":          "Arrays & Strings",
    "linked_lists":            "Linked Lists",
    "recursion_backtracking":  "Recursion & Backtracking",
    "trees_graphs":            "Trees & Graphs",
    "dynamic_programming":     "Dynamic Programming",
    "sorting_searching":       "Sorting & Searching",
    "sql_databases":           "Databases (SQL)",
}
CARA_SYSTEM_PROMPT = (
    "You are Cara, the AI assistant inside CareerOS. You can answer any question the user "
    "asks — general knowledge, casual chat, how-to questions, career advice, whatever they "
    "bring up — not just career topics. Be helpful, direct, and conversational. When a "
    "question does relate to careers, jobs, resumes, interviews, or skills, lean on your "
    "knowledge of the Indian job market (companies, salary benchmarks, hiring norms) to make "
    "the answer more useful. Keep replies concise (roughly under 150 words) unless the user "
    "clearly wants more detail. Never claim to take actions outside the chat — you only answer. "
    "Reply in plain conversational text only — no markdown formatting like asterisks, bullet "
    "points, or bold text, since the chat UI displays raw text."
)

# ── MODELS ──
class User(db.Model):
    __tablename__ = 'users'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120))
    email = db.Column(db.String(120), unique=True)
    password_hash = db.Column(db.String(255))
    is_verified = db.Column(db.Boolean, default=False)
    profile_complete = db.Column(db.Boolean, default=False)
    bio = db.Column(db.Text)
    target_role = db.Column(db.String(120))
    domain = db.Column(db.String(100))
    is_pro = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    chat_count_today = db.Column(db.Integer, default=0)
    chat_count_date = db.Column(db.Date, default=None)
    pro_expires_at = db.Column(db.DateTime)

    # profile fields
    phone = db.Column(db.String(30))
    location = db.Column(db.String(120))
    linkedin = db.Column(db.String(255))
    github = db.Column(db.String(255))
    resume_filename = db.Column(db.String(255))
    resume_score = db.Column(db.Integer)

    skills = db.relationship('Skill', backref='user', lazy=True)
    education = db.relationship('Education', backref='user', lazy=True)
    experience = db.relationship('Experience', backref='user', lazy=True)

class Skill(db.Model):
    __tablename__ = 'skills'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    name = db.Column(db.String(120))
    level = db.Column(db.String(20))

class Education(db.Model):
    __tablename__ = 'education'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    school = db.Column(db.String(255))
    degree = db.Column(db.String(255))
    years = db.Column(db.String(50))

class Experience(db.Model):
    __tablename__ = 'experience'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    title = db.Column(db.String(255))
    company = db.Column(db.String(255))
    dates = db.Column(db.String(50))


class ResumeAnalysis(db.Model):
    __tablename__ = 'resume_analysis'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    selection_chance = db.Column(db.Integer)
    ats_score = db.Column(db.Integer)
    summary = db.Column(db.Text)
    missing_sections = db.Column(db.Text)   # JSON-encoded list
    keyword_gaps = db.Column(db.Text)       # JSON-encoded list
    strengths = db.Column(db.Text)          # JSON-encoded list
    suggestions = db.Column(db.Text)        # JSON-encoded list
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def as_dict(self):
        return {
            "selection_chance": self.selection_chance,
            "ats_score": self.ats_score,
            "summary": self.summary,
            "missing_sections": json.loads(self.missing_sections or "[]"),
            "keyword_gaps": json.loads(self.keyword_gaps or "[]"),
            "strengths": json.loads(self.strengths or "[]"),
            "suggestions": json.loads(self.suggestions or "[]"),
            "created_at": self.created_at.strftime("%d %b %Y") if self.created_at else None,
        }


class OTPVerification(db.Model):
    __tablename__ = 'otp_verification'
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(120))
    otp_code = db.Column(db.String(6))
    expires_at = db.Column(db.DateTime)
    created_at = db.Column(db.DateTime, default=db.func.now())

class AssessmentQuestion(db.Model):
    __tablename__ = "assessment_questions"
    id = db.Column(db.Integer, primary_key=True)
    domain = db.Column(db.String(100))
    question = db.Column(db.Text)
    option_a = db.Column(db.String(255))
    option_b = db.Column(db.String(255))
    option_c = db.Column(db.String(255))
    option_d = db.Column(db.String(255))
    correct_answer = db.Column(db.Integer)

class AssessmentResult(db.Model):
    __tablename__ = "assessment_results"
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer)
    domain = db.Column(db.String(100))
    score = db.Column(db.Integer)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class Roadmap(db.Model):
    __tablename__ = "roadmaps"
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer)
    title = db.Column(db.String(255))
    target_role = db.Column(db.String(120))
    total_weeks = db.Column(db.Integer)
    progress_percent = db.Column(db.Integer, default=0)
    status = db.Column(db.String(50), default="active")
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class RoadmapMilestone(db.Model):
    __tablename__ = "roadmap_milestones"
    id = db.Column(db.Integer, primary_key=True)
    roadmap_id = db.Column(db.Integer)
    week = db.Column(db.Integer)
    title = db.Column(db.String(255))
    task = db.Column(db.Text)
    resource_url = db.Column(db.String(500))
    resource_title = db.Column(db.String(255))
    resource_channel = db.Column(db.String(255))
    resource_video_id = db.Column(db.String(50))
    resource_duration = db.Column(db.String(20))
    resource_views = db.Column(db.String(30))
    resource_thumbnail = db.Column(db.String(500))
    estimated_hours = db.Column(db.Integer)
    status = db.Column(db.String(50), default="pending")
    milestone_type = db.Column(db.String(20), default="new")  # "revision" or "new"

    # ── video-gated quiz tracking ──
    video_watched = db.Column(db.Boolean, default=False)   # set once the embedded player fires ENDED
    quiz_score = db.Column(db.Integer)                       # marks scored on the most recent attempt
    quiz_total = db.Column(db.Integer)                       # total marks the quiz was out of (10-15)
    quiz_attempts = db.Column(db.Integer, default=0)
    quiz_passed = db.Column(db.Boolean, default=False)       # True once they've cleared the pass threshold


class MilestoneQuiz(db.Model):
    """
    One quiz per milestone, generated on-demand the first time the user
    finishes that milestone's video. questions_json holds the full
    question set INCLUDING correct answers — this table is never sent to
    the client as-is; /api/milestones/<id>/quiz strips correct_index out
    before returning it, so answers stay server-side.
    """
    __tablename__ = "milestone_quizzes"
    id = db.Column(db.Integer, primary_key=True)
    milestone_id = db.Column(db.Integer, db.ForeignKey('roadmap_milestones.id'), unique=True)
    questions_json = db.Column(db.Text)  # JSON: [{"id","question","options","correct_index","marks"}, ...]
    total_marks = db.Column(db.Integer)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


# Passing threshold for milestone quizzes: score / total_marks >= this
# fraction auto-marks the milestone completed.
QUIZ_PASS_THRESHOLD = 0.6


class MilestoneNotes(db.Model):
    """
    Short written study notes + a Q&A set for one milestone's topic,
    generated on demand. These exist to give learners something more
    substantial than a single video they can finish in a day — a quick
    read-back of the core concepts plus a handful of Q&A pairs to check
    their own understanding (separate from the graded MilestoneQuiz).
    """
    __tablename__ = "milestone_notes"
    id = db.Column(db.Integer, primary_key=True)
    milestone_id = db.Column(db.Integer, db.ForeignKey('roadmap_milestones.id'), unique=True)
    notes_text = db.Column(db.Text)   # short markdown-ish study notes
    qa_json = db.Column(db.Text)      # JSON: [{"question": str, "answer": str}, ...]
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class LearningHubSubjectSet(db.Model):
    """
    Cached AI-generated subject list for one domain. Domain here is the
    human-readable label (DOMAIN_LABELS value, e.g. "Engineering &
    Technology"), not the short key, since that's what the frontend
    already sends. One row per domain — regenerated only if you pass
    ?regenerate=1.
    """
    __tablename__ = "learning_hub_subject_sets"
    id = db.Column(db.Integer, primary_key=True)
    domain = db.Column(db.String(120), unique=True, nullable=False)
    subjects_json = db.Column(db.Text)  # JSON: [{"name","description","tags":[...]}, ...]
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class LearningHubMaterial(db.Model):
    """
    Cached AI-generated study material for one (domain, subject) pair.
    Same caching rationale as MilestoneQuiz/MilestoneNotes: avoid
    re-spending Gemini quota every time the same subject gets clicked.
    """
    __tablename__ = "learning_hub_material"
    id = db.Column(db.Integer, primary_key=True)
    domain = db.Column(db.String(120), nullable=False)
    subject = db.Column(db.String(200), nullable=False)
    overview = db.Column(db.Text)
    topics_json = db.Column(db.Text)     # JSON: [{"title","explanation"}, ...]
    resources_json = db.Column(db.Text)  # JSON: [{"label","url"}, ...]
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    __table_args__ = (
        db.UniqueConstraint('domain', 'subject', name='uq_hub_domain_subject'),
    )


class CodingProblemSet(db.Model):
    """
    Cached AI-generated problem list for one category. Same caching
    rationale as LearningHubSubjectSet — one row per category, only
    regenerated if you pass ?regenerate=1.
    """
    __tablename__ = "coding_problem_sets"
    id = db.Column(db.Integer, primary_key=True)
    category = db.Column(db.String(120), unique=True, nullable=False)
    problems_json = db.Column(db.Text)  # JSON: [{"title","difficulty","tags":[...],"one_liner"}, ...]
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class CodingProblem(db.Model):
    """
    Cached AI-generated full problem detail for one (category, title)
    pair — statement, constraints, examples, hidden test cases, and
    starter code per language. test_cases_json is never sent to the
    frontend (see _get_coding_test_cases) so it stays server-side only,
    same spirit as a real judge hiding its grading cases.
    """
    __tablename__ = "coding_problems"
    id = db.Column(db.Integer, primary_key=True)
    category = db.Column(db.String(120), nullable=False)
    title = db.Column(db.String(200), nullable=False)
    difficulty = db.Column(db.String(20))
    statement = db.Column(db.Text)
    constraints_json = db.Column(db.Text)   # JSON: ["1 <= n <= 1e5", ...]
    examples_json = db.Column(db.Text)      # JSON: [{"input","output","explanation"}, ...]
    test_cases_json = db.Column(db.Text)    # JSON: [{"input","output"}, ...] — server-side only
    starter_code_json = db.Column(db.Text)  # JSON: {"python": "...", "javascript": "...", ...}
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    __table_args__ = (
        db.UniqueConstraint('category', 'title', name='uq_coding_category_title'),
    )


class CodingSubmission(db.Model):
    """
    One Submit attempt (not every Run — Run against samples is cheap/free
    and doesn't get saved). Powers the "Problems Solved" / "Submissions
    Made" stats and the solved-checkmark on the problem grid.
    """
    __tablename__ = "coding_submissions"
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    category = db.Column(db.String(120), nullable=False)
    problem_title = db.Column(db.String(200), nullable=False)
    language = db.Column(db.String(30), nullable=False)
    code = db.Column(db.Text)
    verdict = db.Column(db.String(30))  # Accepted / Wrong Answer / Runtime Error / Compile Error
    passed_count = db.Column(db.Integer, default=0)
    total_count = db.Column(db.Integer, default=0)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class Job(db.Model):
    __tablename__ = 'jobs'
    id = db.Column(db.Integer, primary_key=True)
    company_name = db.Column(db.String(100), nullable=False)
    job_title = db.Column(db.String(100), nullable=False)
    location = db.Column(db.String(100), nullable=False)
    job_type = db.Column(db.String(50))  # Remote/Hybrid/Onsite
    experience = db.Column(db.String(50))
    salary = db.Column(db.String(50))
    description = db.Column(db.Text)
    skills_required = db.Column(db.Text)  # comma-separated list of skills
    company_logo = db.Column(db.String(255))
    domain = db.Column(db.String(100))
    posted_date = db.Column(db.DateTime, default=datetime.utcnow)

    def to_dict(self):
        return {
            "id": self.id,
            "company_name": self.company_name,
            "job_title": self.job_title,
            "location": self.location,
            "job_type": self.job_type,
            "experience": self.experience,
            "salary": self.salary,
            "description": self.description,
            "skills_required": [s.strip() for s in (self.skills_required or "").split(",") if s.strip()],
            "company_logo": self.company_logo,
            "domain": self.domain,
            "posted_date": self.posted_date.strftime('%Y-%m-%d') if self.posted_date else None
        }


class SavedJob(db.Model):
    __tablename__ = 'saved_jobs'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    job_id = db.Column(db.Integer, db.ForeignKey('jobs.id'), nullable=False)
    saved_date = db.Column(db.DateTime, default=datetime.utcnow)

    job = db.relationship('Job', backref='saved_by_users')


class Application(db.Model):
    __tablename__ = 'applications'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    job_id = db.Column(db.Integer, db.ForeignKey('jobs.id'), nullable=False)
    applied_date = db.Column(db.DateTime, default=datetime.utcnow)
    status = db.Column(db.String(50), default="Applied")  # Applied, Screening, Interview, Offer, Rejected, etc.

    job = db.relationship('Job', backref='applications')


class Interview(db.Model):
    __tablename__ = 'interviews'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    application_id = db.Column(db.Integer, db.ForeignKey('applications.id'))
    company_name = db.Column(db.String(100))
    job_title = db.Column(db.String(100))
    interview_date = db.Column(db.DateTime, nullable=False)
    meeting_link = db.Column(db.String(255))
    status = db.Column(db.String(50), default="Scheduled")  # Scheduled, Completed, Cancelled
    round_name = db.Column(db.String(100))  # e.g., "System Design", "HR Discussion"

    application = db.relationship('Application', backref='interviews')


def calculate_ai_match(user_id):
    """
    Computes a match percentage by finding overlap between user's skills and all available jobs.
    Returns an average percentage (between 0 and 100).
    """
    user = User.query.get(user_id)
    if not user:
        return 0
    
    user_skills = {s.name.lower().strip() for s in user.skills} if user.skills else set()
    if not user_skills:
        return 75  # Return a base/default match if user hasn't added skills yet
    
    all_jobs = Job.query.all()
    if not all_jobs:
        return 75
        
    match_percentages = []
    for job in all_jobs:
        job_skills = {s.lower().strip() for s in (job.skills_required or "").split(",") if s.strip()}
        if not job_skills:
            match_percentages.append(100)
            continue
        intersection = user_skills.intersection(job_skills)
        match_percentages.append(round((len(intersection) / len(job_skills)) * 100) if len(job_skills) > 0 else 75)
        
    return round(sum(match_percentages) / len(match_percentages)) if match_percentages else 75



def generate_notes_for_milestone(milestone):
    """
    Calls Gemini to write compact, STRUCTURED study notes plus a Q&A set
    for a milestone's topic. Returns (sections, qa_list) where sections is
    a list of {"heading": str, "points": [str, ...]} — structured rather
    than one free-text blob, so the frontend can render real headings and
    bullet lists instead of a wall of text.
    Raises RateLimitError / json.JSONDecodeError the same way the quiz
    generator does — callers decide how to surface that.
    """
    prompt = f"""
You are writing supplementary study notes for a learner whose roadmap
milestone is a single tutorial video that only takes about a day to watch.
The notes should give them something more substantial to actually retain,
independent of rewatching the video.

Milestone title: {milestone.title}
What it's supposed to teach: {milestone.task}
Related video: "{milestone.resource_title or milestone.title}"

Write:
1. Study notes broken into 2-5 short SECTIONS (e.g. distinct sub-topics or
   concepts within this milestone). Each section has a short heading and
   3-6 bullet points. Each bullet point must be ONE self-contained,
   skimmable sentence or short phrase — do NOT write run-on paragraphs
   and do NOT put multiple ideas in one bullet.
2. A Q&A set of 5-7 question/answer pairs that check real understanding
   of the topic (not trivia about the video). Answers should be direct,
   a few sentences each, and also written as plain sentences (no markdown).

Return ONLY valid JSON matching exactly this schema:
{{
  "sections": [
    {{
      "heading": "string, short (2-5 words)",
      "points": ["one self-contained bullet point", "another bullet point"]
    }}
  ],
  "qa": [
    {{"question": "string", "answer": "string"}}
  ]
}}
"""
    data = _call_gemini_json(prompt)

    sections = []
    for s in data.get("sections", []):
        heading = (s.get("heading") or "").strip()
        points = [p.strip() for p in s.get("points", []) if isinstance(p, str) and p.strip()]
        if heading and points:
            sections.append({"heading": heading, "points": points})

    qa_list = [
        {"question": (qa.get("question") or "").strip(), "answer": (qa.get("answer") or "").strip()}
        for qa in data.get("qa", [])
        if qa.get("question") and qa.get("answer")
    ]
    if not sections or not qa_list:
        raise ValueError("Gemini returned incomplete notes/Q&A for this milestone.")
    return sections, qa_list


def _get_or_create_notes(milestone, regenerate=False):
    existing = MilestoneNotes.query.filter_by(milestone_id=milestone.id).first()
    if existing and not regenerate:
        return existing

    sections, qa_list = generate_notes_for_milestone(milestone)
    if existing:
        existing.notes_text = json.dumps(sections)
        existing.qa_json = json.dumps(qa_list)
        existing.created_at = datetime.utcnow()
    else:
        existing = MilestoneNotes(
            milestone_id=milestone.id,
            notes_text=json.dumps(sections),
            qa_json=json.dumps(qa_list),
        )
        db.session.add(existing)
    db.session.commit()
    return existing


def generate_quiz_for_milestone(milestone):
    """
    Generates a short (10-15 mark) multiple-choice quiz testing whether
    the learner actually absorbed this milestone's video, using Gemini.
    Returns a list of question dicts:
        [{"id": "q1", "question": str, "options": [str,str,str,str],
          "correct_index": int, "marks": int}, ...]
    and the total marks (always 10-15). Raises RateLimitError /
    json.JSONDecodeError the same way the roadmap generator does — the
    caller decides how to surface that.
    """
    prompt = f"""
You are writing a short comprehension check for someone who just watched a
tutorial video on this specific topic:

Milestone title: {milestone.title}
What it's supposed to teach: {milestone.task}
Video watched: "{milestone.resource_title or milestone.title}"

Write 4-5 multiple-choice questions that test whether they understood the
CONCEPT (not obscure trivia about the video itself). Each question has
exactly 4 options and exactly one correct option. Distribute "marks" per
question so the marks add up to a total between 10 and 15 (e.g. 5
questions worth 3 marks each = 15, or 4 questions worth 2-3 marks = 10-11).

Return ONLY valid JSON matching exactly this schema:
{{
  "questions": [
    {{
      "question": "string",
      "options": ["string", "string", "string", "string"],
      "correct_index": 0,
      "marks": number
    }}
  ]
}}
"""
    data = _call_gemini_json(prompt)
    raw_questions = data.get("questions", [])
    if not raw_questions:
        raise ValueError("Gemini returned no quiz questions for this milestone.")

    questions = []
    total_marks = 0
    for i, q in enumerate(raw_questions):
        marks = int(q.get("marks", 2))
        total_marks += marks
        questions.append({
            "id": f"q{i+1}",
            "question": q.get("question", "").strip(),
            "options": q.get("options", [])[:4],
            "correct_index": int(q.get("correct_index", 0)),
            "marks": marks,
        })
    return questions, total_marks


def _get_or_create_quiz(milestone, regenerate=False):
    existing = MilestoneQuiz.query.filter_by(milestone_id=milestone.id).first()
    if existing and not regenerate:
        return existing

    questions, total_marks = generate_quiz_for_milestone(milestone)
    if existing:
        existing.questions_json = json.dumps(questions)
        existing.total_marks = total_marks
        existing.created_at = datetime.utcnow()
    else:
        existing = MilestoneQuiz(
            milestone_id=milestone.id,
            questions_json=json.dumps(questions),
            total_marks=total_marks,
        )
        db.session.add(existing)
    db.session.commit()
    return existing


def _get_or_create_hub_subjects(domain, regenerate=False):
    existing = LearningHubSubjectSet.query.filter_by(domain=domain).first()
    if existing and not regenerate:
        return json.loads(existing.subjects_json)

    prompt = f'''You are helping build a study syllabus browser for Indian
students and job-seekers.

Domain: "{domain}"

Return 6 to 8 core subjects/specializations that fall under this domain in
the Indian education/career context. For each subject give a short
1-sentence description and 2-3 short tag words (e.g. difficulty level,
category).

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
'''
    data = _call_gemini_json(prompt)
    subjects = data.get("subjects", [])
    if not isinstance(subjects, list) or not subjects:
        raise ValueError("Gemini returned no subjects")

    if existing:
        existing.subjects_json = json.dumps(subjects)
        existing.created_at = datetime.utcnow()
    else:
        existing = LearningHubSubjectSet(domain=domain, subjects_json=json.dumps(subjects))
        db.session.add(existing)
    db.session.commit()
    return subjects


def _get_or_create_hub_material(domain, subject, regenerate=False):
    existing = LearningHubMaterial.query.filter_by(domain=domain, subject=subject).first()
    if existing and not regenerate:
        return {
            "overview": existing.overview,
            "topics": json.loads(existing.topics_json or "[]"),
            "resources": json.loads(existing.resources_json or "[]"),
        }

    prompt = f'''You are building a study guide for an Indian student
learning "{subject}" within the "{domain}" domain.

Return:
1. A 2-3 sentence overview of what this subject covers and why it matters.
2. 5 to 7 key topics within this subject. For each topic give:
   - "title": short topic name
   - "explanation": 1-2 sentence plain-English explanation a beginner could follow
   - "notes": 2-4 short bullet points with a bit more depth than the
     explanation -- specific facts, steps, or things worth remembering
   - "search_keywords": 2-4 words that would find a real, relevant
     tutorial video on YouTube for this specific topic
3. 3 to 5 real, generally well-known learning resources (official docs,
   well-known free course platforms, NPTEL/SWAYAM for Indian academic
   subjects, etc.) as a label and URL. Only include resource types that
   are safe to link -- prefer a platform's homepage/search page over a
   guessed deep link if you are not confident a specific URL exists.

Respond with ONLY raw JSON, no markdown fences, no commentary, in exactly
this shape:

{{
  "overview": "...",
  "topics": [
    {{
      "title": "...",
      "explanation": "...",
      "notes": ["...", "..."],
      "search_keywords": ["...", "..."]
    }}
  ],
  "resources": [
    {{ "label": "...", "url": "..." }}
  ]
}}
'''
    data = _call_gemini_json(prompt)
    overview = data.get("overview", "")
    topics = data.get("topics", [])
    resources = data.get("resources", [])

    for topic in topics:
        try:
            enrich_with_video(topic)
        except Exception as e:
            print(f"Learning Hub topic video lookup failed for {topic.get('title')!r}: {e}")

    if existing:
        existing.overview = overview
        existing.topics_json = json.dumps(topics)
        existing.resources_json = json.dumps(resources)
        existing.created_at = datetime.utcnow()
    else:
        existing = LearningHubMaterial(
            domain=domain, subject=subject,
            overview=overview,
            topics_json=json.dumps(topics),
            resources_json=json.dumps(resources),
        )
        db.session.add(existing)
    db.session.commit()
    return {"overview": overview, "topics": topics, "resources": resources}


def _get_or_create_coding_problems(category, regenerate=False):
    existing = CodingProblemSet.query.filter_by(category=category).first()
    if existing and not regenerate:
        return json.loads(existing.problems_json)

    prompt = f'''You are building a curated coding-practice problem list for
Indian students and job-seekers preparing for technical interviews.

Category: "{category}"

Return 6 to 8 problems in this category, similar in spirit to a
LeetCode/HackerRank problem list, ranging across difficulty levels. For
each problem give:
- "title": a short, specific problem title (e.g. "Two Sum")
- "difficulty": one of "Easy", "Medium", "Hard"
- "tags": 2-3 short tag words (e.g. "Hash Map", "Two Pointers")
- "one_liner": one sentence describing what the problem asks for

Respond with ONLY raw JSON, no markdown fences, no commentary, in exactly
this shape:

{{
  "problems": [
    {{
      "title": "Two Sum",
      "difficulty": "Easy",
      "tags": ["Arrays", "Hash Map"],
      "one_liner": "Find two numbers in an array that add up to a target."
    }}
  ]
}}
'''
    data = _call_gemini_json(prompt)
    problems = data.get("problems", [])
    if not isinstance(problems, list) or not problems:
        raise ValueError("Gemini returned no problems")

    if existing:
        existing.problems_json = json.dumps(problems)
        existing.created_at = datetime.utcnow()
    else:
        existing = CodingProblemSet(category=category, problems_json=json.dumps(problems))
        db.session.add(existing)
    db.session.commit()
    return problems


def _get_or_create_coding_problem_detail(category, title, regenerate=False):
    existing = CodingProblem.query.filter_by(category=category, title=title).first()
    if existing and not regenerate:
        return {
            "title": existing.title,
            "difficulty": existing.difficulty,
            "statement": existing.statement,
            "constraints": json.loads(existing.constraints_json or "[]"),
            "examples": json.loads(existing.examples_json or "[]"),
            "starter_code": json.loads(existing.starter_code_json or "{}"),
        }

    prompt = f'''You are creating one coding-practice problem for an online
judge aimed at Indian students preparing for technical interviews.

Category: "{category}"
Problem title: "{title}"

Design this as a stdin/stdout problem (like Codeforces/HackerRank) — the
solution reads input from standard input and prints output to standard
output. Keep the input/output format simple and completely unambiguous,
since it will be auto-graded by exact string match on stdout.

Return:
1. "statement": 2-4 plain-text paragraphs (no markdown headers) explaining
   the problem clearly, including the exact input/output format.
2. "constraints": 3-5 short strings describing input limits (e.g.
   "1 <= n <= 10^5").
3. "examples": 2-3 sample input/output pairs to SHOW the user, each with
   "input" (exact stdin text), "output" (exact expected stdout, no extra
   text), and "explanation" (1 sentence).
4. "test_cases": 6-10 input/output pairs used to auto-grade submissions
   (can reuse the examples plus more, covering edge cases). Same
   "input"/"output" shape as examples, no explanation needed. Output must
   be the exact stdout text a correct solution would print (trailing
   whitespace is trimmed before comparison, but formatting inside the
   output must be exact).
5. "starter_code": boilerplate for EXACTLY these 5 languages — python,
   javascript, cpp, java, c — that reads input in the exact format you
   defined above and has a clear TODO comment where the user writes their
   solution, but does NOT solve the problem. For java, the public class
   MUST be named "Main" (the file is Main.java). Keep each boilerplate
   short and idiomatic for that language's standard stdin reading.

Respond with ONLY raw JSON, no markdown fences, no commentary, in exactly
this shape:

{{
  "statement": "...",
  "constraints": ["..."],
  "examples": [{{"input": "...", "output": "...", "explanation": "..."}}],
  "test_cases": [{{"input": "...", "output": "..."}}],
  "starter_code": {{
    "python": "...", "javascript": "...", "cpp": "...", "java": "...", "c": "..."
  }}
}}
'''
    data = _call_gemini_json(prompt)
    statement = data.get("statement", "")
    constraints = data.get("constraints", [])
    examples = data.get("examples", [])
    test_cases = data.get("test_cases", [])
    starter_code = data.get("starter_code", {})

    if not test_cases:
        raise ValueError("Gemini returned no test cases")

    # Difficulty lives on the cached problem *list*, not this call — pull
    # it from there so the detail row matches what the grid already showed.
    difficulty = "Medium"
    problem_set = CodingProblemSet.query.filter_by(category=category).first()
    if problem_set:
        for p in json.loads(problem_set.problems_json):
            if p.get("title") == title:
                difficulty = p.get("difficulty", "Medium")
                break

    if existing:
        existing.difficulty = difficulty
        existing.statement = statement
        existing.constraints_json = json.dumps(constraints)
        existing.examples_json = json.dumps(examples)
        existing.test_cases_json = json.dumps(test_cases)
        existing.starter_code_json = json.dumps(starter_code)
        existing.created_at = datetime.utcnow()
    else:
        existing = CodingProblem(
            category=category, title=title, difficulty=difficulty,
            statement=statement,
            constraints_json=json.dumps(constraints),
            examples_json=json.dumps(examples),
            test_cases_json=json.dumps(test_cases),
            starter_code_json=json.dumps(starter_code),
        )
        db.session.add(existing)
    db.session.commit()

    return {
        "title": title, "difficulty": difficulty, "statement": statement,
        "constraints": constraints, "examples": examples, "starter_code": starter_code,
    }


def _get_coding_test_cases(category, title):
    """Server-side only — never returned directly to the frontend."""
    row = CodingProblem.query.filter_by(category=category, title=title).first()
    if not row or not row.test_cases_json:
        return []
    return json.loads(row.test_cases_json)


# ── HELPER FUNCTION: OTP ──
def generate_and_send_otp(email):
    otp_code = str(random.randint(100000, 999999))
    expires_at = datetime.utcnow() + timedelta(minutes=10)

    OTPVerification.query.filter_by(email=email).delete()

    otp_entry = OTPVerification(email=email, otp_code=otp_code, expires_at=expires_at)
    db.session.add(otp_entry)
    db.session.commit()

    msg = Message('Your CareerOS verification code',
                  sender=app.config['MAIL_USERNAME'],
                  recipients=[email])
    msg.body = f'Your OTP code is: {otp_code}\nThis code expires in 10 minutes.'
    mail.send(msg)


# ── HELPER FUNCTION: GEMINI ROADMAP / PATHFINDER GENERATION ──
class RateLimitError(Exception):
    pass


def _call_gemini_json(prompt, model="gemini-2.5-flash"):
    """
    Shared low-level Gemini caller used by both roadmap and pathfinder
    generation. Forces JSON output, retries with backoff on rate limits
    or transient errors.

    Raises:
        RateLimitError: if Gemini is rate-limited after 3 attempts.
        json.JSONDecodeError: if Gemini's response isn't valid JSON.
    """
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
            print("Gemini API error:", repr(e))
            if "RESOURCE_EXHAUSTED" in str(e) or "429" in str(e):
                if attempt < 2:
                    time.sleep(2 ** attempt)
                    continue
                raise RateLimitError("Gemini rate limit hit after retries")
            if attempt < 2:
                time.sleep(1)
                continue
            raise


def _normalize_milestones(data):
    """
    Gemini sometimes nests milestones by phase instead of returning one flat
    top-level array (e.g. {"revision": [...], "new": [...]} or
    {"phases": [{"milestones": [...]}, ...]}) even when told not to. Rather
    than silently saving zero milestones when that happens, detect and
    flatten the common alternate shapes here.
    """
    milestones = data.get("milestones")
    if isinstance(milestones, list) and milestones:
        return milestones

    # Alternate shape: separate "revision" / "new" arrays at the top level.
    flattened = []
    for key in ("revision", "revision_milestones", "new", "new_milestones"):
        value = data.get(key)
        if isinstance(value, list):
            m_type = "revision" if "revision" in key else "new"
            for m in value:
                m.setdefault("milestone_type", m_type)
            flattened.extend(value)
    if flattened:
        return flattened

    # Alternate shape: a "phases" array, each with its own "milestones".
    phases = data.get("phases")
    if isinstance(phases, list):
        for phase in phases:
            phase_milestones = phase.get("milestones") if isinstance(phase, dict) else None
            if isinstance(phase_milestones, list):
                m_type = "revision" if "revision" in str(phase.get("type", phase.get("name", ""))).lower() else "new"
                for m in phase_milestones:
                    m.setdefault("milestone_type", m_type)
                flattened.extend(phase_milestones)
    return flattened


def generate_roadmap_with_ai(target_role, domain, prior_knowledge="", weekly_hours=10, experience_level="beginner"):
    """
    Calls Gemini to generate a personalized roadmap, then replaces the
    AI's guessed resource links with REAL YouTube videos found via the
    YouTube Data API (see youtube_helper.py). This avoids the classic
    LLM failure mode of confidently returning dead/hallucinated URLs.

    If the user reports prior knowledge, the roadmap opens with a short
    "revision" phase covering exactly what they said they already know
    (not re-taught from scratch, just refreshed), followed by a "new"
    phase covering everything else needed to reach target_role. If the
    user has no prior knowledge, the whole roadmap is "new".

    Raises ValueError if the AI (even after one retry) never returns any
    usable milestones, instead of silently succeeding with an empty roadmap.
    """
    prior_knowledge = (prior_knowledge or "").strip()
    prior_knowledge_line = prior_knowledge if prior_knowledge else "Nothing yet — complete beginner, starting from scratch."

    prompt = f"""
You are a career roadmap generator. Create a personalized learning roadmap.

Target Role: {target_role}
Domain: {domain}
Available Time: {weekly_hours} hours/week
Experience Level: {experience_level}
What the learner says they've already learned or worked on: "{prior_knowledge_line}"

The roadmap covers two things, in order:
1. A short "revision" recap — ONLY if the learner listed real prior knowledge
   above. Skip it completely (contribute zero items) if they said they're
   starting fresh / know nothing. If included, keep it to 1-3 items that
   quickly refresh exactly what they said they already know — do not
   re-teach it from zero, and do not add things they didn't mention.
2. The forward-looking "new" path — everything else the learner still needs
   to learn to reach {target_role}, building on top of the revision recap.

CRITICAL OUTPUT RULE: every single milestone from BOTH parts above — revision
and new — must be items of ONE single flat top-level JSON array called
"milestones". Do NOT create separate arrays for revision vs new, do NOT nest
milestones under phase objects. Flat array only. Use the "milestone_type"
field inside each milestone object to mark which part it belongs to.

Return ONLY valid JSON, matching exactly this schema (this is illustrative —
use real content, but copy this exact structure):
{{
  "title": "string",
  "target_role": "string",
  "total_weeks": number,
  "milestones": [
    {{
      "week": 1,
      "milestone_type": "revision",
      "title": "string",
      "task": "string",
      "search_keywords": ["2-4 words to find a real tutorial video for this milestone"],
      "estimated_hours": number
    }},
    {{
      "week": 2,
      "milestone_type": "new",
      "title": "string",
      "task": "string",
      "search_keywords": ["2-4 words"],
      "estimated_hours": number
    }}
  ]
}}

Number "week" continuously starting at 1 across the whole flat array.
Generate 6-10 "new" milestones, plus 0-3 "revision" milestones depending on
what the learner already knows — the "milestones" array must never be empty.
Do NOT invent URLs — only provide search_keywords, those will be used to
look up a real video separately.
"""
    data = _call_gemini_json(prompt)
    milestones = _normalize_milestones(data)

    if not milestones:
        # One retry with a blunter, simpler prompt before giving up — some
        # models occasionally ignore structure instructions on the first pass.
        print("Gemini returned zero usable milestones on first attempt, retrying with a stricter prompt...")
        retry_prompt = prompt + (
            "\n\nYour previous response did not include a valid non-empty "
            "\"milestones\" flat array. This time, you MUST return at least "
            "6 items directly inside \"milestones\" at the top level."
        )
        data = _call_gemini_json(retry_prompt)
        milestones = _normalize_milestones(data)

    if not milestones:
        raise ValueError("Gemini returned no usable milestones for this roadmap after retrying.")

    data["milestones"] = enrich_milestones_with_videos(milestones)
    return data


def generate_pathfinder_with_ai(current_role, target_role):
    """
    Calls Gemini to generate a dependency-mapped skill tree for a role
    transition, matching the schema skill_pathfinder.js expects
    (stages / nodes / connections), then attaches one real YouTube video
    per node the same way generate_roadmap_with_ai does for milestones.
    """
    prompt = f"""
You are a career skill-tree generator. A user currently works as a
{current_role} and wants to transition to {target_role}.

Design a dependency-mapped skill tree with exactly 4 stages (progressive
phases of the transition) and 5-8 skill nodes total spread across those
stages. Each node depends on 0-2 earlier nodes, referenced by id.

Return ONLY valid JSON matching this exact schema:
{{
  "title": "string, e.g. '{current_role} to {target_role}'",
  "stages": [
    {{"id": "stage1", "title": "1. Phase name"}}
  ],
  "nodes": [
    {{
      "id": "short_snake_case_id",
      "stage": "stage1",
      "title": "string",
      "desc": "1-2 sentence description",
      "dependencies": ["other_node_id"],
      "defaultState": "inprogress if dependencies is empty, otherwise locked",
      "curriculum": ["4 specific bullet points of what to learn"],
      "search_keywords": ["2-4 words to find a real tutorial video on this topic"]
    }}
  ],
  "connections": [
    {{"from": "node_id", "to": "dependent_node_id"}}
  ]
}}

Keep node ids short, unique, snake_case. Every node outside stage 1 should
have at least one dependency. Do NOT invent resource URLs.
"""
    data = _call_gemini_json(prompt)

    for node in data.get("nodes", []):
        enrich_with_video(node)
        node["resources"] = [{
            "name": node.pop("resource_title", None) or f"{node.get('title', 'Tutorial')}",
            "platform": node.pop("resource_channel", None) or "YouTube",
            "url": node.pop("resource_url", None),
        }]

    return data


def generate_resume_analysis_with_ai(resume_text, target_role):
    """
    Calls Gemini to score/critique a resume against a target role, matching
    the schema resume-analyzer.html's renderResults() expects.
    """
    target_role_line = target_role if target_role else "a role matching their background (no specific target role given)"
    prompt = f"""
You are an expert resume reviewer and ATS (Applicant Tracking System) simulator.

Target role: {target_role_line}

Resume text:
\"\"\"
{resume_text[:12000]}
\"\"\"

Evaluate this resume for the target role and return ONLY valid JSON matching
exactly this schema:
{{
  "selection_chance": number (0-100, realistic estimate of shortlisting odds for the target role),
  "ats_score": number (0-100, how well an ATS would parse/rank this resume),
  "summary": "2-3 sentence overall verdict, direct and specific",
  "missing_sections": ["section or element the resume is missing, e.g. 'Quantified achievements'"],
  "keyword_gaps": ["important keyword/skill for the target role that's absent from the resume"],
  "strengths": ["specific genuine strength found in the resume"],
  "suggestions": ["specific, actionable improvement"]
}}

Keep each array to 3-6 concise items. Base everything on the actual resume
text given, do not invent details that aren't there or implied.
"""
    return _call_gemini_json(prompt)


# ── AI COACH CHAT (OpenRouter) ──
@app.route('/api/chat', methods=['POST'])
def api_chat():
    data = request.get_json(silent=True) or {}
    question = (data.get("question") or "").strip()

    print("Question:", question)
    print("API Key Loaded:", bool(OPENROUTER_API_KEY))

    if not question:
        return jsonify({"error": "Please type a question."}), 400

    today = datetime.utcnow().date().isoformat()
    user = None

    if session.get('user_id'):
        user = User.query.get(session['user_id'])
        if user:
            if user.chat_count_date != datetime.utcnow().date():
                user.chat_count_date = datetime.utcnow().date()
                user.chat_count_today = 0
            if not user.is_pro and (user.chat_count_today or 0) >= FREE_DAILY_CHAT_LIMIT:
                return jsonify({
                    "output": None,
                    "error": f"You've reached today's free limit of {FREE_DAILY_CHAT_LIMIT} messages. Upgrade to Pro for unlimited coaching."
                }), 200
    else:
        if session.get('anon_chat_date') != today:
            session['anon_chat_date'] = today
            session['anon_chat_count'] = 0
        if (session.get('anon_chat_count') or 0) >= FREE_DAILY_CHAT_LIMIT:
            return jsonify({
                "output": None,
                "error": f"You've reached today's free limit of {FREE_DAILY_CHAT_LIMIT} messages. Sign up and upgrade to Pro for unlimited coaching."
            }), 200

    if not GEMINI_API_KEY and not OPENROUTER_API_KEY:
        return jsonify({
            "output": None,
            "error": "No AI API key configured."
        }), 200

    try:
        # ---------- Try Gemini first ----------
        try:
            response = gemini_client.models.generate_content(
                model="gemini-2.5-flash",
                contents=[
                    CARA_SYSTEM_PROMPT,
                    question
                ]
            )
            answer = response.text

        # ---------- If Gemini fails, fall back to OpenRouter ----------
        except Exception as gemini_error:
            print("Gemini Error:", gemini_error)
            print("Switching to OpenRouter...")

            response = client.chat.completions.create(
                model="meta-llama/llama-3.3-70b-instruct:free",
                messages=[
                    {"role": "system", "content": CARA_SYSTEM_PROMPT},
                    {"role": "user", "content": question}
                ]
            )
            answer = response.choices[0].message.content

        # Count messages
        if user:
            user.chat_count_today = (user.chat_count_today or 0) + 1
            db.session.commit()
        else:
            session['anon_chat_count'] = (session.get('anon_chat_count') or 0) + 1

        return jsonify({"output": answer})

    except Exception as e:
        print("AI Error:", e)
        return jsonify({
            "output": None,
            "error": str(e)
        }), 200

# ── STATIC PAGE ROUTES ──
@app.route('/')
def home():
    return render_template('index.html')
@app.route('/about')
def about():
    return render_template('about.html')
@app.route('/features')
def features():
    return render_template('features.html')

@app.route('/stories')
def stories():
    return render_template('stories.html')

@app.route('/pricing')
def pricing():
    return render_template('pricing.html')

@app.route('/faq')
def faq():
    return render_template('faq.html')


# ── LOGIN ──
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        user = User.query.filter_by(email=request.form['email']).first()
        if user and check_password_hash(user.password_hash, request.form['password']):
            if not user.is_verified:
                flash('Please verify your email first.')
                return redirect(url_for('signup'))
            session['user_id'] = user.id
            if not user.profile_complete:
                return redirect(url_for('profile_setup'))
            return redirect(url_for('profile'))
        flash('Invalid email or password.')
        return redirect(url_for('login'))
    return render_template('login.html')


# ── LOGOUT ──
@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))


# ── SIGNUP + OTP ROUTES ──
@app.route('/signup', methods=['GET', 'POST'])
def signup():
    if request.method == 'POST':
        name = request.form['name']
        email = request.form['email']
        password = request.form['password']

        if User.query.filter_by(email=email).first():
            flash('Email already registered.')
            return redirect(url_for('signup'))

        user = User(
            name=name,
            email=email,
            password_hash=generate_password_hash(password),
            is_verified=False
        )
        db.session.add(user)
        db.session.commit()

        generate_and_send_otp(email)
        session['pending_email'] = email
        return redirect(url_for('verify_otp'))

    return render_template('signup.html')

@app.route('/verify-otp', methods=['GET', 'POST'])
def verify_otp():
    email = session.get('pending_email')
    if not email:
        return redirect(url_for('signup'))

    if request.method == 'POST':
        entered_otp = request.form['otp']
        record = OTPVerification.query.filter_by(email=email).first()

        if not record:
            flash('No OTP found. Please request a new one.')
            return redirect(url_for('verify_otp'))

        if datetime.utcnow() > record.expires_at:
            flash('OTP expired. Please request a new one.')
            return redirect(url_for('verify_otp'))

        if entered_otp != record.otp_code:
            flash('Incorrect OTP. Try again.')
            return redirect(url_for('verify_otp'))

        user = User.query.filter_by(email=email).first()
        user.is_verified = True
        db.session.commit()

        db.session.delete(record)
        db.session.commit()

        session.pop('pending_email', None)
        session['user_id'] = user.id
        return redirect(url_for('profile_setup'))

    return render_template('verify_otp.html', email=email)

@app.route('/resend-otp')
def resend_otp():
    email = session.get('pending_email')
    if email:
        generate_and_send_otp(email)
        flash('A new OTP has been sent.')
    return redirect(url_for('verify_otp'))


# ── PROFILE SETUP ──
@app.route('/profile-setup', methods=['GET', 'POST'])
def profile_setup():
    user = User.query.get(session.get("user_id"))

    if not user:
        return redirect(url_for("login"))

    if request.method == "POST":
        # ── basics ──
        user.bio = request.form.get("bio", "")
        user.target_role = request.form.get("target_role", "")
        user.domain = request.form.get("domain", "")

        # ── contact details ──
        user.phone = request.form.get("phone", "")
        user.location = request.form.get("location", "")
        user.linkedin = request.form.get("linkedin", "")
        user.github = request.form.get("github", "")

        # ── resume upload ──
        resume_file = request.files.get("resume")
        if resume_file and resume_file.filename:
            filename = secure_filename(f"user_{user.id}_{resume_file.filename}")
            resume_file.save(os.path.join(UPLOAD_FOLDER, filename))
            user.resume_filename = filename
            # plug in real scoring logic later; placeholder for now
            user.resume_score = user.resume_score or 0

        # ── skills (replace all on each save) ──
        Skill.query.filter_by(user_id=user.id).delete()
        skill_names = request.form.getlist("skill_name[]")
        skill_levels = request.form.getlist("skill_level[]")
        for name, level in zip(skill_names, skill_levels):
            name = name.strip()
            if name:
                db.session.add(Skill(user_id=user.id, name=name, level=level))

        # ── education (replace all on each save) ──
        Education.query.filter_by(user_id=user.id).delete()
        schools = request.form.getlist("edu_school[]")
        degrees = request.form.getlist("edu_degree[]")
        years = request.form.getlist("edu_years[]")
        for school, degree, yr in zip(schools, degrees, years):
            school = school.strip()
            if school:
                db.session.add(Education(user_id=user.id, school=school, degree=degree, years=yr))

        # ── experience (replace all on each save) ──
        Experience.query.filter_by(user_id=user.id).delete()
        titles = request.form.getlist("exp_title[]")
        companies = request.form.getlist("exp_company[]")
        dates = request.form.getlist("exp_dates[]")
        for title, company, dt in zip(titles, companies, dates):
            title = title.strip()
            if title:
                db.session.add(Experience(user_id=user.id, title=title, company=company, dates=dt))

        user.profile_complete = True
        db.session.commit()

        return redirect(url_for("assessment", domain=user.domain))

    return render_template("profile_setup.html", user=user)

@app.route("/assessment/<domain>")
def assessment(domain):
    user = User.query.get(session.get("user_id"))

    if not user:
        return redirect(url_for("login"))

    questions = AssessmentQuestion.query.filter_by(domain=domain).all()
    random.shuffle(questions)          # different order every time
    questions = questions[:20]         # cap at 20 even if more exist later

    question_list = []
    for q in questions:
        question_list.append({
            "id": q.id,
            "text": q.question,
            "options": [q.option_a, q.option_b, q.option_c, q.option_d]
        })

    return render_template(
        "assessment.html",
        user=user,
        domain=domain,
        domain_label=DOMAIN_LABELS.get(domain),
        questions=question_list
    )
@app.route("/assessment-submit", methods=["POST"])
def assessment_submit():
    user = User.query.get(session.get("user_id"))

    if not user:
        return redirect(url_for("login"))

    domain = request.form["domain"]
    questions = AssessmentQuestion.query.filter_by(domain=domain).all()

    score = 0
    for q in questions:
        selected = request.form.get(f"answer_{q.id}")
        if selected is not None:
            if int(selected) == q.correct_answer:
                score += 1

    result = AssessmentResult(user_id=user.id, domain=domain, score=score)
    db.session.add(result)
    db.session.commit()

    return render_template(
        "assessment_result.html",
        user=user,
        score=score,
        domain_label=DOMAIN_LABELS.get(domain)
    )


# ── PROFILE PAGE ──
def calculate_profile_percent(user):
    """
    Weighted profile-completion score, out of 100.

    Core identity, contact info, resume, skills, education and experience
    make up 90% between them (so a bare-bones signup never reads as
    "done"). The remaining 10% is a small, steadily-growing bonus for
    actually using the product — finishing roadmap milestones/courses —
    so the number keeps nudging upward as the user learns, not just when
    they edit their profile.
    """
    score = 0.0

    # Core identity — 20%
    core_fields = [user.name, user.email, user.target_role, user.domain, user.bio]
    score += (sum(1 for f in core_fields if f) / len(core_fields)) * 20

    # Contact details — 15%
    contact_fields = [user.phone, user.location, user.linkedin, user.github]
    score += (sum(1 for f in contact_fields if f) / len(contact_fields)) * 15

    # Resume uploaded — 10%
    if user.resume_filename:
        score += 10

    # Skills added — 15%
    if getattr(user, 'skills', None):
        score += 15

    # Education added — 15%
    if getattr(user, 'education', None):
        score += 15

    # Experience added — 15%
    if getattr(user, 'experience', None):
        score += 15

    # Learning progress — up to 10% bonus, +2% per completed roadmap
    # milestone/course, so it ticks up a little each time one is finished.
    completed_milestones = (
        RoadmapMilestone.query
        .join(Roadmap, RoadmapMilestone.roadmap_id == Roadmap.id)
        .filter(Roadmap.user_id == user.id, RoadmapMilestone.status == "completed")
        .count()
    )
    score += min(completed_milestones * 2, 10)

    return min(round(score), 100)


@app.route('/profile')
def profile():
    user = User.query.get(session.get('user_id'))
    if not user:
        return redirect(url_for('login'))
    return render_template('profile.html', user=user, profile_percent=calculate_profile_percent(user))



# ── DASHBOARD ──
def _recalculate_roadmap_progress(roadmap_id):
    """
    Recomputes Roadmap.progress_percent from its milestones' status column.
    Call this any time a milestone's status changes. Safe to call with a
    roadmap that has zero milestones (progress stays 0, no division error).
    """
    total = RoadmapMilestone.query.filter_by(roadmap_id=roadmap_id).count()
    completed = RoadmapMilestone.query.filter_by(roadmap_id=roadmap_id, status="completed").count()
    percent = round((completed / total) * 100) if total else 0

    roadmap = Roadmap.query.get(roadmap_id)
    if roadmap:
        roadmap.progress_percent = percent
        if total and completed == total:
            roadmap.status = "completed"
        db.session.commit()
    return percent, completed, total


def _get_learning_progress(user):
    """
    Builds the real "what you've learned / what's pending" data for the
    dashboard from the user's active roadmap. Returns a dict the template
    can render directly, or None if the user hasn't generated a roadmap yet.
    """
    active_roadmap = Roadmap.query.filter_by(user_id=user.id, status="active").first()
    if not active_roadmap:
        return None

    milestones = (RoadmapMilestone.query
                  .filter_by(roadmap_id=active_roadmap.id)
                  .order_by(RoadmapMilestone.week)
                  .all())

    completed = [m for m in milestones if m.status == "completed"]
    pending = [m for m in milestones if m.status != "completed"]
    total = len(milestones)
    percent = round((len(completed) / total) * 100) if total else 0

    if active_roadmap.progress_percent != percent:
        active_roadmap.progress_percent = percent
        db.session.commit()

    return {
        "roadmap": active_roadmap,
        "completed": completed,
        "pending": pending,
        "total": total,
        "completed_count": len(completed),
        "pending_count": len(pending),
        "percent": percent,
    }


@app.route('/dashboard')
def dashboard():
    user = User.query.get(session.get('user_id'))
    if not user:
        return redirect(url_for('login'))
    profile_percent = calculate_profile_percent(user)
    learning = _get_learning_progress(user)
    return render_template(
        'dashboard.html',
        user=user,
        profile_percent=profile_percent,
        learning=learning,
    )


@app.route('/api/milestones/<int:milestone_id>/toggle', methods=['POST'])
def toggle_milestone(milestone_id):
    """
    Marks a milestone as completed (or back to pending) and recomputes the
    parent Roadmap's progress_percent so the dashboard and roadmap page
    both stay accurate. Client can send an explicit target status; if it
    doesn't, we just flip whatever the current status is.
    """
    user = User.query.get(session.get('user_id'))
    if not user:
        return jsonify({"error": "Please log in first."}), 401

    milestone = RoadmapMilestone.query.get(milestone_id)
    if not milestone:
        return jsonify({"error": "Milestone not found."}), 404

    roadmap = Roadmap.query.get(milestone.roadmap_id)
    if not roadmap or roadmap.user_id != user.id:
        return jsonify({"error": "Not authorized to update this milestone."}), 403

    body = request.get_json(silent=True) or {}
    new_status = body.get("status")
    if new_status not in ("completed", "pending"):
        new_status = "pending" if milestone.status == "completed" else "completed"

    # Milestones with a video attached must be earned via the quiz, not
    # checked off by hand — unchecking (going back to pending) is still
    # always allowed manually.
    if new_status == "completed" and milestone.resource_video_id and not milestone.quiz_passed:
        return jsonify({
            "error": "Watch the video and pass the short quiz to complete this milestone.",
            "requires_quiz": True,
        }), 400

    milestone.status = new_status
    db.session.commit()

    percent, completed, total = _recalculate_roadmap_progress(roadmap.id)

    return jsonify({
        "success": True,
        "milestone_id": milestone.id,
        "status": milestone.status,
        "roadmap_progress_percent": percent,
        "completed_count": completed,
        "total_count": total,
    }), 200


@app.route('/api/milestones/<int:milestone_id>/video-watched', methods=['POST'])
def mark_video_watched(milestone_id):
    """
    Called by the embedded player's onStateChange handler the moment the
    video reaches ENDED. Just flags video_watched — completion still
    requires passing the quiz, so this alone doesn't move progress_percent.
    """
    user = User.query.get(session.get('user_id'))
    if not user:
        return jsonify({"error": "Please log in first."}), 401

    milestone = RoadmapMilestone.query.get(milestone_id)
    if not milestone:
        return jsonify({"error": "Milestone not found."}), 404

    roadmap = Roadmap.query.get(milestone.roadmap_id)
    if not roadmap or roadmap.user_id != user.id:
        return jsonify({"error": "Not authorized."}), 403

    milestone.video_watched = True
    db.session.commit()
    return jsonify({"success": True}), 200


@app.route('/api/milestones/<int:milestone_id>/quiz', methods=['GET'])
def get_milestone_quiz(milestone_id):
    """
    Returns the quiz for this milestone (generating it via Gemini the
    first time it's requested, caching it after that). correct_index is
    stripped before sending — grading happens server-side in quiz-submit.
    Pass ?regenerate=1 to force a fresh set of questions (e.g. after a
    failed attempt, if you want the user to face different questions).
    """
    user = User.query.get(session.get('user_id'))
    if not user:
        return jsonify({"error": "Please log in first."}), 401

    milestone = RoadmapMilestone.query.get(milestone_id)
    if not milestone:
        return jsonify({"error": "Milestone not found."}), 404

    roadmap = Roadmap.query.get(milestone.roadmap_id)
    if not roadmap or roadmap.user_id != user.id:
        return jsonify({"error": "Not authorized."}), 403

    if not milestone.video_watched:
        return jsonify({"error": "Finish watching the video first.", "requires_video": True}), 400

    regenerate = request.args.get("regenerate") == "1"

    try:
        quiz = _get_or_create_quiz(milestone, regenerate=regenerate)
    except RateLimitError:
        return jsonify({"error": "AI is busy right now. Please try again in a moment.", "retry": True}), 429
    except (json.JSONDecodeError, ValueError) as e:
        print("Quiz generation error:", e)
        return jsonify({"error": "Couldn't generate a quiz for this milestone. Please try again."}), 502

    questions = json.loads(quiz.questions_json)
    # Strip correct_index before sending to the client.
    public_questions = [
        {"id": q["id"], "question": q["question"], "options": q["options"], "marks": q["marks"]}
        for q in questions
    ]

    return jsonify({
        "milestone_id": milestone.id,
        "milestone_title": milestone.title,
        "total_marks": quiz.total_marks,
        "questions": public_questions,
        "attempts_so_far": milestone.quiz_attempts or 0,
        "already_passed": bool(milestone.quiz_passed),
    }), 200


@app.route('/api/milestones/<int:milestone_id>/quiz-submit', methods=['POST'])
def submit_milestone_quiz(milestone_id):
    """
    Grades the submitted answers against the stored quiz, records the
    score/attempt, and — if the score clears QUIZ_PASS_THRESHOLD — marks
    the milestone completed and recalculates roadmap progress in the same
    step. This is the ONLY path (besides unchecking) that can complete a
    milestone that has a video attached.
    """
    user = User.query.get(session.get('user_id'))
    if not user:
        return jsonify({"error": "Please log in first."}), 401

    milestone = RoadmapMilestone.query.get(milestone_id)
    if not milestone:
        return jsonify({"error": "Milestone not found."}), 404

    roadmap = Roadmap.query.get(milestone.roadmap_id)
    if not roadmap or roadmap.user_id != user.id:
        return jsonify({"error": "Not authorized."}), 403

    quiz = MilestoneQuiz.query.filter_by(milestone_id=milestone.id).first()
    if not quiz:
        return jsonify({"error": "No quiz has been generated for this milestone yet."}), 400

    body = request.get_json(silent=True) or {}
    answers = body.get("answers", {})  # {"q1": 2, "q2": 0, ...}

    questions = json.loads(quiz.questions_json)
    score = 0
    results = []
    for q in questions:
        selected = answers.get(q["id"])
        is_correct = selected is not None and int(selected) == q["correct_index"]
        if is_correct:
            score += q["marks"]
        results.append({
            "id": q["id"],
            "correct": is_correct,
            "correct_index": q["correct_index"],
            "your_answer": selected,
        })

    passed = quiz.total_marks > 0 and (score / quiz.total_marks) >= QUIZ_PASS_THRESHOLD

    milestone.quiz_score = score
    milestone.quiz_total = quiz.total_marks
    milestone.quiz_attempts = (milestone.quiz_attempts or 0) + 1
    if passed:
        milestone.quiz_passed = True
        milestone.status = "completed"
    db.session.commit()

    percent, completed, total = _recalculate_roadmap_progress(roadmap.id)

    return jsonify({
        "success": True,
        "score": score,
        "total_marks": quiz.total_marks,
        "passed": passed,
        "results": results,
        "milestone_status": milestone.status,
        "roadmap_progress_percent": percent,
        "completed_count": completed,
        "total_count": total,
    }), 200


@app.route('/api/milestones/<int:milestone_id>/notes', methods=['GET'])
def get_milestone_notes(milestone_id):
    """
    Returns study notes + Q&A for this milestone (generating them via
    Gemini the first time they're requested, caching after that). No
    video-watched gate — notes are meant to help even before/instead of
    watching, unlike the graded quiz. Pass ?regenerate=1 for a fresh set.
    """
    user = User.query.get(session.get('user_id'))
    if not user:
        return jsonify({"error": "Please log in first."}), 401

    milestone = RoadmapMilestone.query.get(milestone_id)
    if not milestone:
        return jsonify({"error": "Milestone not found."}), 404

    roadmap_obj = Roadmap.query.get(milestone.roadmap_id)
    if not roadmap_obj or roadmap_obj.user_id != user.id:
        return jsonify({"error": "Not authorized."}), 403

    regenerate = request.args.get("regenerate") == "1"

    try:
        notes = _get_or_create_notes(milestone, regenerate=regenerate)
    except RateLimitError:
        return jsonify({"error": "AI is busy right now. Please try again in a moment.", "retry": True}), 429
    except (json.JSONDecodeError, ValueError) as e:
        print("Notes generation error:", e)
        return jsonify({"error": "Couldn't generate notes for this milestone. Please try again."}), 502
    except Exception as e:
        print("Notes generation error:", e)
        traceback.print_exc()
        return jsonify({"error": "Something went wrong generating notes."}), 500

    def _parsed_sections(notes_row):
        parsed = json.loads(notes_row.notes_text or "[]")
        if not isinstance(parsed, list) or not parsed or not all(isinstance(s, dict) and s.get("points") for s in parsed):
            raise ValueError("Not in the structured sections format.")
        return parsed

    try:
        sections = _parsed_sections(notes)
    except (json.JSONDecodeError, ValueError):
        # This row predates the structured-sections format (one free-text
        # markdown blob instead of {"heading","points"} sections) — rather
        # than showing that raw, asterisk-laden text, transparently
        # regenerate it into the current format right now.
        print(f"Milestone {milestone.id}: legacy notes format detected, auto-upgrading.")
        try:
            notes = _get_or_create_notes(milestone, regenerate=True)
            sections = _parsed_sections(notes)
        except RateLimitError:
            return jsonify({"error": "AI is busy right now. Please try again in a moment.", "retry": True}), 429
        except Exception as e:
            print("Notes auto-upgrade error:", e)
            traceback.print_exc()
            return jsonify({"error": "Couldn't refresh notes for this milestone. Please try again."}), 502

    return jsonify({
        "milestone_id": milestone.id,
        "milestone_title": milestone.title,
        "sections": sections,
        "qa": json.loads(notes.qa_json or "[]"),
    }), 200


# ── ROADMAP ──
@app.route('/roadmap')
def roadmap():
    user = User.query.get(session.get('user_id'))
    if not user:
        return redirect(url_for('login'))

    # order_by(...desc()) is a safety net in case any old rows from before
    # generate-roadmap started archiving predecessors left more than one
    # "active" roadmap for this user — newest wins.
    existing = (Roadmap.query
                .filter_by(user_id=user.id, status="active")
                .order_by(Roadmap.created_at.desc())
                .first())

    if existing:
        milestones = RoadmapMilestone.query.filter_by(roadmap_id=existing.id).order_by(RoadmapMilestone.week).all()
        return render_template('roadmap.html', user=user, roadmap=existing, milestones=milestones)

    return render_template('roadmap.html', user=user, roadmap=None, milestones=None)


@app.route('/api/roadmap/history')
def roadmap_history():
    """
    Lists this user's past (archived/completed) roadmaps so switching
    topics doesn't feel like losing work — each entry shows what it was,
    how far they got, and when it stopped being active.
    """
    user = User.query.get(session.get('user_id'))
    if not user:
        return jsonify({"error": "Please log in first."}), 401

    past = (Roadmap.query
            .filter(Roadmap.user_id == user.id, Roadmap.status != "active")
            .order_by(Roadmap.created_at.desc())
            .all())

    return jsonify({
        "roadmaps": [
            {
                "id": r.id,
                "title": r.title,
                "target_role": r.target_role,
                "status": r.status,
                "progress_percent": r.progress_percent,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in past
        ]
    }), 200


@app.route('/api/generate-roadmap', methods=['POST'])
def generate_roadmap():
    user = User.query.get(session.get('user_id'))
    if not user:
        return jsonify({"error": "Please log in first."}), 401

    body = request.get_json(silent=True) or {}
    topic = (body.get('topic') or '').strip()
    prior_knowledge = (body.get('prior_knowledge') or '').strip()
    confirm_switch = bool(body.get('confirm_switch'))

    if not topic:
        return jsonify({"error": "Tell me what you'd like to learn first."}), 400

    existing_active = Roadmap.query.filter_by(user_id=user.id, status="active").first()
    if existing_active and not confirm_switch:
        # Someone already has an active roadmap — don't silently replace it.
        # The frontend is expected to confirm with the user (they'll lose
        # "active" status on the old roadmap, though its progress/history
        # stays in the DB) and resend with confirm_switch: true.
        return jsonify({
            "error": "You already have an active roadmap. Confirm switching to archive it and start a new one.",
            "requires_confirmation": True,
            "current_roadmap_title": existing_active.title,
        }), 409

    try:
        data = generate_roadmap_with_ai(
            target_role=topic,
            domain=user.domain,
            prior_knowledge=prior_knowledge,
        )

        # Retire any roadmap(s) currently marked active for this user before
        # creating the new one. Without this, generating a second roadmap
        # (i.e. the user changing topics) would leave two "active" rows for
        # the same user, and /roadmap would show whichever one the DB
        # happens to return first — not necessarily the new one. Progress
        # on the old roadmap/milestones is kept, just no longer "active".
        Roadmap.query.filter_by(user_id=user.id, status="active").update(
            {"status": "archived"}, synchronize_session=False
        )
        db.session.commit()

        new_roadmap = Roadmap(
            user_id=user.id,
            title=data["title"],
            target_role=data["target_role"],
            total_weeks=data["total_weeks"],
            progress_percent=0,
            status="active"
        )
        db.session.add(new_roadmap)
        db.session.commit()

        for m in data["milestones"]:
            milestone = RoadmapMilestone(
                roadmap_id=new_roadmap.id,
                week=m["week"],
                title=m["title"],
                task=m["task"],
                resource_url=m["resource_url"],
                resource_title=m.get("resource_title"),
                resource_channel=m.get("resource_channel"),
                resource_video_id=m.get("resource_video_id"),
                resource_duration=m.get("resource_duration"),
                resource_views=m.get("resource_views"),
                resource_thumbnail=m.get("resource_thumbnail"),
                estimated_hours=m["estimated_hours"],
                status="pending",
                milestone_type=m.get("milestone_type", "new"),
            )
            db.session.add(milestone)
        db.session.commit()

        return jsonify({"success": True, "roadmap_id": new_roadmap.id}), 200

    except RateLimitError:
        return jsonify({"error": "AI is busy right now. Please try again in a moment.", "retry": True}), 429

    except json.JSONDecodeError:
        return jsonify({"error": "AI returned invalid format. Please try again."}), 502

    except ValueError as e:
        print("Roadmap generation error (no milestones):", e)
        return jsonify({"error": "The AI couldn't build a proper roadmap for that. Try rephrasing what you want to learn, or try again."}), 502

    except Exception as e:
        # Full traceback in the server console so the *real* cause shows up
        # instead of just "Something went wrong" — check your terminal/logs.
        print("Roadmap generation error:", e)
        traceback.print_exc()
        return jsonify({"error": "Something went wrong generating your roadmap."}), 500

print("YOUTUBE_API_KEY found:", bool(Config.YOUTUBE_API_KEY))
@app.route('/api/generate-pathfinder', methods=['POST'])
def generate_pathfinder():
    body = request.get_json(silent=True) or {}
    current_role = (body.get('current_role') or '').strip()
    target_role = (body.get('target_role') or '').strip()

    if not current_role or not target_role:
        return jsonify({"error": "Both current and target roles are needed."}), 400

    try:
        path = generate_pathfinder_with_ai(current_role, target_role)
        return jsonify({"success": True, "path": path}), 200

    except RateLimitError:
        return jsonify({"error": "AI is busy right now. Please try again in a moment.", "retry": True}), 429

    except json.JSONDecodeError:
        return jsonify({"error": "AI returned invalid format. Please try again."}), 502

    except Exception as e:
        print("Pathfinder generation error:", e)
        return jsonify({"error": "Something went wrong generating your skill tree."}), 500


# ── CAREER CENTER ──
@app.route('/career-center')
def career_center():
    if 'user_id' not in session:
        return redirect(url_for('login'))

    user = User.query.get(session['user_id'])

    if not user:
        session.clear()
        return redirect(url_for('login'))

    latest_analysis = (
        ResumeAnalysis.query
        .filter_by(user_id=user.id)
        .order_by(ResumeAnalysis.created_at.desc())
        .first()
    )

    analysis = latest_analysis.as_dict() if latest_analysis else None

    stats = {
    "applications": Application.query.filter_by(user_id=user.id).count(),
    "interviews": Interview.query.filter_by(user_id=user.id).count(),
    "saved_jobs": SavedJob.query.filter_by(user_id=user.id).count(),
    "ai_match_avg": calculate_ai_match(user.id),
}

    initials = "".join(
        part[0].upper()
        for part in (user.name or "?").split()[:2]
    ) or "?"

    return render_template(
        "career-center.html",
        user=user,
        user_initials=initials,
        analysis=analysis,
        stats=stats,
    )


# ── CAREER CENTER REST APIS ──

@app.route('/career/jobs')
def career_jobs():
    if 'user_id' not in session:
        return jsonify({"error": "Please log in first."}), 401

    query = Job.query
    
    # Filters from query params
    role = request.args.get('role', '').strip()
    location = request.args.get('location', '').strip()
    company = request.args.get('company', '').strip()
    domain = request.args.get('domain', '').strip()
    experience = request.args.get('experience', '').strip()
    salary = request.args.get('salary', '').strip()
    remote = request.args.get('remote')
    
    if role:
        query = query.filter(Job.job_title.ilike(f"%{role}%"))
    if location:
        query = query.filter(Job.location.ilike(f"%{location}%"))
    if company:
        query = query.filter(Job.company_name.ilike(f"%{company}%"))
    if domain and domain != "Any":
        query = query.filter(Job.domain == domain)
    if remote == 'true':
        query = query.filter(Job.job_type == 'Remote')
        
    # Standardize values from dropdowns
    if experience and experience != "Any":
        query = query.filter(Job.experience == experience)
    if salary and salary != "Any":
        query = query.filter(Job.salary == salary)

    jobs = query.order_by(Job.posted_date.desc()).all()
    user_id = session['user_id']
    saved_job_ids = {sj.job_id for sj in SavedJob.query.filter_by(user_id=user_id).all()}
    applied_job_ids = {a.job_id for a in Application.query.filter_by(user_id=user_id).all()}
    
    # Calculate match scores
    user = User.query.get(user_id)
    user_skills = {s.name.lower().strip() for s in user.skills} if user.skills else set()
    
    jobs_list = []
    for j in jobs:
        d = j.to_dict()
        d['saved'] = j.id in saved_job_ids
        d['applied'] = j.id in applied_job_ids
        
        # Calculate individual match details
        job_skills_list = [s.strip() for s in (j.skills_required or "").split(",") if s.strip()]
        job_skills = {s.lower().strip() for s in job_skills_list}
        
        matching_skills = []
        missing_skills = []
        for s in job_skills_list:
            if s.lower().strip() in user_skills:
                matching_skills.append(s)
            else:
                missing_skills.append(s)
                
        d['matching_skills'] = matching_skills
        d['missing_skills'] = missing_skills
        
        if not job_skills:
            d['match_pct'] = 100
        elif not user_skills:
            d['match_pct'] = 75
        else:
            intersection = user_skills.intersection(job_skills)
            d['match_pct'] = round((len(intersection) / len(job_skills)) * 100) if len(job_skills) > 0 else 75
            
        jobs_list.append(d)
        
    return jsonify(jobs_list)


@app.route('/career/save-job', methods=['POST'])
def save_job():
    if 'user_id' not in session:
        return jsonify({"error": "Please log in first."}), 401
    
    data = request.get_json(silent=True) or {}
    job_id = data.get('job_id')
    if not job_id:
        return jsonify({"error": "Missing job_id."}), 400
        
    user_id = session['user_id']
    existing = SavedJob.query.filter_by(user_id=user_id, job_id=job_id).first()
    
    if existing:
        db.session.delete(existing)
        action = "unsaved"
    else:
        new_save = SavedJob(user_id=user_id, job_id=job_id)
        db.session.add(new_save)
        action = "saved"
        
    db.session.commit()
    
    saved_count = SavedJob.query.filter_by(user_id=user_id).count()
    return jsonify({
        "success": True,
        "action": action,
        "saved_jobs_count": saved_count
    })


@app.route('/career/apply', methods=['POST'])
def apply_job():
    if 'user_id' not in session:
        return jsonify({"error": "Please log in first."}), 401
        
    data = request.get_json(silent=True) or {}
    job_id = data.get('job_id')
    if not job_id:
        return jsonify({"error": "Missing job_id."}), 400
        
    user_id = session['user_id']
    existing = Application.query.filter_by(user_id=user_id, job_id=job_id).first()
    
    if existing:
        return jsonify({"error": "You have already applied for this job.", "already_applied": True}), 400
        
    new_app = Application(user_id=user_id, job_id=job_id, status="Applied")
    db.session.add(new_app)
    db.session.commit()
    
    app_count = Application.query.filter_by(user_id=user_id).count()
    return jsonify({
        "success": True,
        "applications_count": app_count,
        "application": {
            "id": new_app.id,
            "job_title": new_app.job.job_title,
            "company_name": new_app.job.company_name,
            "status": new_app.status,
            "applied_date": new_app.applied_date.strftime('%Y-%m-%d')
        }
    })


@app.route('/career/applications')
def career_applications():
    if 'user_id' not in session:
        return jsonify({"error": "Please log in first."}), 401
        
    user_id = session['user_id']
    apps = Application.query.filter_by(user_id=user_id).order_by(Application.applied_date.desc()).all()
    
    apps_list = []
    for a in apps:
        apps_list.append({
            "id": a.id,
            "job_id": a.job_id,
            "job_title": a.job.job_title,
            "company_name": a.job.company_name,
            "company_logo": a.job.company_logo,
            "status": a.status,
            "applied_date": a.applied_date.strftime('%d %b %Y')
        })
    return jsonify(apps_list)


@app.route('/career/interviews')
def career_interviews():
    if 'user_id' not in session:
        return jsonify({"error": "Please log in first."}), 401
        
    user_id = session['user_id']
    interviews = Interview.query.filter_by(user_id=user_id).order_by(Interview.interview_date.asc()).all()
    
    int_list = []
    for i in interviews:
        int_list.append({
            "id": i.id,
            "company_name": i.company_name,
            "job_title": i.job_title,
            "interview_date": i.interview_date.strftime('%Y-%m-%dT%H:%M:%S+05:30'),
            "interview_date_str": i.interview_date.strftime('%d %b %Y'),
            "interview_time_str": i.interview_date.strftime('%I:%M %p IST'),
            "meeting_link": i.meeting_link,
            "status": i.status,
            "round_name": i.round_name
        })
    return jsonify(int_list)



# ── RESUME BUILDER ──
@app.route('/resume-builder')
def resume_builder():
    user = User.query.get(session.get('user_id'))
    if not user:
        return redirect(url_for('login'))
    return render_template('resume-builder.html', user=user)


# ── RESUME ANALYZER ──
@app.route('/resume-analyzer')
def resume_analyzer():
    user = User.query.get(session.get('user_id'))
    if not user:
        return redirect(url_for('login'))

    latest = (
        ResumeAnalysis.query
        .filter_by(user_id=user.id)
        .order_by(ResumeAnalysis.created_at.desc())
        .first()
    )
    analysis = latest.as_dict() if latest else None

    return render_template('resume-analyzer.html', user=user, analysis=analysis)


@app.route('/resume-analyzer/analyze', methods=['POST'], endpoint='resume_analyzer_analyze')
def resume_analyzer_analyze():
    user = User.query.get(session.get('user_id'))
    if not user:
        return jsonify({"error": "Please log in again."}), 401

    resume_file = request.files.get('resume')

    # A new file was uploaded — save it and use it for this analysis.
    if resume_file and resume_file.filename:
        ext = resume_file.filename.rsplit('.', 1)[-1].lower() if '.' in resume_file.filename else ''
        if ext not in RESUME_ALLOWED_EXTENSIONS:
            return jsonify({"error": "Please upload a PDF, DOCX, or TXT resume."}), 400

        filename = secure_filename(f"user_{user.id}_{resume_file.filename}")
        filepath = os.path.join(UPLOAD_FOLDER, filename)
        resume_file.save(filepath)
        user.resume_filename = filename
        db.session.commit()
    elif user.resume_filename:
        # No new upload — re-analyze the resume already on file.
        filepath = os.path.join(UPLOAD_FOLDER, user.resume_filename)
    else:
        return jsonify({"error": "Please upload a resume first."}), 400

    resume_text, extract_fail_reason = extract_resume_text(filepath)
    if not resume_text:
        error_messages = {
            "not_found": "We couldn't find that resume file on the server anymore. Please upload it again.",
            "pdf_no_text_layer": "This file looks like a scanned image or a picture-based PDF, so there's no selectable text in it. Try exporting your resume as a text-based PDF (e.g. from Word/Google Docs \u2192 Export as PDF) or upload a DOCX/TXT instead.",
            "pdf_error": "We hit an error opening that PDF — it may be corrupted or password-protected. Try re-saving it and uploading again.",
            "docx_error": "We hit an error opening that DOCX file. Try re-saving it from Word and uploading again.",
            "docx_not_real_docx": "This file doesn't look like a valid .docx — it may actually be an older .doc file renamed, or the upload got corrupted. Open it in Word and use \u2018Save As \u2192 Word Document (.docx)\u2019, then upload the new file.",
            "txt_error": "We hit an error reading that TXT file. Try re-saving it with UTF-8 encoding.",
            "unsupported": "Please upload a PDF, DOCX, or TXT resume.",
        }
        message = error_messages.get(extract_fail_reason, "Couldn't read text from that file. Try a different PDF, DOCX, or TXT resume.")
        return jsonify({"error": message}), 400

    try:
        data = generate_resume_analysis_with_ai(resume_text, user.target_role)

        analysis = ResumeAnalysis(
            user_id=user.id,
            selection_chance=data.get("selection_chance"),
            ats_score=data.get("ats_score"),
            summary=data.get("summary"),
            missing_sections=json.dumps(data.get("missing_sections") or []),
            keyword_gaps=json.dumps(data.get("keyword_gaps") or []),
            strengths=json.dumps(data.get("strengths") or []),
            suggestions=json.dumps(data.get("suggestions") or []),
        )
        db.session.add(analysis)
        user.resume_score = analysis.selection_chance
        db.session.commit()

        result = analysis.as_dict()
        result["resume_filename"] = user.resume_filename
        return jsonify(result), 200

    except RateLimitError:
        return jsonify({"error": "AI is busy right now. Please try again in a moment.", "retry": True}), 429

    except json.JSONDecodeError:
        return jsonify({"error": "AI returned invalid format. Please try again."}), 502

    except Exception as e:
        print("Resume analysis error:", e)
        traceback.print_exc()
        return jsonify({"error": "Something went wrong analyzing your resume."}), 500


@app.route('/resume-analyzer/delete', methods=['POST'], endpoint='resume_analyzer_delete')
def resume_analyzer_delete():
    user = User.query.get(session.get('user_id'))
    if not user:
        return jsonify({"error": "Please log in again."}), 401

    if not user.resume_filename:
        return jsonify({"error": "No resume on file to delete."}), 400

    filepath = os.path.join(UPLOAD_FOLDER, user.resume_filename)
    try:
        if os.path.isfile(filepath):
            os.remove(filepath)
    except OSError as e:
        print("Resume delete error:", e)
        return jsonify({"error": "Couldn't delete that file from the server. Please try again."}), 500

    user.resume_filename = None
    user.resume_score = None
    db.session.commit()

    return jsonify({"success": True}), 200


# ── SETTINGS ──
@app.route('/settings')
def settings():
    user = User.query.get(session.get('user_id'))
    if not user:
        return redirect(url_for('login'))
    return render_template('settings.html', user=user)


# ── SKILL PATHFINDER ──
@app.route('/skill-pathfinder')
def skill_pathfinder():
    user_id = session.get('user_id')
    user = User.query.get(user_id) if user_id else None
    return render_template('skill_pathfinder.html', user=user)


# ── LEARNING HUB ──
@app.route('/learning-hub')
def learning_hub():
    user = User.query.get(session.get('user_id'))
    if not user:
        return redirect(url_for('login'))
    return render_template('learning-hub.html', user=user, domain_labels=DOMAIN_LABELS, stats={})


@app.route('/api/learning-hub/subjects', methods=['POST'])
def api_learning_hub_subjects():
    if 'user_id' not in session:
        return jsonify({"error": "Please log in first."}), 401

    data = request.get_json(silent=True) or {}
    domain = (data.get("domain") or "").strip()
    if not domain:
        return jsonify({"error": "Missing domain."}), 400

    regenerate = request.args.get("regenerate") == "1"

    try:
        subjects = _get_or_create_hub_subjects(domain, regenerate=regenerate)
    except RateLimitError:
        return jsonify({"error": "AI is busy right now. Please try again in a moment.", "retry": True}), 429
    except (json.JSONDecodeError, ValueError) as e:
        print("Learning Hub subjects generation error:", e)
        return jsonify({"error": "Couldn't generate subjects right now. Please try again."}), 502

    return jsonify({"subjects": subjects}), 200


@app.route('/api/learning-hub/material', methods=['POST'])
def api_learning_hub_material():
    if 'user_id' not in session:
        return jsonify({"error": "Please log in first."}), 401

    data = request.get_json(silent=True) or {}
    domain = (data.get("domain") or "").strip()
    subject = (data.get("subject") or "").strip()
    if not domain or not subject:
        return jsonify({"error": "Missing domain or subject."}), 400

    regenerate = request.args.get("regenerate") == "1"

    try:
        material = _get_or_create_hub_material(domain, subject, regenerate=regenerate)
    except RateLimitError:
        return jsonify({"error": "AI is busy right now. Please try again in a moment.", "retry": True}), 429
    except (json.JSONDecodeError, ValueError) as e:
        print("Learning Hub material generation error:", e)
        return jsonify({"error": "Couldn't generate study material right now. Please try again."}), 502

    return jsonify(material), 200


_EMBED_CHECK_CACHE = {}  # {url: (embeddable: bool, checked_at: datetime)} — simple in-process cache
_EMBED_CHECK_TTL = timedelta(hours=6)


@app.route('/api/learning-hub/check-embed')
def api_learning_hub_check_embed():
    """
    The resource-preview modal calls this before it puts a URL in an
    <iframe>: most sites (YouTube, docs.python.org, etc.) send
    X-Frame-Options / a frame-ancestors CSP that blocks iframing outright,
    which would otherwise just show a blank/broken frame with no
    explanation. This checks those headers server-side (fetching them
    client-side isn't possible — that's exactly the cross-origin request
    the browser would block) and tells the frontend whether to render the
    iframe or fall back to "Open in new tab".
    """
    if 'user_id' not in session:
        return jsonify({"error": "Please log in first."}), 401

    url = (request.args.get('url') or '').strip()
    if not url or not url.lower().startswith(('http://', 'https://')):
        return jsonify({"error": "Missing or invalid url."}), 400

    cached = _EMBED_CHECK_CACHE.get(url)
    if cached and datetime.utcnow() - cached[1] < _EMBED_CHECK_TTL:
        return jsonify({"embeddable": cached[0]}), 200

    embeddable = True
    try:
        resp = requests.head(url, timeout=5, allow_redirects=True)
        # Some servers don't implement HEAD properly (405/empty headers) —
        # fall back to a lightweight GET in that case.
        if resp.status_code >= 400 or not resp.headers:
            resp = requests.get(url, timeout=5, allow_redirects=True, stream=True)
            resp.close()

        xfo = (resp.headers.get('X-Frame-Options') or '').strip().upper()
        csp = (resp.headers.get('Content-Security-Policy') or '').lower()

        if xfo in ('DENY', 'SAMEORIGIN'):
            embeddable = False
        elif 'frame-ancestors' in csp and "'none'" in csp.split('frame-ancestors', 1)[1].split(';')[0]:
            embeddable = False
        elif 'frame-ancestors' in csp and "'self'" in csp.split('frame-ancestors', 1)[1].split(';')[0] \
                and 'frame-ancestors *' not in csp:
            embeddable = False
    except requests.exceptions.RequestException as e:
        # Can't reach it to check headers — safest default is to let the
        # iframe try and let its own onerror/blank state be the fallback,
        # but a request-level failure (DNS, timeout, refused) usually
        # means the iframe would fail too, so treat as not embeddable.
        print("check-embed request failed for", url, ":", e)
        embeddable = False

    _EMBED_CHECK_CACHE[url] = (embeddable, datetime.utcnow())
    return jsonify({"embeddable": embeddable}), 200


# ── CODING ARENA ──
@app.route('/coding-arena')
def coding_arena():
    user = User.query.get(session.get('user_id'))
    if not user:
        return redirect(url_for('login'))

    solved = (db.session.query(CodingSubmission.problem_title)
              .filter_by(user_id=user.id, verdict="Accepted")
              .distinct().count())
    submissions = CodingSubmission.query.filter_by(user_id=user.id).count()

    return render_template(
        'coding-arena.html', user=user,
        category_labels=CODING_CATEGORIES,
        languages=list_supported_languages(),
        stats={"solved": solved, "submissions": submissions},
    )


@app.route('/api/coding-arena/problems', methods=['POST'])
def api_coding_arena_problems():
    if 'user_id' not in session:
        return jsonify({"error": "Please log in first."}), 401

    data = request.get_json(silent=True) or {}
    category = (data.get("category") or "").strip()
    if not category:
        return jsonify({"error": "Missing category."}), 400

    regenerate = request.args.get("regenerate") == "1"

    try:
        problems = _get_or_create_coding_problems(category, regenerate=regenerate)
    except RateLimitError:
        return jsonify({"error": "AI is busy right now. Please try again in a moment.", "retry": True}), 429
    except (json.JSONDecodeError, ValueError) as e:
        print("Coding Arena problems generation error:", e)
        return jsonify({"error": "Couldn't generate problems right now. Please try again."}), 502

    solved_titles = {
        r.problem_title for r in
        CodingSubmission.query.filter_by(user_id=session['user_id'], category=category, verdict="Accepted").all()
    }
    for p in problems:
        p['solved'] = p.get('title') in solved_titles

    return jsonify({"problems": problems}), 200


@app.route('/api/coding-arena/problem', methods=['POST'])
def api_coding_arena_problem():
    if 'user_id' not in session:
        return jsonify({"error": "Please log in first."}), 401

    data = request.get_json(silent=True) or {}
    category = (data.get("category") or "").strip()
    title = (data.get("title") or "").strip()
    if not category or not title:
        return jsonify({"error": "Missing category or title."}), 400

    regenerate = request.args.get("regenerate") == "1"

    try:
        problem = _get_or_create_coding_problem_detail(category, title, regenerate=regenerate)
    except RateLimitError:
        return jsonify({"error": "AI is busy right now. Please try again in a moment.", "retry": True}), 429
    except (json.JSONDecodeError, ValueError) as e:
        print("Coding Arena problem detail generation error:", e)
        return jsonify({"error": "Couldn't generate this problem right now. Please try again."}), 502

    return jsonify(problem), 200


@app.route('/api/coding-arena/run', methods=['POST'])
def api_coding_arena_run():
    """Quick feedback only — runs against the sample cases (or a custom
    stdin override), never saved as a submission."""
    if 'user_id' not in session:
        return jsonify({"error": "Please log in first."}), 401

    data = request.get_json(silent=True) or {}
    category = (data.get("category") or "").strip()
    title = (data.get("title") or "").strip()
    language = (data.get("language") or "").strip()
    code = data.get("code") or ""
    stdin_override = data.get("stdin")

    if not language or not code:
        return jsonify({"error": "Missing language or code."}), 400

    try:
        if stdin_override is not None:
            result = run_code(language, code, stdin_override)
            return jsonify({"mode": "custom", "result": result}), 200

        if not category or not title:
            return jsonify({"error": "Missing category or title."}), 400
        problem = CodingProblem.query.filter_by(category=category, title=title).first()
        if not problem:
            return jsonify({"error": "Problem not found. Open it first."}), 404

        examples = json.loads(problem.examples_json or "[]")
        if not examples:
            return jsonify({"error": "No sample cases for this problem."}), 400

        results = []
        for ex in examples:
            r = run_code(language, code, ex.get("input", ""))
            passed = r["stdout"].strip() == (ex.get("output") or "").strip()
            results.append({
                "input": ex.get("input", ""), "expected": ex.get("output", ""),
                "stdout": r["stdout"], "stderr": r["stderr"], "passed": passed,
            })
        return jsonify({"mode": "samples", "results": results}), 200

    except PistonError as e:
        print("Piston run error:", e)
        return jsonify({"error": "Code execution service is unavailable right now. Please try again."}), 502


@app.route('/api/coding-arena/submit', methods=['POST'])
def api_coding_arena_submit():
    """Runs against ALL test cases (hidden ones included), saves a
    submission row, and returns a verdict — stops at the first failing
    case (like most real judges) rather than running everything."""
    if 'user_id' not in session:
        return jsonify({"error": "Please log in first."}), 401

    data = request.get_json(silent=True) or {}
    category = (data.get("category") or "").strip()
    title = (data.get("title") or "").strip()
    language = (data.get("language") or "").strip()
    code = data.get("code") or ""

    if not category or not title or not language or not code:
        return jsonify({"error": "Missing category, title, language or code."}), 400

    test_cases = _get_coding_test_cases(category, title)
    if not test_cases:
        return jsonify({"error": "This problem has no test cases yet. Open it first."}), 404

    passed = 0
    verdict = "Accepted"
    failure = None

    try:
        for tc in test_cases:
            r = run_code(language, code, tc.get("input", ""))
            if r["compile_error"]:
                verdict = "Compile Error"
                failure = {"stderr": r["stderr"]}
                break
            if r["exit_code"] not in (0, None):
                verdict = "Runtime Error"
                failure = {"stderr": r["stderr"], "input": tc.get("input", "")}
                break
            if r["stdout"].strip() != (tc.get("output") or "").strip():
                verdict = "Wrong Answer"
                failure = {
                    "input": tc.get("input", ""), "expected": tc.get("output", ""),
                    "stdout": r["stdout"],
                }
                break
            passed += 1
    except PistonError as e:
        print("Piston submit error:", e)
        return jsonify({"error": "Code execution service is unavailable right now. Please try again."}), 502

    submission = CodingSubmission(
        user_id=session['user_id'], category=category, problem_title=title,
        language=language, code=code, verdict=verdict,
        passed_count=passed, total_count=len(test_cases),
    )
    db.session.add(submission)
    db.session.commit()

    return jsonify({
        "verdict": verdict, "passed": passed, "total": len(test_cases), "failure": failure,
    }), 200


with app.app_context():
    db.create_all()

if __name__ == '__main__':
    app.run(host="0.0.0.0", debug=True)
