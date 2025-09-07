# config.py
from dotenv import load_dotenv
import os

# load .env into environment
load_dotenv()

# Mongo
MONGODB_URI = os.getenv("MONGODB_URI", "")  # keep empty default to detect missing
DB_NAME = os.getenv("DB_NAME", "BrahminMatch")

# Twilio (may be None in local dev)
TW_SID = os.getenv("TWILIO_ACCOUNT_SID")
TW_AUTH = os.getenv("TWILIO_AUTH_TOKEN")
TW_VERIFY_SID = os.getenv("TWILIO_VERIFY_SID")

# JWT - require secret to be set in production
JWT_SECRET = os.getenv("JWT_SECRET")
if not JWT_SECRET:
    # fail early so token creation doesn't silently blow up later
    raise RuntimeError("JWT_SECRET env var not set. Set JWT_SECRET in your .env")

JWT_ALGORITHM = os.getenv("JWT_ALGORITHM", "HS256")
JWT_EXPIRES_MINUTES = int(os.getenv("JWT_EXPIRES_MINUTES", "60"))
