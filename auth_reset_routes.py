"""
Forgot-password + login-via-OTP flow for CareerOS.
--------------------------------------------------
This is written to be merged into your existing app.py. It assumes you
already have:
  - a Flask `app` instance
  - a SQLAlchemy `db` instance
  - a `User` model with at least: id, email, password_hash, name
  - werkzeug's generate_password_hash/check_password_hash (or similar)
  - render_template, flash, redirect, url_for, request already imported

Everywhere you see "# >>> ADAPT" is a spot to wire up to your real code.
"""

import secrets
import random
import hmac
from datetime import datetime, timedelta

from flask import render_template, request, redirect, url_for, flash, session
from flask_mail import Mail, Message
from werkzeug.security import generate_password_hash

# ── 1. FLASK-MAIL CONFIG ────────────────────────────────────────────
# Add these to your app config (values from environment variables in
# production — never hardcode credentials).
#
# app.config['MAIL_SERVER'] = 'smtp.gmail.com'          # or your SMTP host
# app.config['MAIL_PORT'] = 587
# app.config['MAIL_USE_TLS'] = True
# app.config['MAIL_USERNAME'] = os.environ['MAIL_USERNAME']
# app.config['MAIL_PASSWORD'] = os.environ['MAIL_PASSWORD']   # app password, not your real password
# app.config['MAIL_DEFAULT_SENDER'] = ('CareerOS', os.environ['MAIL_USERNAME'])
#
# mail = Mail(app)

# >>> ADAPT: import your real `app`, `db`, `User`, `mail` instead of these placeholders
# from app import app, db, mail
# from models import User

TOKEN_TTL_MINUTES = 15


# ── 2. USER MODEL ADDITIONS ─────────────────────────────────────────
# Add these columns to your existing User model (then run a migration,
# e.g. `flask db migrate && flask db upgrade` if you're on Alembic):
#
#   reset_token = db.Column(db.String(64), nullable=True, index=True)
#   reset_token_expiry = db.Column(db.DateTime, nullable=True)
#   otp_code = db.Column(db.String(6), nullable=True)
#   otp_expiry = db.Column(db.DateTime, nullable=True)
#
# reset_token doubles as the identifier for BOTH the "reset password" link
# and the "login with OTP" link in the email — one token, two possible
# next steps. otp_code is the separate 6-digit secret the user has to type.


# ── 3. HELPERS ───────────────────────────────────────────────────────
def _generate_token():
    return secrets.token_urlsafe(32)


def _generate_otp():
    return f"{random.randint(0, 999999):06d}"


def _send_forgot_password_email(user, token, otp):
    reset_url = url_for('reset_password', token=token, _external=True)
    otp_url = url_for('login_otp', token=token, _external=True)

    msg = Message(
        subject="Reset your CareerOS password",
        recipients=[user.email],
    )
    msg.html = render_template(
        'email_forgot_password.html',
        name=user.name,
        reset_url=reset_url,
        otp_url=otp_url,
        otp=otp,
        ttl_minutes=TOKEN_TTL_MINUTES,
    )
    mail.send(msg)  # >>> ADAPT: `mail` = your Flask-Mail instance


# ── 4. ROUTES ─────────────────────────────────────────────────────────

@app.route('/forgot-password', methods=['GET', 'POST'])
def forgot_password():
    if request.method == 'POST':
        email = request.form.get('email', '').strip().lower()

        user = User.query.filter_by(email=email).first()  # >>> ADAPT to your query style
        if user:
            token = _generate_token()
            otp = _generate_otp()
            now = datetime.utcnow()

            user.reset_token = token
            user.reset_token_expiry = now + timedelta(minutes=TOKEN_TTL_MINUTES)
            user.otp_code = otp
            user.otp_expiry = now + timedelta(minutes=TOKEN_TTL_MINUTES)
            db.session.commit()

            _send_forgot_password_email(user, token, otp)

        # Always show the same "check your inbox" state, whether or not the
        # email exists — this avoids leaking which emails are registered.
        return render_template('forgot_password.html', sent=True, email=email)

    return render_template('forgot_password.html', sent=False)


@app.route('/reset-password/<token>', methods=['GET', 'POST'])
def reset_password(token):
    user = User.query.filter_by(reset_token=token).first()  # >>> ADAPT

    if not user or not user.reset_token_expiry or user.reset_token_expiry < datetime.utcnow():
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

        user.password_hash = generate_password_hash(password)  # >>> ADAPT field name if different

        # Invalidate both the reset token and the OTP — either one being
        # used should retire the other, since they were issued together.
        user.reset_token = None
        user.reset_token_expiry = None
        user.otp_code = None
        user.otp_expiry = None
        db.session.commit()

        flash('Your password has been reset. Please log in.')
        return redirect(url_for('login'))

    return render_template('reset_password.html', token=token)


@app.route('/login-otp/<token>', methods=['GET', 'POST'])
def login_otp(token):
    user = User.query.filter_by(reset_token=token).first()  # >>> ADAPT

    if not user or not user.otp_expiry or user.otp_expiry < datetime.utcnow():
        flash('That code has expired. Please request a new one.')
        return redirect(url_for('forgot_password'))

    if request.method == 'POST':
        submitted_otp = request.form.get('otp', '').strip()

        # Constant-time comparison to avoid timing attacks on the OTP.
        if user.otp_code and hmac.compare_digest(submitted_otp, user.otp_code):
            # Log the user in — adapt to however your app manages sessions
            # (Flask-Login's login_user(user), or manual session as below).
            session['user_id'] = user.id  # >>> ADAPT to your auth system, e.g. login_user(user)

            # Invalidate both the OTP and the reset token after use.
            user.reset_token = None
            user.reset_token_expiry = None
            user.otp_code = None
            user.otp_expiry = None
            db.session.commit()

            return redirect(url_for('dashboard'))  # >>> ADAPT to your post-login route

        flash('That code is incorrect. Please try again.')
        return render_template('login_otp.html', token=token, email=user.email)

    return render_template('login_otp.html', token=token, email=user.email)
