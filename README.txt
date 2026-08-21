KAKASHI TOPUP CENTER - Integrated Part 1 + Part 2 + Backend + SQLite

1. Install Python 3.10+.
2. Open CMD in this folder.
3. Run: pip install -r requirements.txt
4. Run: python app.py
5. Open: http://127.0.0.1:5000

Admin:
Email: admin@kakashi.com
Password: admin123

The website design is based on your supplied Part 1 and Part 2. Member accounts,
orders, statuses, admin statistics and receipt data are stored in SQLite.
Change the admin password and SECRET_KEY before publishing.

WhatsApp buttons open WhatsApp with the order/customer message. Actual automatic
server-side WhatsApp delivery and real email sending require API credentials.


ADMIN FIX V3: includes robust same-origin sessions and a local-only admin fallback key for the built-in admin account.


WhatsApp: Confirm opens a WhatsApp chat with the customer and pre-fills the confirmation message. WhatsApp requires the user/admin to press Send; a normal website cannot silently send WhatsApp messages without an official WhatsApp Business API integration.
