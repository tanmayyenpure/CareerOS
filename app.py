from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify, send_from_directory
from flask_sqlalchemy import SQLAlchemy
from flask_mail import Mail, Message
from werkzeug.security import generate_password_hash, check_password_hash
import random
import os
import json
import time
import traceback
import zipfile
import hmac
import hashlib
import secrets
from datetime import datetime, timedelta

import razorpay
from plans import PLANS, VALID_PLAN_IDS, VALID_CYCLES, get_amount_paise

from openai import OpenAI
from google import genai
from google.genai import types
from werkzeug.utils import secure_filename
import requests

# Tesseract OCR is a separate program pytesseract shells out to — point it
# at the install location explicitly so this doesn't depend on PATH being
# set correctly. Adjust this path if you installed it somewhere else.
try:
    import pytesseract
    _TESSERACT_PATH = os.getenv("TESSERACT_CMD")
    if not _TESSERACT_PATH:
        if os.name == "nt":
            _default_win = r"C:\Program Files\Tesseract-OCR\tesseract.exe"
            if os.path.isfile(_default_win):
                _TESSERACT_PATH = _default_win
        else:
            if os.path.isfile("/usr/bin/tesseract"):
                _TESSERACT_PATH = "/usr/bin/tesseract"
    if _TESSERACT_PATH:
        pytesseract.pytesseract.tesseract_cmd = _TESSERACT_PATH
except ImportError:
    pass

# ── RESUME TEXT EXTRACTION (used by /resume-analyzer/analyze) ──
RESUME_ALLOWED_EXTENSIONS = {'pdf', 'docx', 'txt'}


def ocr_pdf_text(filepath, max_pages=5):
    """
    Fallback for PDFs where pdfplumber can't pull any text out directly
    (scanned/image-only PDFs, or PDFs with unmapped text encoding).
    Renders each page to an image via pdfplumber (which uses pypdfium2 under
    the hood, already a pdfplumber dependency — no Poppler needed) and runs
    Tesseract OCR on the pixels.

    Requires the `pytesseract` pip package AND the Tesseract OCR *program*
    installed separately at the OS level (pip alone can't provide this).
    Returns "" (not an error) if OCR isn't available or finds nothing, so
    the caller falls back to the normal "no text layer" message.
    """
    try:
        import pytesseract
        import pdfplumber
    except ImportError:
        print("Resume OCR: pytesseract not installed, skipping OCR fallback")
        return ""

    text_parts = []
    try:
        with pdfplumber.open(filepath) as pdf:
            for page in pdf.pages[:max_pages]:
                try:
                    image = page.to_image(resolution=200).original
                    page_text = pytesseract.image_to_string(image)
                    if page_text and page_text.strip():
                        text_parts.append(page_text.strip())
                except Exception:
                    print(f"Resume OCR: failed to OCR one page of {filepath}")
                    traceback.print_exc()
    except pytesseract.pytesseract.TesseractNotFoundError:
        print("Resume OCR: Tesseract is not installed on this machine "
              "(pytesseract is installed, but the Tesseract program isn't on PATH)")
        return ""
    except Exception:
        print(f"Resume OCR: unexpected error opening {filepath} for OCR")
        traceback.print_exc()
        return ""

    return "\n".join(text_parts).strip()


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
                # pdfplumber ran fine but found no embedded/extractable text.
                # This covers two cases: a genuinely scanned/image-only PDF,
                # and PDFs (e.g. some Canva/design-tool exports) that have
                # visible text but no proper Unicode text map, so pdfplumber
                # can't pull characters out even though nothing was scanned.
                # OCR handles both, since it reads the rendered pixels
                # instead of relying on the PDF's internal text layer.
                print(f"Resume text extraction: no text layer in {filepath}, "
                      f"falling back to OCR")
                ocr_text = ocr_pdf_text(filepath)
                if ocr_text:
                    return ocr_text, None
                print(f"Resume text extraction: OCR found no text either in {filepath}")
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


UPLOAD_FOLDER = os.getenv("UPLOAD_FOLDER") or (
    "/tmp/uploads/resumes" if os.getenv("VERCEL") == "1" else os.path.join("static", "uploads", "resumes")
)
try:
    os.makedirs(UPLOAD_FOLDER, exist_ok=True)
except OSError:
    pass
from config import Config, is_production
from youtube_helper import enrich_milestones_with_videos, enrich_with_video
from piston_helper import run_code, list_supported_languages, PistonError
from resume_ml.analyzer import MLResumeAnalyzer

print("CWD:", os.getcwd())
print("OPENROUTER_API_KEY found:", bool(Config.OPENROUTER_API_KEY))
print("GEMINI_API_KEY found:", bool(Config.GEMINI_API_KEY))

# ── CREATE APP FIRST ──
app = Flask(__name__)
app.config.from_object(Config)

db = SQLAlchemy(app)
mail = Mail(app)

# ── OPENROUTER (CARA CHAT) CONFIG ──
OPENROUTER_API_KEY = app.config.get('OPENROUTER_API_KEY')
client = None
if OPENROUTER_API_KEY:
    try:
        client = OpenAI(
            base_url="https://openrouter.ai/api/v1",
            api_key=OPENROUTER_API_KEY,
        )
    except Exception as exc:
        # Optional AI credentials must not prevent Flask from starting.
        print(f"OpenRouter client unavailable ({type(exc).__name__}); AI chat is disabled")

# ── GEMINI (ROADMAP GENERATION) CONFIG ──
GEMINI_API_KEY = app.config.get('GEMINI_API_KEY')
gemini_client = None
if GEMINI_API_KEY:
    try:
        gemini_client = genai.Client(api_key=GEMINI_API_KEY)
    except Exception as exc:
        print(f"Gemini client unavailable ({type(exc).__name__}); Gemini features are disabled")

# ── ML RESUME ANALYZER (trained scikit-learn model, no LLM) ──
try:
    ml_resume_analyzer = MLResumeAnalyzer()
except Exception as e:
    ml_resume_analyzer = None
    print(f"ML resume analyzer not loaded: {e}")

# ── RAZORPAY (PRICING / UPGRADES) CONFIG ──
RAZORPAY_KEY_ID = app.config.get('RAZORPAY_KEY_ID')
RAZORPAY_KEY_SECRET = app.config.get('RAZORPAY_KEY_SECRET')
RAZORPAY_WEBHOOK_SECRET = app.config.get('RAZORPAY_WEBHOOK_SECRET')
razorpay_client = None
if RAZORPAY_KEY_ID and RAZORPAY_KEY_SECRET:
    razorpay_client = razorpay.Client(auth=(RAZORPAY_KEY_ID, RAZORPAY_KEY_SECRET))
else:
    print("Razorpay not configured — set RAZORPAY_KEY_ID / RAZORPAY_KEY_SECRET in .env to enable payments")

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

    # plan/payments — 'free' | 'pro' | 'team'. is_pro is kept in sync
    # (True whenever plan is 'pro' or 'team') so the existing chat-limit
    # check above keeps working unchanged.
    plan = db.Column(db.String(20), default='free')
    billing_cycle = db.Column(db.String(10))  # 'monthly' | 'yearly', None for free
    razorpay_customer_id = db.Column(db.String(64))

    # profile fields
    phone = db.Column(db.String(30))
    location = db.Column(db.String(120))
    linkedin = db.Column(db.String(255))
    github = db.Column(db.String(255))
    resume_filename = db.Column(db.String(255))
    resume_score = db.Column(db.Integer)

    # notification preferences — gate which categories _create_notification()
    # actually persists for this user. Both default to on so existing users
    # see no behavior change until they opt out in Settings.
    notify_career = db.Column(db.Boolean, default=True)
    notify_network = db.Column(db.Boolean, default=True)

    skills = db.relationship('Skill', backref='user', lazy=True)
    education = db.relationship('Education', backref='user', lazy=True)
    experience = db.relationship('Experience', backref='user', lazy=True)

class Skill(db.Model):
    __tablename__ = 'skills'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    name = db.Column(db.String(120))
    level = db.Column(db.String(20))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

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


class Payment(db.Model):
    __tablename__ = 'payments'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)

    plan_id = db.Column(db.String(20), nullable=False)        # pro | team
    billing_cycle = db.Column(db.String(10), nullable=False)  # monthly | yearly
    amount_paise = db.Column(db.Integer, nullable=False)

    razorpay_order_id = db.Column(db.String(64), unique=True, nullable=False)
    razorpay_payment_id = db.Column(db.String(64), unique=True)
    razorpay_signature = db.Column(db.String(128))

    # 'razorpay' for real gateway orders, 'dummy' for the in-house simulated
    # checkout (used automatically when Razorpay isn't configured).
    gateway = db.Column(db.String(20), default='razorpay')
    method = db.Column(db.String(20))            # card | upi | wallet
    transaction_id = db.Column(db.String(64))     # dummy gateway's own txn id
    failure_reason = db.Column(db.String(255))

    status = db.Column(db.String(20), default='created')  # created -> paid | failed
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    verified_at = db.Column(db.DateTime)

    user = db.relationship('User', backref='payments')


class Post(db.Model):
    __tablename__ = 'posts'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    text = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    author = db.relationship('User', backref='posts')
    images = db.relationship('PostImage', backref='post', lazy=True,
                              order_by='PostImage.id', cascade='all, delete-orphan')
    likes = db.relationship('PostLike', backref='post', lazy=True,
                             cascade='all, delete-orphan')
    comments = db.relationship('PostComment', backref='post', lazy=True,
                                order_by='PostComment.created_at', cascade='all, delete-orphan')

class PostImage(db.Model):
    __tablename__ = 'post_images'
    id = db.Column(db.Integer, primary_key=True)
    post_id = db.Column(db.Integer, db.ForeignKey('posts.id'), nullable=False)
    filename = db.Column(db.String(255))

