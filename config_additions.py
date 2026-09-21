"""
Add these lines to your existing config.py, inside the Config class
(same pattern as your other Config.XXX_API_KEY attributes), and add
the matching keys to your .env file.
"""

# Inside class Config: ...
#     RAZORPAY_KEY_ID = os.environ.get('RAZORPAY_KEY_ID')
#     RAZORPAY_KEY_SECRET = os.environ.get('RAZORPAY_KEY_SECRET')
#     RAZORPAY_WEBHOOK_SECRET = os.environ.get('RAZORPAY_WEBHOOK_SECRET')

# .env additions:
#     RAZORPAY_KEY_ID=rzp_test_xxxxxxxx
#     RAZORPAY_KEY_SECRET=xxxxxxxxxxxxxxxx
#     RAZORPAY_WEBHOOK_SECRET=xxxxxxxxxxxxxxxx
#
# Get test-mode keys free at https://dashboard.razorpay.com (Settings > API Keys).
# Test mode works fully without KYC — switch to rzp_live_ keys once Razorpay
# activates your account for real payments.
