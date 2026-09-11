KAKASHI TOPUP CENTER - MANUAL TOP-UP EDITION

This build includes secure SMS OTP authentication using Text.lk.

1) Install Python 3.10+
2) Open CMD in this folder
3) Run: pip install -r requirements.txt
4) Configure the environment variables below
5) Run: python app.py
6) Open: http://127.0.0.1:5000

TEXT.LK SMS OTP CONFIGURATION
Set these environment variables on the SERVER (never in index.html):
  TEXTLK_API_TOKEN=your_textlk_bearer_token
  TEXTLK_SENDER_ID=your_sender_id

The app uses Text.lk's Bearer-token POST endpoint:
  https://app.text.lk/api/v3/sms/send

OTP FLOW
Customer registration:
  Register -> SMS OTP -> Verify OTP -> Account verified -> Login

Member login:
  Email + Password -> SMS OTP -> Verify OTP -> Logged in

Forgot password:
  Email/Mobile -> SMS OTP -> New password

SECURITY
- OTPs are stored as SHA-256 hashes, not plaintext.
- OTP expires after 5 minutes.
- Maximum 5 incorrect attempts per OTP.
- Resend is rate-limited to once per 60 seconds.
- SMS credentials stay on the backend and are never sent to the browser.
- Admin login also uses the admin mobile number for OTP.
- The frontend no longer contains the admin API key.
- Change SECRET_KEY, ADMIN_PASSWORD and ADMIN_API_KEY using environment variables before publishing.
- Use HTTPS in production.

ADMIN
The existing admin account/role system is preserved. The admin password is checked first, then an OTP is sent to ADMIN_WHATSAPP.

EXISTING FEATURES
Wallet, orders, admin order management, manual top-up flow, UID validation, receipts and order history are preserved.

IMPORTANT
If TEXTLK_API_TOKEN or TEXTLK_SENDER_ID is missing, OTP sending will fail with a clear server-side configuration error. Do not put the Text.lk token in frontend JavaScript or commit it to GitHub.