class PostLike(db.Model):
    __tablename__ = 'post_likes'
    id = db.Column(db.Integer, primary_key=True)
    post_id = db.Column(db.Integer, db.ForeignKey('posts.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    __table_args__ = (db.UniqueConstraint('post_id', 'user_id', name='uq_post_like_user'),)

class PostComment(db.Model):
    __tablename__ = 'post_comments'
    id = db.Column(db.Integer, primary_key=True)
    post_id = db.Column(db.Integer, db.ForeignKey('posts.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    text = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    author = db.relationship('User')


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
    # 'signup' (email verification during signup) or 'login' (forgot-password
    # "login with OTP" option). Existing rows/inserts default to 'signup' so
    # nothing about the signup flow changes.
    purpose = db.Column(db.String(20), default='signup')

class PasswordResetToken(db.Model):
    """Backs the forgot-password email: one token identifies the user for
    BOTH links in that email (reset password / log in with OTP). Whichever
    the user uses first invalidates it."""
    __tablename__ = 'password_reset_tokens'
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(120))
    token = db.Column(db.String(64), unique=True)
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

class AssessmentAnswer(db.Model):
    """
    One row per question answered in an assessment attempt. AssessmentResult
    only ever stored the total score, so there was no way to know WHICH
    topics a user was weak on afterward — this table fixes that. question_text
    is snapshotted at answer time (not just a question_id FK) so this stays
    valid even if the question bank is edited or trimmed later, and so the
    roadmap generator can read weak areas as plain text without an extra join.
    """
    __tablename__ = "assessment_answers"
    id = db.Column(db.Integer, primary_key=True)
    result_id = db.Column(db.Integer)   # AssessmentResult.id this belongs to
    user_id = db.Column(db.Integer)
    domain = db.Column(db.String(100))
    question_id = db.Column(db.Integer)
    question_text = db.Column(db.Text)
    is_correct = db.Column(db.Boolean)
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
    topics_json = db.Column(db.Text)     # JSON: [{"title","explanation","notes","resource_video_id",...}, ...]
    resources_json = db.Column(db.Text)  # JSON: [{"label","url"}, ...]
    # Bumped whenever the generation prompt/schema changes (e.g. adding
    # "notes" + video enrichment per topic). Rows written under an older
    # version are treated as stale and silently regenerated on next
    # request instead of being served forever with missing fields.
    schema_version = db.Column(db.Integer, default=1)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    __table_args__ = (
        db.UniqueConstraint('domain', 'subject', name='uq_hub_domain_subject'),
    )


# Bump this any time the fields returned per-topic change shape.
LEARNING_HUB_MATERIAL_SCHEMA_VERSION = 2


class LearningHubActivity(db.Model):
    """
    Logs every time a user successfully pulls up study material in the
    Learning Hub (cache hit or fresh AI generation — either way it's
    material *they* looked at). Powers the "Subjects Explored" (distinct
    domain+subject pairs) and "Study Materials Generated" (row count,
    including revisits) stat tiles on the hero card, which were previously
    always 0 because the route passed `stats={}` with nothing computed.
    """
    __tablename__ = "learning_hub_activity"
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    domain = db.Column(db.String(120), nullable=False)
    subject = db.Column(db.String(200), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


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


class CertificationCourseSet(db.Model):
    """
    Cached AI-generated course catalog for one domain — same caching
    rationale as LearningHubSubjectSet / CodingProblemSet. One row per
    domain, only regenerated if you pass ?regenerate=1.
    """
    __tablename__ = "certification_course_sets"
    id = db.Column(db.Integer, primary_key=True)
    domain = db.Column(db.String(120), unique=True, nullable=False)
    courses_json = db.Column(db.Text)  # JSON: [{"title","level","duration_hours","description","tags":[...]}, ...]
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class CertificationCourse(db.Model):
    """
    Cached AI-generated full course detail (syllabus) for one
    (domain, title) pair — module list with one lecture video enriched
    per module via youtube_helper, same pattern as LearningHubMaterial.
    """
    __tablename__ = "certification_courses"
    id = db.Column(db.Integer, primary_key=True)
    domain = db.Column(db.String(120), nullable=False)
    title = db.Column(db.String(200), nullable=False)
    level = db.Column(db.String(20))
    duration_hours = db.Column(db.Integer)
    description = db.Column(db.Text)
    modules_json = db.Column(db.Text)  # JSON: [{"title","description","resource_video_id",...}, ...]
    schema_version = db.Column(db.Integer, default=1)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    __table_args__ = (
        db.UniqueConstraint('domain', 'title', name='uq_cert_domain_title'),
    )


CERTIFICATION_COURSE_SCHEMA_VERSION = 1


class CertificationQuiz(db.Model):
    """
    Final proctored-style assessment for one course, generated on-demand
    the first time a learner finishes every module. Same
    server-side-answers pattern as MilestoneQuiz — correct_index is
    stripped out before this ever reaches the client.
    """
    __tablename__ = "certification_quizzes"
    id = db.Column(db.Integer, primary_key=True)
    course_id = db.Column(db.Integer, db.ForeignKey('certification_courses.id'), unique=True)
    questions_json = db.Column(db.Text)  # JSON: [{"id","question","options","correct_index"}, ...]
    total_marks = db.Column(db.Integer)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


# Passing threshold for the final certification exam.
CERTIFICATION_PASS_THRESHOLD = 0.7


class CertificationEnrollment(db.Model):
    """
    One row per (user, course) — tracks which module videos a learner has
    marked watched and whether they've cleared the final exam yet.
    """
    __tablename__ = "certification_enrollments"
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    domain = db.Column(db.String(120), nullable=False)
    course_title = db.Column(db.String(200), nullable=False)
    modules_completed_json = db.Column(db.Text, default="[]")  # JSON list of module indices
    status = db.Column(db.String(20), default="in_progress")   # in_progress / completed
    quiz_score = db.Column(db.Integer)
    quiz_total = db.Column(db.Integer)
    quiz_attempts = db.Column(db.Integer, default=0)
    enrolled_at = db.Column(db.DateTime, default=datetime.utcnow)
    completed_at = db.Column(db.DateTime)

    __table_args__ = (
        db.UniqueConstraint('user_id', 'domain', 'course_title', name='uq_cert_enrollment'),
    )


class Certificate(db.Model):
    """
    An issued, downloadable certificate. certificate_code is the public
    verification code embedded on the PDF (e.g. CERT-A1B2C3D4).
    """
    __tablename__ = "certificates"
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    domain = db.Column(db.String(120), nullable=False)
    course_title = db.Column(db.String(200), nullable=False)
    certificate_code = db.Column(db.String(20), unique=True, nullable=False)
    issued_at = db.Column(db.DateTime, default=datetime.utcnow)


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

    # ── live job-board integration (Adzuna) ──
    source = db.Column(db.String(20), default="internal")  # "internal" (seeded) or "adzuna"
    external_id = db.Column(db.String(100), index=True)     # Adzuna's job id, used to upsert on re-sync
    apply_url = db.Column(db.String(1000))                  # real listing URL to redirect to on Apply

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
            "posted_date": self.posted_date.strftime('%Y-%m-%d') if self.posted_date else None,
            "source": self.source or "internal",
            "apply_url": self.apply_url,
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
    match_pct_at_apply = db.Column(db.Integer)  # snapshot of AI match % at the moment they applied
    last_progressed_at = db.Column(db.DateTime, default=datetime.utcnow)  # last time status auto-advanced

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


class Notification(db.Model):
    """
    Career Center activity feed. Created automatically by application/
    interview/save events and by the background application-progress
    simulator (see _advance_user_applications).
    """
    __tablename__ = 'notifications'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    type = db.Column(db.String(30))  # applied, viewed, shortlisted, interview, rejected, offer, tip
    company_name = db.Column(db.String(100))
    company_logo = db.Column(db.String(10))
    message = db.Column(db.Text, nullable=False)
    related_job_id = db.Column(db.Integer, db.ForeignKey('jobs.id'))
    is_read = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def as_dict(self):
        return {
            "id": self.id,
            "type": self.type,
            "company_name": self.company_name,
            "company_logo": self.company_logo,
            "message": self.message,
            "related_job_id": self.related_job_id,
            "is_read": self.is_read,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class InterviewCoachSession(db.Model):
    """One practiced Q&A round in the AI Interview Coach, scored by Gemini."""
    __tablename__ = 'interview_coach_sessions'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    mode = db.Column(db.String(30))  # HR Interview / Technical / Behavioral / System Design / Coding
    question = db.Column(db.Text)
    answer_text = db.Column(db.Text)
    interview_score = db.Column(db.Integer)
    confidence = db.Column(db.Integer)
    communication = db.Column(db.Integer)
    technical_accuracy = db.Column(db.Integer)
    feedback = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def as_dict(self):
        return {
            "id": self.id,
            "mode": self.mode,
            "question": self.question,
            "interview_score": self.interview_score,
            "confidence": self.confidence,
            "communication": self.communication,
            "technical_accuracy": self.technical_accuracy,
            "feedback": self.feedback,
            "created_at": self.created_at.strftime('%d %b, %I:%M %p') if self.created_at else None,
        }


class SkillSnapshot(db.Model):
    """
    Recorded once per profile save (see /profile POST) so the Career
    Analytics 'Skills Growth' chart has real history to plot instead of
    hardcoded numbers.
    """
    __tablename__ = 'skill_snapshots'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    skill_count = db.Column(db.Integer, default=0)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


# ── NETWORKING (connections, invitations, companies) ──────────────────
class ConnectionRequest(db.Model):
    """A pending invitation to connect, sender -> receiver. Deleted once
    accepted (and turned into a Connection row) or declined."""
    __tablename__ = 'connection_requests'
    id = db.Column(db.Integer, primary_key=True)
    sender_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    receiver_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    message = db.Column(db.String(255))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    sender = db.relationship('User', foreign_keys=[sender_id])
    receiver = db.relationship('User', foreign_keys=[receiver_id])

    __table_args__ = (db.UniqueConstraint('sender_id', 'receiver_id', name='uq_connection_request'),)


class Connection(db.Model):
    """
    An accepted connection between two users. Stored once per pair,
    canonicalized so user_id_a < user_id_b — always go through the
    are_connected() / create_connection() / remove_connection() /
    get_connection_ids() helpers below rather than querying this table
    directly, so you don't have to remember the ordering.
    """
    __tablename__ = 'connections'
    id = db.Column(db.Integer, primary_key=True)
    user_id_a = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    user_id_b = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    __table_args__ = (db.UniqueConstraint('user_id_a', 'user_id_b', name='uq_connection_pair'),)


class Company(db.Model):
    __tablename__ = 'companies'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(150), unique=True, nullable=False)
    domain = db.Column(db.String(100))
    industry = db.Column(db.String(150))
    logo_url = db.Column(db.String(255))
    description = db.Column(db.Text)
    website = db.Column(db.String(255))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class CompanyFollow(db.Model):
    __tablename__ = 'company_follows'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    company_id = db.Column(db.Integer, db.ForeignKey('companies.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    __table_args__ = (db.UniqueConstraint('user_id', 'company_id', name='uq_company_follow'),)


def _connection_pair(a, b):
    return (a, b) if a < b else (b, a)


def are_connected(a, b):
    lo, hi = _connection_pair(a, b)
    return Connection.query.filter_by(user_id_a=lo, user_id_b=hi).first() is not None


def create_connection(a, b):
    lo, hi = _connection_pair(a, b)
    if not Connection.query.filter_by(user_id_a=lo, user_id_b=hi).first():
        db.session.add(Connection(user_id_a=lo, user_id_b=hi))


def remove_connection(a, b):
    lo, hi = _connection_pair(a, b)
    Connection.query.filter_by(user_id_a=lo, user_id_b=hi).delete()


def get_connection_ids(user_id):
    """All user ids connected to user_id (in either direction)."""
    rows = Connection.query.filter(
        db.or_(Connection.user_id_a == user_id, Connection.user_id_b == user_id)
    ).all()
    return {r.user_id_b if r.user_id_a == user_id else r.user_id_a for r in rows}


def mutual_connection_count(a, b):
    return len(get_connection_ids(a) & get_connection_ids(b))


def connection_status(viewer_id, target_id):
    """'connected' | 'pending_sent' | 'pending_received' | 'none'"""
    if are_connected(viewer_id, target_id):
        return "connected"
    if ConnectionRequest.query.filter_by(sender_id=viewer_id, receiver_id=target_id).first():
        return "pending_sent"
    if ConnectionRequest.query.filter_by(sender_id=target_id, receiver_id=viewer_id).first():
        return "pending_received"
    return "none"


def _with_display_fields(user):
    """
    Attaches convenience `.role` / `.company` attributes to a User instance
    for the network/company templates. These aren't DB columns — `.role`
    just mirrors target_role, and `.company` is read off the user's most
    recently added Experience entry (profile_setup.html already asks users
    to list experience most-recent-first, so index 0 is the current job).
    Safe no-op extra attributes; doesn't touch the database.
    """
    if user is None:
        return None
    user.role = user.target_role
    user.company = user.experience[0].company if user.experience else None
    return user


def seed_companies_from_jobs():
    """
    One-time backfill: creates a Company row for every distinct company_name
    already sitting in the jobs table, so /companies has real data without
    any manual entry. Safe to call on every startup — skips names that
    already exist. Call once inside `with app.app_context()`, alongside
    db.create_all().
    """
    existing_names = {c.name for c in Company.query.all()}
    seen_in_batch = set()
    for job in Job.query.all():
        name = (job.company_name or "").strip()
        if not name or name in existing_names or name in seen_in_batch:
            continue
        db.session.add(Company(
            name=name,
            domain=job.domain,
            industry=DOMAIN_LABELS.get(job.domain, job.domain or "General"),
            logo_url=job.company_logo,
        ))
        seen_in_batch.add(name)
    if seen_in_batch:
        db.session.commit()


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


# ── LIVE JOB BOARD INTEGRATION (ADZUNA) ──────────────────────────────
# Register a free account at https://developer.adzuna.com/ to get these.
# Add to config.py's Config class (pulled from .env, same pattern as
# OPENROUTER_API_KEY / GEMINI_API_KEY):
#     ADZUNA_APP_ID  = os.environ.get("ADZUNA_APP_ID", "")
#     ADZUNA_APP_KEY = os.environ.get("ADZUNA_APP_KEY", "")
ADZUNA_APP_ID = getattr(Config, "ADZUNA_APP_ID", "") or os.environ.get("ADZUNA_APP_ID", "")
ADZUNA_APP_KEY = getattr(Config, "ADZUNA_APP_KEY", "") or os.environ.get("ADZUNA_APP_KEY", "")
ADZUNA_ENABLED = bool(ADZUNA_APP_ID and ADZUNA_APP_KEY)

# Recognized skill keywords we scan job descriptions for, since Adzuna
# doesn't return a structured skills list the way our seeded jobs do.
KNOWN_SKILL_KEYWORDS = [
    "Python", "Java", "JavaScript", "TypeScript", "C++", "C#", "Go", "Rust", "Ruby",
    "React", "Angular", "Vue", "Node.js", "Django", "Flask", "Spring Boot", ".NET",
    "AWS", "Azure", "GCP", "Docker", "Kubernetes", "Terraform", "Kafka", "gRPC",
    "SQL", "MySQL", "PostgreSQL", "MongoDB", "Redis", "DynamoDB", "Cassandra",
    "CI/CD", "Linux", "Bash", "Git", "System Design", "Microservices",
    "Machine Learning", "PyTorch", "TensorFlow", "LLMs", "NLP", "Data Science",
    "HTML", "CSS", "REST", "GraphQL", "Selenium", "Testing", "Agile",
]

# In-memory cooldown so we don't hammer Adzuna on every /career/jobs call.
# Keyed by (query, location) -> datetime of last sync. Fine for a single
# process; move to Redis/DB if you run multiple workers.
_ADZUNA_LAST_SYNC = {}
ADZUNA_SYNC_COOLDOWN_MINUTES = 30


def _strip_html(text):
    import re
    return re.sub(r"<[^>]+>", " ", text or "").strip()


def _extract_skills_from_text(text):
    text_l = (text or "").lower()
    found = [kw for kw in KNOWN_SKILL_KEYWORDS if kw.lower() in text_l]
    return found[:8] if found else ["Communication", "Problem Solving"]


def _format_inr_salary(min_val, max_val):
    def to_lakhs(v):
        return round(v / 100000, 1)
    if min_val and max_val:
        return f"₹{to_lakhs(min_val):g}L – ₹{to_lakhs(max_val):g}L"
    if min_val:
        return f"₹{to_lakhs(min_val):g}L+"
    return "Not disclosed"


def sync_jobs_from_adzuna(query="software developer", location="India", max_pages=1):
    """
    Pulls live listings from Adzuna's public jobs API (India index) and
    upserts them into our local Job table, matched on external_id so
    re-syncing updates rather than duplicates. Returns the number of
    jobs written. No-ops quietly if ADZUNA_APP_ID/KEY aren't configured,
    so the app degrades gracefully to seeded jobs during local dev.
    """
    if not ADZUNA_ENABLED:
        return 0

    cache_key = (query.lower().strip(), (location or "India").lower().strip())
    last = _ADZUNA_LAST_SYNC.get(cache_key)
    if last and (datetime.utcnow() - last) < timedelta(minutes=ADZUNA_SYNC_COOLDOWN_MINUTES):
        return 0  # synced recently enough, skip the API round-trip

    written = 0
    try:
        for page in range(1, max_pages + 1):
            resp = requests.get(
                f"https://api.adzuna.com/v1/api/jobs/in/search/{page}",
                params={
                    "app_id": ADZUNA_APP_ID,
                    "app_key": ADZUNA_APP_KEY,
                    "results_per_page": 20,
                    "what": query,
                    "where": location or "India",
                    "content-type": "application/json",
                },
                timeout=8,
            )
            resp.raise_for_status()
            results = resp.json().get("results", [])

            for r in results:
                external_id = str(r.get("id"))
                if not external_id:
                    continue

                title = _strip_html(r.get("title"))[:100]
                company_name = _strip_html((r.get("company") or {}).get("display_name"))[:100] or "Unknown"
                loc_name = _strip_html((r.get("location") or {}).get("display_name"))[:100] or (location or "India")
                description = _strip_html(r.get("description"))[:2000]
                contract_time = (r.get("contract_time") or "").lower()
                contract_type = (r.get("contract_type") or "").lower()
                job_type = "Remote" if "remote" in (title + description).lower() else (
                    "Contract" if contract_type == "contract" else
                    "Part-time" if contract_time == "part_time" else "Onsite"
                )
                category_label = (r.get("category") or {}).get("label", "") or "Engineering & Technology"

                job = Job.query.filter_by(external_id=external_id, source="adzuna").first()
                if not job:
                    job = Job(external_id=external_id, source="adzuna")
                    db.session.add(job)

                job.company_name = company_name
                job.job_title = title or "Untitled Role"
                job.location = loc_name
                job.job_type = job_type
                job.experience = job.experience or "Not specified"
                job.salary = _format_inr_salary(r.get("salary_min"), r.get("salary_max"))
                job.description = description
                job.skills_required = ", ".join(_extract_skills_from_text(title + " " + description))
                job.company_logo = (company_name[:1] or "?").upper()
                job.domain = category_label
                job.apply_url = r.get("redirect_url")
                try:
                    job.posted_date = datetime.strptime(r.get("created", "")[:19], "%Y-%m-%dT%H:%M:%S")
                except (ValueError, TypeError):
                    job.posted_date = datetime.utcnow()

                written += 1

            if len(results) < 20:
                break  # last page

        db.session.commit()
        _ADZUNA_LAST_SYNC[cache_key] = datetime.utcnow()
    except requests.RequestException as e:
        print("Adzuna sync error:", e)
        db.session.rollback()

    return written


# ── NOTIFICATIONS ─────────────────────────────────────────────────────
# Which preference column on User gates each notification type. Anything
# not listed here (e.g. a future type) defaults to "career" so it's still
# controlled by a toggle rather than being unconditionally on.
NETWORK_NOTIFICATION_TYPES = {"connection_request", "connection_accepted"}


def _create_notification(user_id, ntype, message, company_name=None, company_logo=None, related_job_id=None):
    """Creates a Notification row, unless the user has turned off the
    category this type belongs to (Settings > Notifications). Returns the
    Notification on success, or None if it was skipped by preference —
    callers don't use the return value today, so this is safe either way."""
    user = User.query.get(user_id)
    if user is not None:
        is_network = ntype in NETWORK_NOTIFICATION_TYPES
        if is_network and user.notify_network is False:
            return None
        if not is_network and user.notify_career is False:
            return None

    note = Notification(
        user_id=user_id, type=ntype, message=message,
        company_name=company_name, company_logo=company_logo,
        related_job_id=related_job_id,
    )
    db.session.add(note)
    return note


# ── APPLICATION PROGRESS SIMULATION ───────────────────────────────────
# There's no real recruiter/employer portal behind this app, so a status
# would otherwise sit on "Applied" forever. To make the tracker and
# notifications feel alive (closer to how naukri.com surfaces recruiter
# activity), we deterministically advance each application's status a
# step at a time as real time passes, seeded on the application's own id
# so the same application always progresses the same way rather than
# re-rolling randomly on every page load.
APPLICATION_STAGES = ["Applied", "Screening", "Shortlisted", "Interview", "Offer"]
STAGE_ADVANCE_HOURS = 20  # roughly one stage every ~20 real hours


def _advance_user_applications(user):
    """Call this whenever a user loads the Career Center / applications
    list. Advances any application whose next stage is 'due', creates a
    Notification + (when entering Interview) an Interview row for it."""
    apps = Application.query.filter_by(user_id=user.id).all()
    now = datetime.utcnow()

    for a in apps:
        if a.status in ("Rejected", "Joined"):
            continue
        try:
            current_idx = APPLICATION_STAGES.index(a.status)
        except ValueError:
            continue  # already a terminal/custom status, leave it alone

        hours_since = (now - (a.last_progressed_at or a.applied_date)).total_seconds() / 3600
        if hours_since < STAGE_ADVANCE_HOURS:
            continue

        # Deterministic per-application "roll" so behaviour is stable.
        roll = (a.id * 2654435761) % 100

        if current_idx == len(APPLICATION_STAGES) - 1:
            continue  # already at Offer, only /career/offer-response (future) would move it further

        # 15% chance an application gets rejected at Screening/Shortlisted
        # instead of advancing further, so the tracker isn't unrealistically
        # rosy.
        if current_idx in (1, 2) and roll < 15:
            a.status = "Rejected"
            a.last_progressed_at = now
            _create_notification(
                user.id, "rejected",
                f"{a.job.company_name} marked your application for {a.job.job_title} as not selected this round.",
                company_name=a.job.company_name, company_logo=a.job.company_logo, related_job_id=a.job_id,
            )
            continue

        next_status = APPLICATION_STAGES[current_idx + 1]
        a.status = next_status
        a.last_progressed_at = now

        if next_status == "Screening":
            msg = f"{a.job.company_name} viewed your application for {a.job.job_title}."
        elif next_status == "Shortlisted":
            msg = f"{a.job.company_name} shortlisted you for {a.job.job_title}."
        elif next_status == "Interview":
            msg = f"{a.job.company_name} scheduled an interview for {a.job.job_title}."
            interview_dt = now + timedelta(days=2, hours=(roll % 6))
            db.session.add(Interview(
                user_id=user.id, application_id=a.id,
                company_name=a.job.company_name, job_title=a.job.job_title,
                interview_date=interview_dt, status="Scheduled",
                round_name="Technical Round" if roll % 2 == 0 else "HR Discussion",
            ))
        elif next_status == "Offer":
            msg = f"Congratulations! {a.job.company_name} extended an offer for {a.job.job_title}."
        else:
            msg = f"{a.job.company_name} updated your application status to {next_status}."

        _create_notification(
            user.id, next_status.lower(), msg,
            company_name=a.job.company_name, company_logo=a.job.company_logo, related_job_id=a.job_id,
        )

    if db.session.dirty or db.session.new:
        db.session.commit()



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
    is_current_schema = existing and existing.schema_version == LEARNING_HUB_MATERIAL_SCHEMA_VERSION
    if existing and is_current_schema and not regenerate:
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
     explanation -- specific facts, steps, or things worth remembering.
     This field is REQUIRED and must never be an empty list.
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
        # Gemini occasionally drops "notes" despite the prompt — never
        # leave a topic with nothing to read under it.
        notes = topic.get("notes")
        if not notes:
            fallback = (topic.get("explanation") or "").strip()
            topic["notes"] = [fallback] if fallback else ["No additional notes available for this topic."]

        try:
            enrich_with_video(topic)
        except Exception as e:
            print(f"Learning Hub topic video lookup failed for {topic.get('title')!r}: {e}")

    if existing:
        existing.overview = overview
        existing.topics_json = json.dumps(topics)
        existing.resources_json = json.dumps(resources)
        existing.schema_version = LEARNING_HUB_MATERIAL_SCHEMA_VERSION
        existing.created_at = datetime.utcnow()
    else:
        existing = LearningHubMaterial(
            domain=domain, subject=subject,
            overview=overview,
            topics_json=json.dumps(topics),
            resources_json=json.dumps(resources),
            schema_version=LEARNING_HUB_MATERIAL_SCHEMA_VERSION,
        )
        db.session.add(existing)
    db.session.commit()
    return {"overview": overview, "topics": topics, "resources": resources}


def _get_or_create_cert_courses(domain, regenerate=False):
    existing = CertificationCourseSet.query.filter_by(domain=domain).first()
    if existing and not regenerate:
        return json.loads(existing.courses_json)

    prompt = f'''You are building a Coursera-style certified course catalog
for Indian students and job-seekers.

Domain: "{domain}"

Return 6 to 8 short certification courses that fall under this domain in
the Indian education/career context. For each course give:
- "title": a specific, marketable course title (e.g. "Full-Stack Web Development with React & Node")
- "level": one of "Beginner", "Intermediate", "Advanced"
- "duration_hours": a realistic total study hours estimate (integer, 4-30)
- "description": 1-2 sentence description of what the learner will be able to do after finishing
- "tags": 2-3 short tag words (skills covered)

Respond with ONLY raw JSON, no markdown fences, no commentary, in exactly
this shape:

{{
  "courses": [
    {{
      "title": "...",
      "level": "Beginner",
      "duration_hours": 10,
      "description": "...",
      "tags": ["...", "..."]
    }}
  ]
}}
'''
    data = _call_gemini_json(prompt)
    courses = data.get("courses", [])
    if not isinstance(courses, list) or not courses:
        raise ValueError("Gemini returned no courses")

    if existing:
        existing.courses_json = json.dumps(courses)
        existing.created_at = datetime.utcnow()
    else:
        existing = CertificationCourseSet(domain=domain, courses_json=json.dumps(courses))
        db.session.add(existing)
    db.session.commit()
    return courses


def _get_or_create_cert_course(domain, title, regenerate=False):
    existing = CertificationCourse.query.filter_by(domain=domain, title=title).first()
    is_current_schema = existing and existing.schema_version == CERTIFICATION_COURSE_SCHEMA_VERSION
    if existing and is_current_schema and not regenerate:
        return existing

    prompt = f'''You are building the syllabus for a certified online course
titled "{title}" (an Indian learner audience), within the "{domain}" domain.

Return:
1. "level": one of "Beginner", "Intermediate", "Advanced"
2. "duration_hours": realistic total study hours (integer, 4-30)
3. "description": 2-3 sentence course description
4. 5 to 8 modules/lectures that build on each other. For each module give:
   - "title": short module/lecture title
   - "description": 1-2 sentence plain-English explanation of what this module covers
   - "search_keywords": 2-4 words that would find a real, relevant tutorial
     video on YouTube for this specific module

Respond with ONLY raw JSON, no markdown fences, no commentary, in exactly
this shape:

{{
  "level": "Beginner",
  "duration_hours": 10,
  "description": "...",
  "modules": [
    {{
      "title": "...",
      "description": "...",
      "search_keywords": ["...", "..."]
    }}
  ]
}}
'''
    data = _call_gemini_json(prompt)
    level = data.get("level", "Beginner")
    duration_hours = data.get("duration_hours", 8)
    description = data.get("description", "")
    modules = data.get("modules", [])
    if not isinstance(modules, list) or not modules:
        raise ValueError("Gemini returned no modules")

    for module in modules:
        try:
            enrich_with_video(module)
        except Exception as e:
            print(f"Certification module video lookup failed for {module.get('title')!r}: {e}")

    if existing:
        existing.level = level
        existing.duration_hours = duration_hours
        existing.description = description
        existing.modules_json = json.dumps(modules)
        existing.schema_version = CERTIFICATION_COURSE_SCHEMA_VERSION
        existing.created_at = datetime.utcnow()
    else:
        existing = CertificationCourse(
            domain=domain, title=title, level=level, duration_hours=duration_hours,
            description=description, modules_json=json.dumps(modules),
            schema_version=CERTIFICATION_COURSE_SCHEMA_VERSION,
        )
        db.session.add(existing)
    db.session.commit()
    return existing


def _get_or_create_cert_quiz(course, regenerate=False):
    existing = CertificationQuiz.query.filter_by(course_id=course.id).first()
    if existing and not regenerate:
        return existing

    modules = json.loads(course.modules_json or "[]")
    module_titles = "; ".join(m.get("title", "") for m in modules)

    prompt = f'''You are writing the final certification exam for the course
"{course.title}" ({course.level} level). The course covered these modules:
{module_titles}

Write 8 multiple-choice questions that fairly test understanding across
these modules. Each question has exactly 4 options and one correct answer.

Respond with ONLY raw JSON, no markdown fences, no commentary, in exactly
this shape:

{{
  "questions": [
    {{
      "id": "q1",
      "question": "...",
      "options": ["...", "...", "...", "..."],
      "correct_index": 0
    }}
  ]
}}
'''
    data = _call_gemini_json(prompt)
    questions = data.get("questions", [])
    if not isinstance(questions, list) or not questions:
        raise ValueError("Gemini returned no exam questions")
    for i, q in enumerate(questions):
        q["id"] = q.get("id") or f"q{i+1}"

    if existing:
        existing.questions_json = json.dumps(questions)
        existing.total_marks = len(questions)
        existing.created_at = datetime.utcnow()
    else:
        existing = CertificationQuiz(
            course_id=course.id, questions_json=json.dumps(questions), total_marks=len(questions),
        )
        db.session.add(existing)
    db.session.commit()
    return existing


def _generate_certificate_code():
    import secrets
    while True:
        code = "CERT-" + secrets.token_hex(4).upper()
        if not Certificate.query.filter_by(certificate_code=code).first():
            return code


CERTIFICATE_TEMPLATE_PATH = os.path.join('static', 'certificates', 'certificate_template.pdf')


def _render_certificate_pdf(user, course_title, domain, certificate_code, issued_at):
    """
    Overlays the learner's name, course title, and issue date onto the
    CareerOS certificate template PDF (static/certificates/certificate_template.pdf)
    and returns the merged PDF as bytes. The template's background art, gold
    seal, and "Founder, CareerOS" signature line are left untouched — only
    the three dynamic fields plus a small verification-code footer are drawn
    on top.
    """
    from io import BytesIO
    from pypdf import PdfReader, PdfWriter
    from reportlab.lib.colors import HexColor
    from reportlab.pdfgen import canvas as pdfcanvas

    reader = PdfReader(CERTIFICATE_TEMPLATE_PATH)
    template_page = reader.pages[0]
    page_w = float(template_page.mediabox.width)
    page_h = float(template_page.mediabox.height)

    buf = BytesIO()
    c = pdfcanvas.Canvas(buf, pagesize=(page_w, page_h))

    cyan = HexColor("#37D6F0")
    white = HexColor("#EAF6FB")
    muted = HexColor("#9fd3e0")
    center_x = page_w / 2

    # ── Learner name (fills the "[LEARNER NAME]" placeholder) ──
    name = user.name or "CareerOS Learner"
    name_font_size = 26
    c.setFont("Helvetica-Bold", name_font_size)
    while c.stringWidth(name, "Helvetica-Bold", name_font_size) > 380 and name_font_size > 14:
        name_font_size -= 1
        c.setFont("Helvetica-Bold", name_font_size)
    c.setFillColor(cyan)
    c.drawCentredString(center_x, page_h - 245.9 + 7, name)

    # ── Course title (fills the "course: [Course Name]" placeholder) ──
    c.setFont("Helvetica-Bold", 15)
    c.setFillColor(white)
    max_w = 560
    if c.stringWidth(course_title, "Helvetica-Bold", 15) > max_w:
        words = course_title.split()
        line1, line2 = "", ""
        for w in words:
            trial = (line1 + " " + w).strip()
            if c.stringWidth(trial, "Helvetica-Bold", 15) <= max_w:
                line1 = trial
            else:
                line2 = (line2 + " " + w).strip()
        c.drawCentredString(center_x, page_h - 326.7 + 4 + 9, line1)
        c.drawCentredString(center_x, page_h - 326.7 + 4 - 9, line2)
    else:
        c.drawCentredString(center_x, page_h - 326.7 + 4, course_title)

    # ── Issued date (fills the "[Date]" placeholder) ──
    # Placeholder text box measured directly from the template PDF via pdfplumber:
    #   "[Date]"  x0=593.7  x1=630.8  top=435.7  bottom=447.4  (top-down coords)
    date_box_x0, date_box_x1 = 593.7, 630.8
    date_box_top, date_box_bottom = 435.7, 447.4  # top-down (measured from page top)

    # cover the literal "[Date]" placeholder text with the template's background
    # color before drawing the real date over it, so the placeholder text
    # doesn't show through underneath the new value
    cover_pad = 8
    cover_x0 = date_box_x0 - cover_pad
    cover_x1 = date_box_x1 + cover_pad
    cover_y_bottom = (page_h - date_box_bottom) - 3
    cover_y_top = (page_h - date_box_top) + 3
    c.setFillColor(HexColor("#090E20"))
    c.rect(cover_x0, cover_y_bottom, cover_x1 - cover_x0, cover_y_top - cover_y_bottom, stroke=0, fill=1)

    c.setFont("Helvetica-Bold", 11)
    c.setFillColor(white)
    date_center_x = (date_box_x0 + date_box_x1) / 2
    date_baseline_y = (page_h - date_box_bottom) + 2  # baseline ≈ bottom of glyphs + small descender offset
    c.drawCentredString(date_center_x, date_baseline_y, issued_at.strftime("%d %b %Y"))

    # ── Verification code footer ──
    c.setFont("Helvetica", 9)
    c.setFillColor(muted)
    c.drawCentredString(center_x, 18, f"Verification Code: {certificate_code}")

    c.showPage()
    c.save()
    buf.seek(0)

    overlay_reader = PdfReader(buf)
    writer = PdfWriter()
    template_page.merge_page(overlay_reader.pages[0])
    writer.add_page(template_page)

    out = BytesIO()
    writer.write(out)
    return out.getvalue()


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
    """Send a signup OTP and persist it only after the mail server accepts it."""
    mail_username = app.config.get('MAIL_USERNAME')
    mail_password = app.config.get('MAIL_PASSWORD')
    sender = app.config.get('MAIL_DEFAULT_SENDER') or mail_username
    missing = [
        name for name, value in (
            ('MAIL_USERNAME', mail_username),
            ('MAIL_PASSWORD', mail_password),
            ('MAIL_DEFAULT_SENDER or MAIL_USERNAME', sender),
        ) if not value
    ]
    if missing:
        app.logger.error(
            "OTP email is not configured; missing Vercel environment variable(s): %s",
            ', '.join(missing),
        )
        return False

    otp_code = str(random.randint(100000, 999999))
    expires_at = datetime.utcnow() + timedelta(minutes=10)
    msg = Message(
        'Your CareerOS verification code',
        sender=sender,
        recipients=[email],
    )
    msg.body = f'Your OTP code is: {otp_code}\nThis code expires in 10 minutes.'

    try:
        # SMTP delivery is synchronous; wait for the provider before returning
        # from the serverless request so the message is not cut off afterward.
        mail.send(msg)
    except Exception as exc:
        app.logger.error("OTP email delivery failed (%s)", type(exc).__name__)
        return False

    OTPVerification.query.filter_by(email=email).delete()
    db.session.add(OTPVerification(
        email=email,
        otp_code=otp_code,
        expires_at=expires_at,
    ))
    db.session.commit()
    return True


# ── HELPER FUNCTIONS: FORGOT PASSWORD (reset link + login-via-OTP) ──
RESET_TOKEN_TTL_MINUTES = 15


def _generate_and_send_password_reset(user):
    """Creates a reset token + a separate 6-digit OTP for `user`, and emails
    both in one message. The reset link and the OTP link are keyed off the
    same token so either one can be opened straight from the email without
    needing an existing session (e.g. opened on a different device)."""
    email = user.email
    now = datetime.utcnow()
    expires_at = now + timedelta(minutes=RESET_TOKEN_TTL_MINUTES)

    # One token per email at a time — clear any older, unused ones.
    PasswordResetToken.query.filter_by(email=email).delete()
    OTPVerification.query.filter_by(email=email, purpose='login').delete()

    token = secrets.token_urlsafe(32)
    otp_code = str(random.randint(100000, 999999))

    db.session.add(PasswordResetToken(email=email, token=token, expires_at=expires_at))
    db.session.add(OTPVerification(email=email, otp_code=otp_code, expires_at=expires_at, purpose='login'))
    db.session.commit()

    reset_url = url_for('reset_password', token=token, _external=True)
    otp_url = url_for('login_otp', token=token, _external=True)

    msg = Message('Reset your CareerOS password',
                  sender=app.config['MAIL_USERNAME'],
                  recipients=[email])
    msg.html = render_template(
        'email_forgot_password.html',
        name=user.name, reset_url=reset_url, otp_url=otp_url,
        otp=otp_code, ttl_minutes=RESET_TOKEN_TTL_MINUTES,
    )
    try:
        mail.send(msg)
    except Exception as e:
        # Same reasoning as generate_and_send_otp above — the token/OTP rows
        # are already committed, so this only affects delivery, not state.
        print(f"[PASSWORD RESET MAIL ERROR] Failed to send reset email to {email}: {e}")


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
                    response_mime_type="application/json",
                    max_output_tokens=8192,
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


def generate_roadmap_with_ai(target_role, domain, prior_knowledge="", weekly_hours=10, experience_level="beginner", weak_areas=None):
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

    weak_areas: optional list of question texts the user answered wrong on
    their most recent domain skill assessment (see AssessmentAnswer). When
    present, the "new" path is instructed to cover these specific gaps
    early rather than treating the roadmap as a generic, one-size-fits-all
    path for the target role.

    Raises ValueError if the AI (even after one retry) never returns any
    usable milestones, instead of silently succeeding with an empty roadmap.
    """
    prior_knowledge = (prior_knowledge or "").strip()
    prior_knowledge_line = prior_knowledge if prior_knowledge else "Nothing yet — complete beginner, starting from scratch."

    weak_areas = [w.strip() for w in (weak_areas or []) if w and w.strip()]
    if weak_areas:
        # Cap what goes into the prompt so a large wrong-answer set doesn't
        # blow up prompt size — the weakest/most-recent ones are what
        # matters most for shaping the early roadmap.
        weak_areas_block = "\n".join(f"- {w}" for w in weak_areas[:15])
        weak_areas_line = (
            "The learner took a skill assessment for this domain and got the "
            "following questions wrong, meaning these are real, measured gaps "
            "(not guesses about what they might not know):\n"
            f"{weak_areas_block}"
        )
    else:
        weak_areas_line = "No assessment data available — no measured weak areas to prioritize."

    prompt = f"""
You are a career roadmap generator. Create a personalized learning roadmap.

Target Role: {target_role}
Domain: {domain}
Available Time: {weekly_hours} hours/week
Experience Level: {experience_level}
What the learner says they've already learned or worked on: "{prior_knowledge_line}"

Measured skill gaps from their assessment:
{weak_areas_line}

The roadmap covers two things, in order:
1. A short "revision" recap — ONLY if the learner listed real prior knowledge
   above. Skip it completely (contribute zero items) if they said they're
   starting fresh / know nothing. If included, keep it to 1-3 items that
   quickly refresh exactly what they said they already know — do not
   re-teach it from zero, and do not add things they didn't mention.
2. The forward-looking "new" path — everything else the learner still needs
   to learn to reach {target_role}, building on top of the revision recap.
   If measured skill gaps were listed above, make sure milestones covering
   those specific topics appear EARLY in the "new" path (lower week numbers),
   ahead of topics the assessment didn't flag as weak — the assessment
   result is a stronger signal than a generic curriculum order.

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

# ── PAYMENTS (RAZORPAY) ──
def _activate_plan(user, payment):
    days = 365 if payment.billing_cycle == 'yearly' else 30
    user.plan = payment.plan_id
    user.billing_cycle = payment.billing_cycle
    user.is_pro = True                      # both pro and team unlock is_pro-gated features
    user.pro_expires_at = datetime.utcnow() + timedelta(days=days)


def _get_owned_payment(order_id):
    """Payment row for this order, scoped to the logged-in user."""
    if not session.get('user_id'):
        return None
    return Payment.query.filter_by(razorpay_order_id=order_id, user_id=session['user_id']).first()


@app.route('/api/payments/create-order', methods=['POST'])
def api_create_order():
    if not session.get('user_id'):
        return jsonify({"error": "Please log in first."}), 401

    user = User.query.get(session['user_id'])
    data = request.get_json(silent=True) or {}
    plan_id = data.get('plan_id')
    cycle = data.get('billing_cycle', 'monthly')

    if plan_id not in VALID_PLAN_IDS or cycle not in VALID_CYCLES:
        return jsonify({"error": "Invalid plan or billing cycle."}), 400

    amount = get_amount_paise(plan_id, cycle)

    # No real Razorpay keys configured (e.g. local/demo/college project) ->
    # fall back to the in-house simulated checkout instead of failing.
    if not razorpay_client:
        order_id = f"dummy_{secrets.token_hex(8)}"
        payment = Payment(
            user_id=user.id, plan_id=plan_id, billing_cycle=cycle,
            amount_paise=amount, razorpay_order_id=order_id,
            status="created", gateway="dummy",
        )
        db.session.add(payment)
        db.session.commit()
        return jsonify({"redirect_url": url_for('dummy_checkout', order_id=order_id)})

    order = razorpay_client.order.create({
        "amount": amount,
        "currency": "INR",
        "receipt": f"user{user.id}_{plan_id}_{cycle}_{int(datetime.utcnow().timestamp())}",
        "notes": {"user_id": str(user.id), "plan_id": plan_id, "billing_cycle": cycle},
    })

    payment = Payment(
        user_id=user.id, plan_id=plan_id, billing_cycle=cycle,
        amount_paise=amount, razorpay_order_id=order["id"], status="created",
        gateway="razorpay",
    )
    db.session.add(payment)
    db.session.commit()

    return jsonify({
        "order_id": order["id"], "amount": amount, "currency": "INR",
        "key_id": RAZORPAY_KEY_ID, "plan_name": PLANS[plan_id]["name"],
        "user_email": user.email, "user_name": user.name or "",
    })


# ── DUMMY GATEWAY (used automatically when Razorpay isn't configured) ──
@app.route('/checkout/<order_id>')
def dummy_checkout(order_id):
    payment = _get_owned_payment(order_id)
    if not payment or payment.gateway != 'dummy':
        return redirect(url_for('pricing'))
    if payment.status == 'paid':
        return redirect(url_for('payment_success', order_id=order_id))

    user = User.query.get(session['user_id'])
    order = {
        "order_id": payment.razorpay_order_id,
        "amount": payment.amount_paise // 100,
        "customer_name": user.name or user.email,
    }
    return render_template('checkout.html', order=order)


@app.route('/api/process-payment', methods=['POST'])
def api_process_payment():
    if not session.get('user_id'):
        return jsonify({"error": "Please log in first."}), 401

    data = request.get_json(silent=True) or {}
    order_id = data.get('order_id')
    method = data.get('method')
    simulate_result = data.get('simulate_result', 'random')

    payment = _get_owned_payment(order_id)
    if not payment or payment.gateway != 'dummy':
        return jsonify({"error": "Order not found."}), 404
    if payment.status == 'paid':
        return jsonify({"redirect_url": url_for('payment_success', order_id=order_id)})
    if method not in ('card', 'upi', 'wallet'):
        return jsonify({"error": "Invalid payment method."}), 400

    # Deterministic test triggers first, same convention as the hints shown
    # on the checkout page; otherwise fall back to the demo control.
    success, reason = True, None
    if method == 'card':
        card_number = (data.get('card_number') or '').replace(' ', '')
        if card_number == '4000000000000002':
            success, reason = False, "Card declined by issuing bank."
    elif method == 'upi':
        upi_id = (data.get('upi_id') or '').strip().lower()
        if upi_id.startswith('fail@'):
            success, reason = False, "UPI transaction declined."

    if success and simulate_result == 'failed':
        success, reason = False, "Payment declined (simulated failure)."
    elif success and simulate_result == 'random':
        success = random.random() < 0.8
        if not success:
            reason = "Payment declined by the bank (simulated)."

    payment.method = method
    if success:
        payment.status = 'paid'
        payment.transaction_id = f"TXN{secrets.token_hex(6).upper()}"
        payment.verified_at = datetime.utcnow()
        user = User.query.get(session['user_id'])
        _activate_plan(user, payment)
        db.session.commit()
        return jsonify({"redirect_url": url_for('payment_success', order_id=order_id)})
    else:
        payment.status = 'failed'
        payment.failure_reason = reason
        db.session.commit()
        return jsonify({"redirect_url": url_for('payment_failed', order_id=order_id)})


@app.route('/payment/success/<order_id>')
def payment_success(order_id):
    payment = _get_owned_payment(order_id)
    if not payment or payment.status != 'paid':
        return redirect(url_for('pricing'))
    order = {
        "order_id": payment.razorpay_order_id,
        "transaction_id": payment.transaction_id,
        "amount": payment.amount_paise // 100,
        "method": payment.method,
    }
    return render_template('success.html', order=order)


@app.route('/payment/failed/<order_id>')
def payment_failed(order_id):
    payment = _get_owned_payment(order_id)
    if not payment:
        return redirect(url_for('pricing'))
    order = {
        "order_id": payment.razorpay_order_id,
        "amount": payment.amount_paise // 100,
        "failure_reason": payment.failure_reason,
    }
    return render_template('failure.html', order=order)


@app.route('/api/payments/verify', methods=['POST'])
def api_verify_payment():
    if not session.get('user_id'):
        return jsonify({"error": "Please log in first."}), 401

    user = User.query.get(session['user_id'])
    data = request.get_json(silent=True) or {}
    order_id = data.get('razorpay_order_id')
    payment_id = data.get('razorpay_payment_id')
    signature = data.get('razorpay_signature')

    if not all([order_id, payment_id, signature]):
        return jsonify({"error": "Missing payment fields."}), 400

    payment = Payment.query.filter_by(razorpay_order_id=order_id, user_id=user.id).first()
    if not payment:
        return jsonify({"error": "Order not found."}), 404

    expected_signature = hmac.new(
        RAZORPAY_KEY_SECRET.encode(), f"{order_id}|{payment_id}".encode(), hashlib.sha256
    ).hexdigest()

    if not hmac.compare_digest(expected_signature, signature):
        payment.status = "failed"
        db.session.commit()
        return jsonify({"error": "Signature verification failed."}), 400

    payment.razorpay_payment_id = payment_id
    payment.razorpay_signature = signature
    payment.status = "paid"
    payment.verified_at = datetime.utcnow()
    _activate_plan(user, payment)
    db.session.commit()

    return jsonify({"status": "success", "plan": payment.plan_id})


@app.route('/api/payments/webhook/razorpay', methods=['POST'])
def razorpay_webhook():
    """Source of truth independent of the browser — configure this URL in
    Razorpay Dashboard > Settings > Webhooks, events: payment.captured, payment.failed."""
    if not RAZORPAY_WEBHOOK_SECRET:
        return jsonify({"error": "Webhook not configured."}), 503

    payload = request.get_data()
    signature = request.headers.get("X-Razorpay-Signature", "")
    expected = hmac.new(RAZORPAY_WEBHOOK_SECRET.encode(), payload, hashlib.sha256).hexdigest()

    if not hmac.compare_digest(expected, signature):
        print("Razorpay webhook: bad signature")
        return jsonify({"error": "invalid signature"}), 400

    event = json.loads(payload)
    event_type = event.get("event")

    if event_type == "payment.captured":
        entity = event["payload"]["payment"]["entity"]
        payment = Payment.query.filter_by(razorpay_order_id=entity.get("order_id")).first()
        if payment and payment.status != "paid":
            payment.status = "paid"
            payment.razorpay_payment_id = entity["id"]
            payment.verified_at = datetime.utcnow()
            user = User.query.get(payment.user_id)
            _activate_plan(user, payment)
            db.session.commit()

    elif event_type == "payment.failed":
        entity = event["payload"]["payment"]["entity"]
        payment = Payment.query.filter_by(razorpay_order_id=entity.get("order_id")).first()
        if payment:
            payment.status = "failed"
            db.session.commit()

    return jsonify({"status": "ok"})


def downgrade_expired_plans():
    """Call daily (cron / scheduled task) to flip lapsed Pro/Team users back to Free."""
    expired = User.query.filter(
        User.plan.in_(['pro', 'team']), User.pro_expires_at < datetime.utcnow()
    ).all()
    for user in expired:
        user.plan = 'free'
        user.billing_cycle = None
        user.is_pro = False
    db.session.commit()
    return len(expired)


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
    user = User.query.get(session['user_id']) if session.get('user_id') else None
    return render_template('pricing.html', current_user=user, razorpay_key_id=RAZORPAY_KEY_ID)

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

        email_sent = generate_and_send_otp(email)
        session['pending_email'] = email
        session['otp_email_sent'] = email_sent
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

    email_sent = session.pop('otp_email_sent', True)
    return render_template('verify_otp.html', email=email, email_sent=email_sent)

@app.route('/resend-otp')
def resend_otp():
    email = session.get('pending_email')
    if email:
        email_sent = generate_and_send_otp(email)
        session['otp_email_sent'] = email_sent
        if email_sent:
            flash('A new OTP has been sent.')
        else:
            flash('We could not send your verification code. Please try again later.')
    return redirect(url_for('verify_otp'))


# ── FORGOT PASSWORD (reset link OR login via OTP) ──
@app.route('/forgot-password', methods=['GET', 'POST'])
def forgot_password():
    if request.method == 'POST':
        email = request.form.get('email', '').strip().lower()

        user = User.query.filter_by(email=email).first()
        if user:
            _generate_and_send_password_reset(user)

        # Same "check your inbox" message whether or not the account exists,
        # so this can't be used to probe which emails are registered.
        return render_template('forgot_password.html', sent=True, email=email)

    return render_template('forgot_password.html', sent=False)


@app.route('/reset-password/<token>', methods=['GET', 'POST'])
def reset_password(token):
    record = PasswordResetToken.query.filter_by(token=token).first()

    if not record or record.expires_at < datetime.utcnow():
        flash('That reset link is invalid or has expired. Please request a new one.')
        return redirect(url_for('forgot_password'))

    if request.method == 'POST':
        password = request.form.get('password', '')
        confirm_password = request.form.get('confirm_password', '')

        if len(password) < 6:
            flash('Password must be at least 6 characters.')
            return render_template('reset_password.html', token=token)

        if password != confirm_password:
            flash('Passwords do not match.')
            return render_template('reset_password.html', token=token)

        user = User.query.filter_by(email=record.email).first()
        if not user:
            flash('That account no longer exists.')
            return redirect(url_for('forgot_password'))

        user.password_hash = generate_password_hash(password)

        # Using either recovery option retires both.
        PasswordResetToken.query.filter_by(email=record.email).delete()
        OTPVerification.query.filter_by(email=record.email, purpose='login').delete()
        db.session.commit()

        flash('Your password has been reset. Please log in.')
        return redirect(url_for('login'))

    return render_template('reset_password.html', token=token)


@app.route('/login-otp/<token>', methods=['GET', 'POST'])
def login_otp(token):
    record = PasswordResetToken.query.filter_by(token=token).first()

    if not record or record.expires_at < datetime.utcnow():
        flash('That link has expired. Please request a new one.')
        return redirect(url_for('forgot_password'))

    otp_row = OTPVerification.query.filter_by(email=record.email, purpose='login').first()

    if request.method == 'POST':
        entered_otp = request.form.get('otp', '').strip()

        if not otp_row or otp_row.expires_at < datetime.utcnow():
            flash('That code has expired. Please request a new one.')
            return redirect(url_for('forgot_password'))

        # Constant-time comparison to avoid leaking the code via timing.
        if not hmac.compare_digest(entered_otp, otp_row.otp_code):
            flash('That code is incorrect. Please try again.')
            return render_template('login_otp.html', token=token, email=record.email)

        user = User.query.filter_by(email=record.email).first()
        if not user:
            flash('That account no longer exists.')
            return redirect(url_for('forgot_password'))

        session['user_id'] = user.id

        # Using either recovery option retires both.
        PasswordResetToken.query.filter_by(email=record.email).delete()
        OTPVerification.query.filter_by(email=record.email, purpose='login').delete()
        db.session.commit()

        if not user.profile_complete:
            return redirect(url_for('profile_setup'))
        return redirect(url_for('profile'))

    return render_template('login_otp.html', token=token, email=record.email)


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
        saved_skill_count = 0
        for name, level in zip(skill_names, skill_levels):
            name = name.strip()
            if name:
                db.session.add(Skill(user_id=user.id, name=name, level=level))
                saved_skill_count += 1
        db.session.add(SkillSnapshot(user_id=user.id, skill_count=saved_skill_count))

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

    # Only grade the questions actually shown for this attempt (their ids
    # arrive as answer_<id> form fields) instead of re-querying every
    # question in the domain bank.
    answered_ids = []
    for key in request.form:
        if key.startswith("answer_"):
            try:
                answered_ids.append(int(key.split("answer_", 1)[1]))
            except ValueError:
                continue

    questions = AssessmentQuestion.query.filter(
        AssessmentQuestion.id.in_(answered_ids)
    ).all() if answered_ids else []

    score = 0
    wrong_questions = []
    result = AssessmentResult(user_id=user.id, domain=domain, score=0)
    db.session.add(result)
    db.session.flush()  # get result.id before inserting answers

    for q in questions:
        selected = request.form.get(f"answer_{q.id}")
        if selected is None:
            continue
        is_correct = int(selected) == q.correct_answer
        if is_correct:
            score += 1
        else:
            wrong_questions.append(q.question)

        db.session.add(AssessmentAnswer(
            result_id=result.id,
            user_id=user.id,
            domain=domain,
            question_id=q.id,
            question_text=q.question,
            is_correct=is_correct,
        ))

    result.score = score
    db.session.commit()

    return render_template(
        "assessment_result.html",
        user=user,
        score=score,
        domain_label=DOMAIN_LABELS.get(domain),
        weak_areas=wrong_questions
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


# ── NETWORK ──
@app.route('/network')
def network():
    user = User.query.get(session.get('user_id'))
    if not user:
        return redirect(url_for('login'))

    connected_ids = get_connection_ids(user.id)
    connections = [_with_display_fields(User.query.get(uid)) for uid in connected_ids]

    pending_received = ConnectionRequest.query.filter_by(receiver_id=user.id).all()
    invitations = [{
        "id": req.id,
        "from_user": _with_display_fields(req.sender),
        "message": req.message,
    } for req in pending_received]

    pending_sent_ids = {r.receiver_id for r in ConnectionRequest.query.filter_by(sender_id=user.id).all()}
    pending_received_ids = {r.sender_id for r in pending_received}
    excluded_ids = connected_ids | pending_sent_ids | pending_received_ids | {user.id}

    # Signals for ranking "People you may know": shared employer, shared
    # school, same career domain, mutual connections — closest matches
    # (actual colleagues/classmates) surface first.
    my_companies = {e.company.strip().lower() for e in user.experience if e.company}
    my_schools = {e.school.strip().lower() for e in user.education if e.school}

    candidates = User.query.filter(User.id.notin_(excluded_ids)).limit(200).all()

    suggestions = []
    for cand in candidates:
        cand = _with_display_fields(cand)
        cand_companies = {e.company.strip().lower() for e in cand.experience if e.company}
        cand_schools = {e.school.strip().lower() for e in cand.education if e.school}
        cand.mutual_count = mutual_connection_count(user.id, cand.id)
        cand.shared_company = next(iter(my_companies & cand_companies), None)
        cand.shared_school = next(iter(my_schools & cand_schools), None)
        suggestions.append(cand)

    suggestions.sort(key=lambda c: (
        c.shared_company is None,
        c.shared_school is None,
        c.domain != user.domain,
        -c.mutual_count,
    ))
    suggestions = suggestions[:24]

    return render_template(
        'network.html',
        user=user,
        connections=connections,
        invitations=invitations,
        suggestions=suggestions,
    )


@app.route('/u/<int:user_id>')
def person_profile(user_id):
    viewer = User.query.get(session.get('user_id'))
    if not viewer:
        return redirect(url_for('login'))

    viewed_user = User.query.get(user_id)
    if not viewed_user:
        flash("That profile doesn't exist.")
        return redirect(url_for('network'))

    if viewed_user.id == viewer.id:
        return redirect(url_for('profile'))

    _with_display_fields(viewed_user)
    posts = Post.query.filter_by(user_id=user_id).order_by(Post.created_at.desc()).all()
    serialized_posts = [_serialize_post(p, viewer) for p in posts]
    return render_template(
        'person_profile.html',
        viewed_user=viewed_user,
        connection_status=connection_status(viewer.id, user_id),
        mutual_connections=mutual_connection_count(viewer.id, user_id),
        posts=serialized_posts,
    )


@app.route('/api/network/connect/<int:user_id>', methods=['POST'])
def api_send_connection_request(user_id):
    if 'user_id' not in session:
        return jsonify({"error": "Please log in first."}), 401
    sender_id = session['user_id']
    if sender_id == user_id:
        return jsonify({"error": "You can't connect with yourself."}), 400
    target = User.query.get(user_id)
    if not target:
        return jsonify({"error": "User not found."}), 404
    if are_connected(sender_id, user_id):
        return jsonify({"error": "You're already connected."}), 400

    existing = ConnectionRequest.query.filter_by(sender_id=sender_id, receiver_id=user_id).first()
    if existing:
        return jsonify({"status": "pending", "invitation_id": existing.id}), 200

    # They'd already invited us — accept it instead of creating a duplicate.
    reverse = ConnectionRequest.query.filter_by(sender_id=user_id, receiver_id=sender_id).first()
    if reverse:
        create_connection(sender_id, user_id)
        db.session.delete(reverse)
        sender = User.query.get(sender_id)
        _create_notification(user_id, "connection_accepted", f"{sender.name} accepted your connection request.")
        db.session.commit()
        return jsonify({"status": "connected"}), 200

    req = ConnectionRequest(sender_id=sender_id, receiver_id=user_id)
    db.session.add(req)
    sender = User.query.get(sender_id)
    _create_notification(user_id, "connection_request", f"{sender.name} sent you a connection request.")
    db.session.commit()
    return jsonify({"status": "pending", "invitation_id": req.id}), 200


@app.route('/api/network/connect/<int:user_id>/accept-from-profile', methods=['POST'])
def api_accept_connection_from_profile(user_id):
    # Used by person_profile.html, which only knows the other user's id,
    # not the underlying invitation id.
    if 'user_id' not in session:
        return jsonify({"error": "Please log in first."}), 401
    receiver_id = session['user_id']
    req = ConnectionRequest.query.filter_by(sender_id=user_id, receiver_id=receiver_id).first()
    if not req:
        return jsonify({"error": "No pending invitation from this user."}), 404

    create_connection(receiver_id, user_id)
    db.session.delete(req)
    receiver = User.query.get(receiver_id)
    _create_notification(user_id, "connection_accepted", f"{receiver.name} accepted your connection request.")
    db.session.commit()
    return jsonify({"status": "connected"}), 200


@app.route('/api/network/invitations/<int:invite_id>/accept', methods=['POST'])
def api_accept_invitation(invite_id):
    if 'user_id' not in session:
        return jsonify({"error": "Please log in first."}), 401
    req = ConnectionRequest.query.get(invite_id)
    if not req or req.receiver_id != session['user_id']:
        return jsonify({"error": "Invitation not found."}), 404

    create_connection(req.sender_id, req.receiver_id)
    db.session.delete(req)
    receiver = User.query.get(req.receiver_id)
    _create_notification(req.sender_id, "connection_accepted", f"{receiver.name} accepted your connection request.")
    db.session.commit()
    return jsonify({"status": "connected"}), 200


@app.route('/api/network/invitations/<int:invite_id>/decline', methods=['POST'])
def api_decline_invitation(invite_id):
    if 'user_id' not in session:
        return jsonify({"error": "Please log in first."}), 401
    req = ConnectionRequest.query.get(invite_id)
    if not req or req.receiver_id != session['user_id']:
        return jsonify({"error": "Invitation not found."}), 404

    db.session.delete(req)
    db.session.commit()
    return jsonify({"status": "declined"}), 200


@app.route('/api/network/connections/<int:user_id>', methods=['DELETE'])
def api_remove_connection(user_id):
    if 'user_id' not in session:
        return jsonify({"error": "Please log in first."}), 401
    remove_connection(session['user_id'], user_id)
    db.session.commit()
    return jsonify({"status": "removed"}), 200


# ── COMPANIES ──
@app.route('/companies')
def companies():
    user = User.query.get(session.get('user_id'))
    if not user:
        return redirect(url_for('login'))

    followed_ids = {f.company_id for f in CompanyFollow.query.filter_by(user_id=user.id).all()}

    # Batched instead of one COUNT() query per company (was N+1: 2 extra
    # queries per company on every page load). Two grouped queries total,
    # regardless of how many companies exist.
    follower_counts = dict(
        db.session.query(CompanyFollow.company_id, db.func.count(CompanyFollow.id))
        .group_by(CompanyFollow.company_id).all()
    )
    employee_counts = dict(
        db.session.query(db.func.lower(Experience.company), db.func.count(db.distinct(Experience.user_id)))
        .group_by(db.func.lower(Experience.company)).all()
    )

    company_list = []
    for c in Company.query.order_by(Company.name).all():
        company_list.append({
            "id": c.id, "name": c.name, "domain": c.domain, "industry": c.industry,
            "logo_url": c.logo_url, "description": c.description,
            "followers_count": follower_counts.get(c.id, 0),
            "employee_count": employee_counts.get(c.name.lower(), 0),
            "is_following": c.id in followed_ids,
        })
    return render_template('companies.html', user=user, companies=company_list)


@app.route('/companies/<int:company_id>')
def company_profile(company_id):
    user = User.query.get(session.get('user_id'))
    if not user:
        return redirect(url_for('login'))

    company = Company.query.get(company_id)
    if not company:
        flash("That company doesn't exist.")
        return redirect(url_for('companies'))

    matching_user_ids = {
        e.user_id for e in Experience.query.filter(
            db.func.lower(Experience.company) == company.name.lower()
        ).all()
    }
    employees = [_with_display_fields(User.query.get(uid)) for uid in matching_user_ids if uid != user.id]

    openings = [{
        "title": job.job_title, "location": job.location, "type": job.job_type,
    } for job in Job.query.filter(db.func.lower(Job.company_name) == company.name.lower()).all()]

    company_dict = {
        "id": company.id, "name": company.name, "domain": company.domain,
        "industry": company.industry, "logo_url": company.logo_url,
        "description": company.description, "website": company.website,
        "followers_count": CompanyFollow.query.filter_by(company_id=company.id).count(),
        "employee_count": len(employees),
        "is_following": CompanyFollow.query.filter_by(user_id=user.id, company_id=company.id).first() is not None,
        "employees": employees,
        "openings": openings,
    }
    return render_template('company_profile.html', company=company_dict)


@app.route('/api/companies/<int:company_id>/follow', methods=['POST'])
def api_follow_company(company_id):
    if 'user_id' not in session:
        return jsonify({"error": "Please log in first."}), 401
    if not Company.query.get(company_id):
        return jsonify({"error": "Company not found."}), 404
    if not CompanyFollow.query.filter_by(user_id=session['user_id'], company_id=company_id).first():
        db.session.add(CompanyFollow(user_id=session['user_id'], company_id=company_id))
        db.session.commit()
    return jsonify({"status": "following"}), 200


@app.route('/api/companies/<int:company_id>/follow', methods=['DELETE'])
def api_unfollow_company(company_id):
    if 'user_id' not in session:
        return jsonify({"error": "Please log in first."}), 401
    CompanyFollow.query.filter_by(user_id=session['user_id'], company_id=company_id).delete()
    db.session.commit()
    return jsonify({"status": "not_following"}), 200


# ── SEARCH (people + companies, used by the Network and Companies pages) ──
@app.route('/api/search')
def api_search():
    if 'user_id' not in session:
        return jsonify({"error": "Please log in first."}), 401
    q = (request.args.get('q') or "").strip()
    if not q:
        return jsonify({"people": [], "companies": []})

    like = f"%{q}%"
    # People whose current/past company or school matches the query, so
    # searching "Razorpay" or "BITS Pilani" surfaces colleagues/classmates
    # even if the query doesn't match their name or target role.
    matching_user_ids = (
        {e.user_id for e in Experience.query.filter(Experience.company.ilike(like)).all()} |
        {e.user_id for e in Education.query.filter(Education.school.ilike(like)).all()}
    )
    conditions = [User.name.ilike(like), User.target_role.ilike(like)]
    if matching_user_ids:
        conditions.append(User.id.in_(matching_user_ids))

    people = (User.query
              .filter(User.id != session['user_id'])
              .filter(db.or_(*conditions))
              .limit(15).all())
    matched_companies = Company.query.filter(Company.name.ilike(like)).limit(10).all()

    return jsonify({
        "people": [{"id": p.id, "name": p.name, "role": p.target_role} for p in people],
        "companies": [{"id": c.id, "name": c.name, "industry": c.industry} for c in matched_companies],
    })


# ── FEED ──
POST_IMAGES_FOLDER = os.getenv("POST_IMAGES_FOLDER") or (
    "/tmp/uploads/posts" if os.getenv("VERCEL") == "1" else os.path.join("static", "uploads", "posts")
)
try:
    os.makedirs(POST_IMAGES_FOLDER, exist_ok=True)
except OSError:
    pass
POST_IMAGE_ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'webp'}


def _relative_time(dt):
    """Turns a UTC datetime into a short "2h ago" style label."""
    if not dt:
        return ""
    seconds = (datetime.utcnow() - dt).total_seconds()
    if seconds < 60:
        return "Just now"
    if seconds < 3600:
        return f"{int(seconds // 60)}m ago"
    if seconds < 86400:
        return f"{int(seconds // 3600)}h ago"
    if seconds < 604800:
        return f"{int(seconds // 86400)}d ago"
    return dt.strftime("%b %d, %Y")


def _serialize_post(post, current_user):
    return {
        "id": post.id,
        "is_mine": post.user_id == current_user.id,
        "user": {
            "name": post.author.name if post.author else "Unknown",
            "role": post.author.target_role if post.author else "",
            "avatar_url": None,
        },
        "created_at": _relative_time(post.created_at),
        "text": post.text or "",
        "images": [
            url_for('static', filename=f'uploads/posts/{img.filename}')
            for img in post.images
        ],
        "likes_count": len(post.likes),
        "liked_by_me": any(like.user_id == current_user.id for like in post.likes),
        "comments": [
            {"user": {"name": c.author.name if c.author else "Unknown"}, "text": c.text}
            for c in post.comments
        ],
    }


@app.route('/feed')
def feed():
    user = User.query.get(session.get('user_id'))
    if not user:
        return redirect(url_for('login'))

    feed_filter = request.args.get('filter', 'all')
    if feed_filter == 'following':
        visible_ids = get_connection_ids(user.id) | {user.id}
        posts = (Post.query.filter(Post.user_id.in_(visible_ids))
                 .order_by(Post.created_at.desc()).all())
    else:
        feed_filter = 'all'
        posts = Post.query.order_by(Post.created_at.desc()).all()
    serialized_posts = [_serialize_post(p, user) for p in posts]

    return render_template('feed.html', user=user, posts=serialized_posts, feed_filter=feed_filter)


@app.route('/api/feed/posts', methods=['POST'])
def api_feed_create_post():
    user = User.query.get(session.get('user_id'))
    if not user:
        return jsonify({"error": "Please log in first."}), 401

    text = (request.form.get('text') or '').strip()
    image_files = request.files.getlist('images')
    if not text and not any(f.filename for f in image_files):
        return jsonify({"error": "Add some text or at least one photo."}), 400

    post = Post(user_id=user.id, text=text)
    db.session.add(post)
    db.session.flush()  # assigns post.id before we save image rows

    for f in image_files:
        if not f or not f.filename:
            continue
        ext = f.filename.rsplit('.', 1)[-1].lower() if '.' in f.filename else ''
        if ext not in POST_IMAGE_ALLOWED_EXTENSIONS:
            continue
        filename = secure_filename(f"post_{post.id}_{int(time.time() * 1000)}_{f.filename}")
        f.save(os.path.join(POST_IMAGES_FOLDER, filename))
        db.session.add(PostImage(post_id=post.id, filename=filename))

    db.session.commit()
    return jsonify({"id": post.id}), 201


@app.route('/api/feed/posts/<int:post_id>', methods=['DELETE'])
def api_feed_delete_post(post_id):
    user = User.query.get(session.get('user_id'))
    if not user:
        return jsonify({"error": "Please log in first."}), 401

    post = Post.query.get(post_id)
    if not post or post.user_id != user.id:
        return jsonify({"error": "Post not found."}), 404

    for img in post.images:
        filepath = os.path.join(POST_IMAGES_FOLDER, img.filename)
        if os.path.isfile(filepath):
            os.remove(filepath)

    db.session.delete(post)
    db.session.commit()
    return jsonify({"deleted": True}), 200


@app.route('/api/feed/posts/<int:post_id>/like', methods=['POST'])
def api_feed_like_post(post_id):
    user = User.query.get(session.get('user_id'))
    if not user:
        return jsonify({"error": "Please log in first."}), 401

    post = Post.query.get(post_id)
    if not post:
        return jsonify({"error": "Post not found."}), 404

    existing = PostLike.query.filter_by(post_id=post.id, user_id=user.id).first()
    if not existing:
        db.session.add(PostLike(post_id=post.id, user_id=user.id))
        db.session.commit()

    return jsonify({"likes_count": len(post.likes)}), 200


@app.route('/api/feed/posts/<int:post_id>/like', methods=['DELETE'])
def api_feed_unlike_post(post_id):
    user = User.query.get(session.get('user_id'))
    if not user:
        return jsonify({"error": "Please log in first."}), 401

    post = Post.query.get(post_id)
    if not post:
        return jsonify({"error": "Post not found."}), 404

    PostLike.query.filter_by(post_id=post.id, user_id=user.id).delete()
    db.session.commit()

    return jsonify({"likes_count": len(post.likes)}), 200


@app.route('/api/feed/posts/<int:post_id>/comments', methods=['POST'])
def api_feed_add_comment(post_id):
    user = User.query.get(session.get('user_id'))
    if not user:
        return jsonify({"error": "Please log in first."}), 401

    post = Post.query.get(post_id)
    if not post:
        return jsonify({"error": "Post not found."}), 404

    data = request.get_json(silent=True) or {}
    text = (data.get('text') or '').strip()
    if not text:
        return jsonify({"error": "Comment can't be empty."}), 400

    comment = PostComment(post_id=post.id, user_id=user.id, text=text)
    db.session.add(comment)
    db.session.commit()

    return jsonify({"id": comment.id}), 201


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
        # Pull weak areas from the user's most recent assessment for their
        # domain (if they've taken one) so the roadmap starts from measured
        # gaps instead of only the free-text prior_knowledge they typed.
        weak_areas = []
        latest_result = (AssessmentResult.query
                          .filter_by(user_id=user.id, domain=user.domain)
                          .order_by(AssessmentResult.created_at.desc())
                          .first())
        if latest_result:
            wrong_answers = (AssessmentAnswer.query
                              .filter_by(result_id=latest_result.id, is_correct=False)
                              .all())
            weak_areas = [a.question_text for a in wrong_answers]

        data = generate_roadmap_with_ai(
            target_role=topic,
            domain=user.domain,
            prior_knowledge=prior_knowledge,
            weak_areas=weak_areas,
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

    # Bring in fresh live listings for this user's target role (falls back
    # to whatever's already seeded if ADZUNA keys aren't configured), then
    # advance any applications that are "due" for a status change so the
    # tracker/notifications feel alive rather than frozen on "Applied".
    sync_jobs_from_adzuna(query=user.target_role or "software developer", location=user.location or "India")
    _advance_user_applications(user)

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
    "unread_notifications": Notification.query.filter_by(user_id=user.id, is_read=False).count(),
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

    # Filters from query params
    role = request.args.get('role', '').strip()
    location = request.args.get('location', '').strip()
    company = request.args.get('company', '').strip()
    domain = request.args.get('domain', '').strip()
    experience = request.args.get('experience', '').strip()
    salary = request.args.get('salary', '').strip()
    remote = request.args.get('remote')

    # If the person actually searched for something, go pull fresh live
    # results for that exact query (subject to the cooldown inside
    # sync_jobs_from_adzuna so repeated keystrokes don't spam the API).
    if role or location:
        sync_jobs_from_adzuna(query=role or "software developer", location=location or "India")

    query = Job.query

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

    job = Job.query.get(job_id)
    if not job:
        return jsonify({"error": "This job no longer exists."}), 404

    user = User.query.get(user_id)
    user_skills = {s.name.lower().strip() for s in user.skills} if user.skills else set()
    job_skills = {s.strip().lower() for s in (job.skills_required or "").split(",") if s.strip()}
    if not job_skills:
        match_pct = 100
    elif not user_skills:
        match_pct = 75
    else:
        match_pct = round((len(user_skills.intersection(job_skills)) / len(job_skills)) * 100)

    new_app = Application(user_id=user_id, job_id=job_id, status="Applied", match_pct_at_apply=match_pct)
    db.session.add(new_app)
    _create_notification(
        user_id, "applied",
        f"Application submitted to {job.company_name} for {job.job_title}.",
        company_name=job.company_name, company_logo=job.company_logo, related_job_id=job.id,
    )
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


@app.route('/api/notifications/unread-count')
def api_notifications_unread_count():
    """Lightweight polling endpoint for the shared bell icon (see
    common.js) — every page has this, so it stays a small COUNT query
    rather than reusing /career/notifications' full 20-row payload."""
    if 'user_id' not in session:
        return jsonify({"count": 0}), 200
    count = Notification.query.filter_by(user_id=session['user_id'], is_read=False).count()
    return jsonify({"count": count})


@app.route('/career/notifications')
def career_notifications():
    if 'user_id' not in session:
        return jsonify({"error": "Please log in first."}), 401

    user_id = session['user_id']
    notes = (Notification.query.filter_by(user_id=user_id)
             .order_by(Notification.created_at.desc()).limit(20).all())
    return jsonify([n.as_dict() for n in notes])


@app.route('/career/notifications/read', methods=['POST'])
def career_notifications_read():
    if 'user_id' not in session:
        return jsonify({"error": "Please log in first."}), 401

    user_id = session['user_id']
    data = request.get_json(silent=True) or {}
    note_id = data.get('notification_id')

    query = Notification.query.filter_by(user_id=user_id, is_read=False)
    if note_id:
        query = query.filter_by(id=note_id)
    updated = query.update({"is_read": True})
    db.session.commit()

    return jsonify({"success": True, "updated": updated})


@app.route('/career/analytics')
def career_analytics():
    """Real, DB-derived data for the four Career Analytics charts —
    replaces the hardcoded Chart.js datasets that used to live in the
    frontend JS."""
    if 'user_id' not in session:
        return jsonify({"error": "Please log in first."}), 401

    user_id = session['user_id']
    now = datetime.utcnow()

    # ---- Application Success Rate: % of applications reaching Offer,
    #      grouped by the month they were applied to, last 6 months ----
    month_labels, success_rates = [], []
    for i in range(5, -1, -1):
        month_start = (now.replace(day=1) - timedelta(days=1)) if i == 0 else now
        # compute month boundaries by walking back i months from "now"
        target_month = (now.month - i - 1) % 12 + 1
        target_year = now.year + ((now.month - i - 1) // 12)
        m_start = datetime(target_year, target_month, 1)
        m_end = (datetime(target_year + 1, 1, 1) if target_month == 12
                 else datetime(target_year, target_month + 1, 1))

        month_apps = Application.query.filter(
            Application.user_id == user_id,
            Application.applied_date >= m_start,
            Application.applied_date < m_end,
        ).all()
        month_labels.append(m_start.strftime('%b'))
        if month_apps:
            offers = sum(1 for a in month_apps if a.status in ("Offer", "Joined"))
            success_rates.append(round((offers / len(month_apps)) * 100))
        else:
            success_rates.append(0)

    # ---- Interview Performance: last 5 AI Interview Coach sessions ----
    sessions = (InterviewCoachSession.query.filter_by(user_id=user_id)
                .order_by(InterviewCoachSession.created_at.asc()).all())
    recent_sessions = sessions[-5:] if sessions else []
    interview_labels = [f"R{i+1}" for i in range(len(recent_sessions))]
    interview_scores = [s.interview_score or 0 for s in recent_sessions]

    # ---- Skills Growth: number of skills tracked over each profile-save
    #      snapshot, last 6 snapshots ----
    snapshots = (SkillSnapshot.query.filter_by(user_id=user_id)
                 .order_by(SkillSnapshot.created_at.asc()).all())
    recent_snaps = snapshots[-6:] if snapshots else []
    skills_labels = [s.created_at.strftime('%d %b') for s in recent_snaps]
    skills_counts = [s.skill_count for s in recent_snaps]

    # ---- Job Match Trend: match % snapshot at the moment of each
    #      application vs. today's overall AI match average ----
    apps_with_match = (Application.query.filter(
        Application.user_id == user_id, Application.match_pct_at_apply.isnot(None)
    ).order_by(Application.applied_date.asc()).all())
    recent_apps = apps_with_match[-8:] if apps_with_match else []
    match_labels = [a.applied_date.strftime('%d %b') for a in recent_apps]
    match_at_apply = [a.match_pct_at_apply for a in recent_apps]
    current_avg_match = calculate_ai_match(user_id)

    return jsonify({
        "success_rate": {"labels": month_labels, "data": success_rates},
        "interview_performance": {"labels": interview_labels, "data": interview_scores},
        "skills_growth": {"labels": skills_labels, "data": skills_counts},
        "job_match_trend": {
            "labels": match_labels,
            "data": match_at_apply,
            "current_avg_match": current_avg_match,
        },
    })


# ── AI INTERVIEW COACH ─────────────────────────────────────────────────
def generate_interview_questions_with_ai(mode, target_role, domain):
    prompt = f"""
You are conducting a {mode} interview for a candidate targeting the role
of {target_role or "a general software/tech role"} in the {domain or "technology"} domain.

Generate 5 realistic interview questions appropriate for a {mode} round.
Return ONLY valid JSON matching exactly this schema:
{{"questions": ["question 1", "question 2", "question 3", "question 4", "question 5"]}}
"""
    data = _call_gemini_json(prompt)
    questions = data.get("questions") or []
    return questions[:5]


def score_interview_answer_with_ai(mode, question, answer_text, target_role):
    prompt = f"""
You are an expert interview coach scoring a candidate's spoken answer
(transcribed from speech) in a {mode} interview round for the role of
{target_role or "a general tech role"}.

Question asked: "{question}"
Candidate's answer (verbatim transcript): "{answer_text[:4000]}"

Score the answer and return ONLY valid JSON matching exactly this schema:
{{
  "interview_score": number (0-100, overall quality of the answer for this round),
  "confidence": number (0-100, how confident/assured the phrasing sounds),
  "communication": number (0-100, clarity and structure of the answer),
  "technical_accuracy": number (0-100, correctness/depth; for HR/behavioral rounds judge relevance and specificity instead),
  "feedback": "2-3 sentences of direct, specific, actionable feedback on this exact answer"
}}
"""
    return _call_gemini_json(prompt)


@app.route('/career/interview-coach/questions', methods=['POST'])
def interview_coach_questions():
    user = User.query.get(session.get('user_id'))
    if not user:
        return jsonify({"error": "Please log in first."}), 401

    data = request.get_json(silent=True) or {}
    mode = (data.get("mode") or "HR Interview").strip()

    try:
        questions = generate_interview_questions_with_ai(mode, user.target_role, user.domain)
        if not questions:
            raise ValueError("No questions returned")
        return jsonify({"mode": mode, "questions": questions}), 200
    except RateLimitError:
        return jsonify({"error": "AI is busy right now. Please try again in a moment.", "retry": True}), 429
    except (json.JSONDecodeError, ValueError) as e:
        print("Interview question generation error:", e)
        return jsonify({"error": "Couldn't generate questions right now. Please try again."}), 502


@app.route('/career/interview-coach/feedback', methods=['POST'])
def interview_coach_feedback():
    user = User.query.get(session.get('user_id'))
    if not user:
        return jsonify({"error": "Please log in first."}), 401

    data = request.get_json(silent=True) or {}
    mode = (data.get("mode") or "HR Interview").strip()
    question = (data.get("question") or "").strip()
    answer_text = (data.get("answer_text") or "").strip()

    if not question or not answer_text:
        return jsonify({"error": "Missing question or recorded answer."}), 400
    if len(answer_text.split()) < 4:
        return jsonify({"error": "That answer looked too short to score — try recording a fuller response."}), 400

    try:
        result = score_interview_answer_with_ai(mode, question, answer_text, user.target_role)

        session_row = InterviewCoachSession(
            user_id=user.id, mode=mode, question=question, answer_text=answer_text,
            interview_score=result.get("interview_score"),
            confidence=result.get("confidence"),
            communication=result.get("communication"),
            technical_accuracy=result.get("technical_accuracy"),
            feedback=result.get("feedback"),
        )
        db.session.add(session_row)
        db.session.commit()

        return jsonify(session_row.as_dict()), 200
    except RateLimitError:
        return jsonify({"error": "AI is busy right now. Please try again in a moment.", "retry": True}), 429
    except json.JSONDecodeError:
        return jsonify({"error": "AI returned invalid format. Please try again."}), 502
    except Exception as e:
        print("Interview feedback scoring error:", e)
        traceback.print_exc()
        return jsonify({"error": "Something went wrong scoring that answer."}), 500


@app.route('/career/interview-coach/latest')
def interview_coach_latest():
    if 'user_id' not in session:
        return jsonify({"error": "Please log in first."}), 401

    latest = (InterviewCoachSession.query.filter_by(user_id=session['user_id'])
              .order_by(InterviewCoachSession.created_at.desc()).first())
    return jsonify(latest.as_dict() if latest else None)



# ── RESUME BUILDER ──
@app.route('/resume-builder')
def resume_builder():
    user = User.query.get(session.get('user_id'))
    if not user:
        return redirect(url_for('login'))
    return render_template('resume-builder.html', user=user)


@app.route('/resume-builder/save-for-analysis', methods=['POST'], endpoint='resume_builder_save_for_analysis')
def resume_builder_save_for_analysis():
    """
    Takes the structured field data from the Resume Builder (name, objective,
    education, experience, etc.) and writes it out as a plain-text resume
    file, then points user.resume_filename at it.

    This deliberately bypasses PDF text-extraction: the builder's "Download
    PDF" rasterizes the preview into an image (html2canvas -> jsPDF), so that
    PDF has no selectable text layer and would fail the analyzer's PDF
    parser. Saving the original field text directly sidesteps that and
    reuses the exact same "resume on file" flow the analyzer already
    supports for uploaded resumes.
    """
    user = User.query.get(session.get('user_id'))
    if not user:
        return jsonify({"error": "Please log in again."}), 401

    payload = request.get_json(silent=True) or {}

    def line(label, value):
        value = (value or "").strip()
        return f"{label}: {value}" if value else ""

    def block_list(items, formatter):
        out = []
        for item in items or []:
            rendered = formatter(item)
            if rendered:
                out.append(rendered)
        return out

    parts = []

    name = (payload.get("name") or "").strip()
    title = (payload.get("title") or "").strip()
    if name:
        parts.append(name)
    if title:
        parts.append(title)

    contact_bits = [payload.get("email", ""), payload.get("phone", ""), payload.get("location", "")]
    contact_line = " | ".join(b.strip() for b in contact_bits if b and b.strip())
    if contact_line:
        parts.append(contact_line)

    objective = (payload.get("objective") or "").strip()
    if objective:
        parts.append("\nCAREER OBJECTIVE\n" + objective)

    education = block_list(payload.get("education"), lambda e: "\n".join(filter(None, [
        line("Degree", e.get("degree")),
        line("Institution", e.get("institution")),
        line("Duration", e.get("duration")),
        line("Score", e.get("score")),
    ])))
    if education:
        parts.append("\nEDUCATION\n" + "\n\n".join(education))

    experience = block_list(payload.get("experience"), lambda e: "\n".join(filter(None, [
        line("Role", e.get("role")),
        line("Company", e.get("company")),
        line("Duration", e.get("duration")),
        line("Description", e.get("description")),
    ])))
    if experience:
        parts.append("\nEXPERIENCE\n" + "\n\n".join(experience))

    internships = block_list(payload.get("internships"), lambda e: "\n".join(filter(None, [
        line("Role", e.get("role")),
        line("Company", e.get("company")),
        line("Duration", e.get("duration")),
        line("Description", e.get("description")),
    ])))
    if internships:
        parts.append("\nINTERNSHIPS\n" + "\n\n".join(internships))

    projects = block_list(payload.get("projects"), lambda e: "\n".join(filter(None, [
        line("Title", e.get("title")),
        line("Tech Stack", e.get("stack")),
        line("Description", e.get("description")),
    ])))
    if projects:
        parts.append("\nPROJECTS\n" + "\n\n".join(projects))

    certificates = [c for c in (payload.get("certificates") or []) if c and str(c).strip()]
    if certificates:
        parts.append("\nCERTIFICATES\n" + ", ".join(certificates))

    achievements = [a for a in (payload.get("achievements") or []) if a and str(a).strip()]
    if achievements:
        parts.append("\nACHIEVEMENTS\n" + "\n".join(f"- {a}" for a in achievements))

    skills = [s for s in (payload.get("skills") or []) if s and str(s).strip()]
    if skills:
        parts.append("\nSKILLS\n" + ", ".join(skills))

    strengths = [s for s in (payload.get("strengths") or []) if s and str(s).strip()]
    if strengths:
        parts.append("\nSTRENGTHS\n" + ", ".join(strengths))

    resume_text = "\n".join(parts).strip()
    if not resume_text:
        return jsonify({"error": "Add some resume content before saving to the Analyzer."}), 400

    filename = secure_filename(f"user_{user.id}_builder-resume.txt")
    filepath = os.path.join(UPLOAD_FOLDER, filename)
    try:
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(resume_text)
    except OSError as e:
        print("Resume builder save error:", e)
        traceback.print_exc()
        return jsonify({"error": "Couldn't save that resume on the server. Please try again."}), 500

    user.resume_filename = filename
    db.session.commit()

    return jsonify({"success": True, "redirect": url_for('resume_analyzer'), "resume_filename": filename}), 200


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
        if ml_resume_analyzer is not None:
            data = ml_resume_analyzer.analyze(resume_text, user.target_role)
        else:
            # Fallback only if the trained model artifacts are missing
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


@app.route('/api/settings/notifications', methods=['POST'])
def api_update_notification_settings():
    user = User.query.get(session.get('user_id'))
    if not user:
        return jsonify({"error": "Please log in first."}), 401

    data = request.get_json(silent=True) or {}
    if 'notify_career' in data:
        user.notify_career = bool(data['notify_career'])
    if 'notify_network' in data:
        user.notify_network = bool(data['notify_network'])
    db.session.commit()

    return jsonify({
        "success": True,
        "notify_career": user.notify_career,
        "notify_network": user.notify_network,
    })


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

    initials = "".join(
        part[0].upper()
        for part in (user.name or "?").split()[:2]
    ) or "?"

    materials_generated = LearningHubActivity.query.filter_by(user_id=user.id).count()
    subjects_viewed = (
        db.session.query(LearningHubActivity.domain, LearningHubActivity.subject)
        .filter_by(user_id=user.id)
        .distinct()
        .count()
    )
    stats = {
        "subjects_viewed": subjects_viewed,
        "materials_generated": materials_generated,
    }

    return render_template(
        'learning-hub.html',
        user=user,
        user_initials=initials,
        domain_labels=DOMAIN_LABELS,
        stats=stats,
    )


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

    db.session.add(LearningHubActivity(user_id=session['user_id'], domain=domain, subject=subject))
    db.session.commit()

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


# ── CERTIFICATIONS ──
@app.route('/certificates')
def certificates():
    user = User.query.get(session.get('user_id'))
    if not user:
        return redirect(url_for('login'))

    enrollments = CertificationEnrollment.query.filter_by(user_id=user.id).all()
    certs = Certificate.query.filter_by(user_id=user.id).order_by(Certificate.issued_at.desc()).all()

    stats = {
        "in_progress": sum(1 for e in enrollments if e.status != "completed"),
        "completed": sum(1 for e in enrollments if e.status == "completed"),
        "certificates_earned": len(certs),
    }

    return render_template(
        'certificates.html',
        user=user,
        domain_labels=DOMAIN_LABELS,
        stats=stats,
        certificates=certs,
    )


def _enrollment_progress(enrollment, total_modules):
    completed = json.loads(enrollment.modules_completed_json or "[]") if enrollment else []
    return {
        "status": enrollment.status if enrollment else "not_started",
        "modules_completed": completed,
        "modules_total": total_modules,
        "all_modules_done": total_modules > 0 and len(completed) >= total_modules,
        "quiz_score": enrollment.quiz_score if enrollment else None,
        "quiz_total": enrollment.quiz_total if enrollment else None,
        "quiz_attempts": enrollment.quiz_attempts if enrollment else 0,
    }


@app.route('/api/certificates/courses', methods=['POST'])
def api_certificates_courses():
    if 'user_id' not in session:
        return jsonify({"error": "Please log in first."}), 401

    data = request.get_json(silent=True) or {}
    domain = (data.get("domain") or "").strip()
    if not domain:
        return jsonify({"error": "Missing domain."}), 400

    regenerate = request.args.get("regenerate") == "1"

    try:
        courses = _get_or_create_cert_courses(domain, regenerate=regenerate)
    except RateLimitError:
        return jsonify({"error": "AI is busy right now. Please try again in a moment.", "retry": True}), 429
    except (json.JSONDecodeError, ValueError) as e:
        print("Certification courses generation error:", e)
        return jsonify({"error": "Couldn't generate courses right now. Please try again."}), 502

    enrollments = {
        e.course_title: e for e in
        CertificationEnrollment.query.filter_by(user_id=session['user_id'], domain=domain).all()
    }
    earned_titles = {
        c.course_title for c in
        Certificate.query.filter_by(user_id=session['user_id'], domain=domain).all()
    }
    for course in courses:
        title = course.get("title")
        e = enrollments.get(title)
        course["enrollment_status"] = e.status if e else "not_started"
        course["certificate_earned"] = title in earned_titles

    return jsonify({"courses": courses}), 200


@app.route('/api/certificates/course-detail', methods=['POST'])
def api_certificates_course_detail():
    if 'user_id' not in session:
        return jsonify({"error": "Please log in first."}), 401

    data = request.get_json(silent=True) or {}
    domain = (data.get("domain") or "").strip()
    title = (data.get("title") or "").strip()
    if not domain or not title:
        return jsonify({"error": "Missing domain or title."}), 400

    regenerate = request.args.get("regenerate") == "1"

    try:
        course = _get_or_create_cert_course(domain, title, regenerate=regenerate)
    except RateLimitError:
        return jsonify({"error": "AI is busy right now. Please try again in a moment.", "retry": True}), 429
    except (json.JSONDecodeError, ValueError) as e:
        print("Certification course detail generation error:", e)
        return jsonify({"error": "Couldn't generate this course right now. Please try again."}), 502

    modules = json.loads(course.modules_json or "[]")
    enrollment = CertificationEnrollment.query.filter_by(
        user_id=session['user_id'], domain=domain, course_title=title
    ).first()
    cert = Certificate.query.filter_by(
        user_id=session['user_id'], domain=domain, course_title=title
    ).first()

    return jsonify({
        "title": course.title,
        "level": course.level,
        "duration_hours": course.duration_hours,
        "description": course.description,
        "modules": modules,
        "progress": _enrollment_progress(enrollment, len(modules)),
        "certificate_code": cert.certificate_code if cert else None,
    }), 200


@app.route('/api/certificates/enroll', methods=['POST'])
def api_certificates_enroll():
    if 'user_id' not in session:
        return jsonify({"error": "Please log in first."}), 401

    data = request.get_json(silent=True) or {}
    domain = (data.get("domain") or "").strip()
    title = (data.get("title") or "").strip()
    if not domain or not title:
        return jsonify({"error": "Missing domain or title."}), 400

    enrollment = CertificationEnrollment.query.filter_by(
        user_id=session['user_id'], domain=domain, course_title=title
    ).first()
    if not enrollment:
        enrollment = CertificationEnrollment(
            user_id=session['user_id'], domain=domain, course_title=title,
            modules_completed_json="[]",
        )
        db.session.add(enrollment)
        db.session.commit()

    course = CertificationCourse.query.filter_by(domain=domain, title=title).first()
    total_modules = len(json.loads(course.modules_json)) if course else 0

    return jsonify({"progress": _enrollment_progress(enrollment, total_modules)}), 200


@app.route('/api/certificates/progress', methods=['POST'])
def api_certificates_progress():
    if 'user_id' not in session:
        return jsonify({"error": "Please log in first."}), 401

    data = request.get_json(silent=True) or {}
    domain = (data.get("domain") or "").strip()
    title = (data.get("title") or "").strip()
    module_index = data.get("module_index")
    if not domain or not title or module_index is None:
        return jsonify({"error": "Missing domain, title, or module_index."}), 400

    enrollment = CertificationEnrollment.query.filter_by(
        user_id=session['user_id'], domain=domain, course_title=title
    ).first()
    if not enrollment:
        return jsonify({"error": "Not enrolled in this course yet."}), 404

    course = CertificationCourse.query.filter_by(domain=domain, title=title).first()
    if not course:
        return jsonify({"error": "Course not found."}), 404
    total_modules = len(json.loads(course.modules_json))

    completed = set(json.loads(enrollment.modules_completed_json or "[]"))
    completed.add(int(module_index))
    enrollment.modules_completed_json = json.dumps(sorted(completed))
    db.session.commit()

    return jsonify({"progress": _enrollment_progress(enrollment, total_modules)}), 200


@app.route('/api/certificates/quiz', methods=['POST'])
def api_certificates_quiz():
    if 'user_id' not in session:
        return jsonify({"error": "Please log in first."}), 401

    data = request.get_json(silent=True) or {}
    domain = (data.get("domain") or "").strip()
    title = (data.get("title") or "").strip()
    if not domain or not title:
        return jsonify({"error": "Missing domain or title."}), 400

    course = CertificationCourse.query.filter_by(domain=domain, title=title).first()
    if not course:
        return jsonify({"error": "Course not found."}), 404

    enrollment = CertificationEnrollment.query.filter_by(
        user_id=session['user_id'], domain=domain, course_title=title
    ).first()
    total_modules = len(json.loads(course.modules_json))
    completed = json.loads(enrollment.modules_completed_json or "[]") if enrollment else []
    if len(completed) < total_modules:
        return jsonify({"error": "Finish every module before taking the final exam."}), 400

    try:
        quiz = _get_or_create_cert_quiz(course)
    except RateLimitError:
        return jsonify({"error": "AI is busy right now. Please try again in a moment.", "retry": True}), 429
    except (json.JSONDecodeError, ValueError) as e:
        print("Certification exam generation error:", e)
        return jsonify({"error": "Couldn't generate the exam right now. Please try again."}), 502

    questions = json.loads(quiz.questions_json)
    client_questions = [
        {"id": q["id"], "question": q["question"], "options": q["options"]} for q in questions
    ]
    return jsonify({"questions": client_questions, "total_marks": quiz.total_marks}), 200


@app.route('/api/certificates/submit-quiz', methods=['POST'])
def api_certificates_submit_quiz():
    if 'user_id' not in session:
        return jsonify({"error": "Please log in first."}), 401

    data = request.get_json(silent=True) or {}
    domain = (data.get("domain") or "").strip()
    title = (data.get("title") or "").strip()
    answers = data.get("answers") or {}
    if not domain or not title:
        return jsonify({"error": "Missing domain or title."}), 400

    course = CertificationCourse.query.filter_by(domain=domain, title=title).first()
    if not course:
        return jsonify({"error": "Course not found."}), 404

    quiz = CertificationQuiz.query.filter_by(course_id=course.id).first()
    if not quiz:
        return jsonify({"error": "Exam not generated yet."}), 400

    enrollment = CertificationEnrollment.query.filter_by(
        user_id=session['user_id'], domain=domain, course_title=title
    ).first()
    if not enrollment:
        return jsonify({"error": "Not enrolled in this course."}), 404

    questions = json.loads(quiz.questions_json)
    score = sum(
        1 for q in questions
        if str(answers.get(q["id"])) == str(q.get("correct_index"))
    )
    total = len(questions)
    passed = total > 0 and (score / total) >= CERTIFICATION_PASS_THRESHOLD

    enrollment.quiz_score = score
    enrollment.quiz_total = total
    enrollment.quiz_attempts = (enrollment.quiz_attempts or 0) + 1

    certificate_code = None
    if passed:
        enrollment.status = "completed"
        enrollment.completed_at = datetime.utcnow()
        existing_cert = Certificate.query.filter_by(
            user_id=session['user_id'], domain=domain, course_title=title
        ).first()
        if not existing_cert:
            existing_cert = Certificate(
                user_id=session['user_id'], domain=domain, course_title=title,
                certificate_code=_generate_certificate_code(),
            )
            db.session.add(existing_cert)
        certificate_code = existing_cert.certificate_code

    db.session.commit()

    return jsonify({
        "passed": passed, "score": score, "total": total,
        "certificate_code": certificate_code,
    }), 200


@app.route('/certificates/download/<certificate_code>')
def download_certificate(certificate_code):
    user = User.query.get(session.get('user_id'))
    if not user:
        return redirect(url_for('login'))

    cert = Certificate.query.filter_by(certificate_code=certificate_code, user_id=user.id).first()
    if not cert:
        flash("Certificate not found.")
        return redirect(url_for('certificates'))

    try:
        pdf_bytes = _render_certificate_pdf(user, cert.course_title, cert.domain, cert.certificate_code, cert.issued_at)
    except ImportError:
        flash("Certificate PDF generation isn't available right now — the reportlab package needs to be installed.")
        return redirect(url_for('certificates'))

    from flask import Response
    safe_title = "".join(c if c.isalnum() or c in " -_" else "" for c in cert.course_title).strip().replace(" ", "_")
    return Response(
        pdf_bytes, mimetype="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="CareerOS_Certificate_{safe_title}.pdf"'},
    )


def _ensure_notification_pref_columns():
    """db.create_all() only creates missing tables, it won't add columns to
    a 'users' table that already exists from before this feature — so on
    an existing dev/prod database notify_career/notify_network would be
    silently missing. This adds them if needed, defaulting existing rows
    to enabled (matches the model's default=True)."""
    from sqlalchemy import inspect, text
    inspector = inspect(db.engine)
    existing_cols = {c['name'] for c in inspector.get_columns('users')}
    with db.engine.begin() as conn:
        if 'notify_career' not in existing_cols:
            conn.execute(text('ALTER TABLE users ADD COLUMN notify_career BOOLEAN DEFAULT 1'))
        if 'notify_network' not in existing_cols:
            conn.execute(text('ALTER TABLE users ADD COLUMN notify_network BOOLEAN DEFAULT 1'))


def _ensure_plan_columns():
    """Same reasoning as _ensure_notification_pref_columns() above — an
    existing 'users' table won't get the new payments columns from
    db.create_all() alone."""
    from sqlalchemy import inspect, text
    inspector = inspect(db.engine)
    existing_cols = {c['name'] for c in inspector.get_columns('users')}
    with db.engine.begin() as conn:
        if 'plan' not in existing_cols:
            conn.execute(text("ALTER TABLE users ADD COLUMN plan VARCHAR(20) DEFAULT 'free'"))
        if 'billing_cycle' not in existing_cols:
            conn.execute(text('ALTER TABLE users ADD COLUMN billing_cycle VARCHAR(10)'))
        if 'razorpay_customer_id' not in existing_cols:
            conn.execute(text('ALTER TABLE users ADD COLUMN razorpay_customer_id VARCHAR(64)'))


def _ensure_dummy_payment_columns():
    """Same reasoning as the other _ensure_*_columns() helpers — an existing
    'payments' table won't get the dummy-gateway columns from db.create_all()
    alone."""
    from sqlalchemy import inspect, text
    inspector = inspect(db.engine)
    existing_cols = {c['name'] for c in inspector.get_columns('payments')}
    with db.engine.begin() as conn:
        if 'gateway' not in existing_cols:
            conn.execute(text("ALTER TABLE payments ADD COLUMN gateway VARCHAR(20) DEFAULT 'razorpay'"))
        if 'method' not in existing_cols:
            conn.execute(text('ALTER TABLE payments ADD COLUMN method VARCHAR(20)'))
        if 'transaction_id' not in existing_cols:
            conn.execute(text('ALTER TABLE payments ADD COLUMN transaction_id VARCHAR(64)'))
        if 'failure_reason' not in existing_cols:
            conn.execute(text('ALTER TABLE payments ADD COLUMN failure_reason VARCHAR(255)'))


def _ensure_otp_purpose_column():
    """Same reasoning as the other _ensure_*_columns() helpers — an existing
    'otp_verification' table won't get the new 'purpose' column from
    db.create_all() alone. Existing (signup) rows default to 'signup'."""
    from sqlalchemy import inspect, text
    inspector = inspect(db.engine)
    existing_cols = {c['name'] for c in inspector.get_columns('otp_verification')}
    with db.engine.begin() as conn:
        if 'purpose' not in existing_cols:
            conn.execute(text("ALTER TABLE otp_verification ADD COLUMN purpose VARCHAR(20) DEFAULT 'signup'"))


@app.route('/static/uploads/resumes/<path:filename>')
def serve_uploaded_resume(filename):
    return send_from_directory(UPLOAD_FOLDER, filename)


@app.route('/static/uploads/posts/<path:filename>')
def serve_uploaded_post_image(filename):
    return send_from_directory(POST_IMAGES_FOLDER, filename)


_db_initialized = False


def init_database():
    global _db_initialized
    if _db_initialized:
        return
    if is_production():
        if not app.config.get("SECRET_KEY"):
            raise RuntimeError(
                "SECRET_KEY environment variable is required in production. Set a long, random SECRET_KEY in your environment/Vercel settings."
            )
        if os.getenv("VERCEL") == "1" and not (
            os.getenv("DATABASE_URL")
            or os.getenv("MYSQL_URL")
            or os.getenv("POSTGRES_URL")
        ):
            raise RuntimeError(
                "DATABASE_URL is required on Vercel. Configure a hosted database (MySQL or PostgreSQL) in Vercel environment variables."
            )
    with app.app_context():
        try:
            with db.engine.connect() as conn:
                pass
        except Exception as exc:
            _db_initialized = False
            print(f"Database not reachable: {exc}")
            if is_production():
                raise RuntimeError(f"Database connection failed: {exc}") from exc
            return

        db.create_all()
        _ensure_notification_pref_columns()
        _ensure_plan_columns()
        _ensure_dummy_payment_columns()
        _ensure_otp_purpose_column()
        seed_companies_from_jobs()
    _db_initialized = True


@app.before_request
def _ensure_db_ready():
    global _db_initialized
    if not _db_initialized:
        init_database()


if os.getenv("VERCEL") != "1":
    try:
        init_database()
    except Exception as exc:
        print(f"Database init notice: {exc}")


if __name__ == '__main__':
    debug = not is_production()
    app.run(host="0.0.0.0", debug=debug)




