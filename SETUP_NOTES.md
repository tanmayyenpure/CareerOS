# CareerOS payments — what changed & how to deploy

## Files here
- **app.py** — your uploaded app.py with payments fully patched in (diffed against your actual code, not a generic scaffold). Compiles clean (`python3 -m py_compile` passes).
- **plans.py** — new file, pricing config. Put it next to app.py.
- **pricing.html** — your uploaded pricing.html with working checkout wired in.
- **config_additions.py** — 3 lines to add to your real `config.py` + `.env` (config.py wasn't in your upload, so this is a snippet, not a full file).

## What actually changed in app.py
1. Added `razorpay`, `hmac`, `hashlib` imports + `plans.py` import
2. Initialized `razorpay_client` next to your Gemini/OpenRouter clients — logs a warning instead of crashing if keys aren't set yet, so the rest of the app still runs
3. **User model**: added `plan`, `billing_cycle`, `razorpay_customer_id` columns. Left `is_pro` and `pro_expires_at` alone and kept them in sync — your existing `/api/chat` free-limit check (line ~2302) needed zero changes
4. Added a `Payment` model (order/verification tracking)
5. `/pricing` route now passes `current_user` (or `None`) and `razorpay_key_id` to the template
6. Three new routes: `/api/payments/create-order`, `/api/payments/verify`, `/api/payments/webhook/razorpay` — same `session['user_id']` auth pattern as the rest of your app, not Flask-Login
7. `_ensure_plan_columns()` — same ALTER-TABLE-if-missing pattern as your existing `_ensure_notification_pref_columns()`, called in the same `with app.app_context()` block

## Steps to actually deploy
1. Install: `pip install razorpay`
2. Get test keys: https://dashboard.razorpay.com → Settings → API Keys (no KYC needed for test mode)
3. Add to `.env`:
   ```
   RAZORPAY_KEY_ID=rzp_test_xxxxxxxx
   RAZORPAY_KEY_SECRET=xxxxxxxxxxxxxxxx
   RAZORPAY_WEBHOOK_SECRET=xxxxxxxxxxxxxxxx
   ```
4. Add the matching 3 lines to your `Config` class (see `config_additions.py`)
5. Drop `plans.py` next to your real `app.py`
6. Replace your real `app.py` and `templates/pricing.html` with the versions here — or diff them if you've made other local changes since you uploaded
7. Restart the app. `_ensure_plan_columns()` runs automatically on startup and adds the new columns to your existing `users` table.
8. Test with card `4111 1111 1111 1111`, any future expiry, any CVV, any OTP

## Not yet wired (flag if you want these)
- **Webhook isn't registered in Razorpay's dashboard yet** — go to Settings → Webhooks, add `https://yourdomain.com/api/payments/webhook/razorpay`, select `payment.captured` + `payment.failed`
- **No daily expiry job** — `downgrade_expired_plans()` exists in app.py but nothing calls it yet. Wire it to a cron job, Flask-APScheduler, or your host's scheduled tasks
- **Team is self-checkout**, same flow as Pro. If you'd rather keep Team as a sales-contact button, swap its `onclick` back to a mailto/contact link
