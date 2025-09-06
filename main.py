# main.py
import os
import datetime
from typing import Optional

from fastapi import FastAPI, HTTPException, status, Depends, Body
from pydantic import BaseModel, Field
from motor.motor_asyncio import AsyncIOMotorClient
from fastapi.middleware.cors import CORSMiddleware  # Add this import

from twilio.rest import Client as TwilioClient
import jwt
from dotenv import load_dotenv
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

load_dotenv()  # loads .env file if present

# Environment / config
MONGODB_URI = os.getenv("MONGODB_URI", "")
DB_NAME = os.getenv("DB_NAME", "users_db")
TW_SID = os.getenv("TWILIO_ACCOUNT_SID")
TW_AUTH = os.getenv("TWILIO_AUTH_TOKEN")
TW_VERIFY_SID = os.getenv("TWILIO_VERIFY_SID")  # your Verify Service SID
JWT_SECRET = os.getenv("JWT_SECRET", )
JWT_ALGORITHM = os.getenv("JWT_ALGORITHM", "HS256")
JWT_EXPIRES_MINUTES = int(os.getenv("JWT_EXPIRES_MINUTES", "60"))

if not all([TW_SID, TW_AUTH, TW_VERIFY_SID]):
    # We don't crash at import time to make local dev easier; but warn.
    print("WARNING: Twilio credentials (TWILIO_*) not fully set. OTP sending will fail until configured.")

# Init services
app = FastAPI(title="OTP Login User Service")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",  # React dev server
        "http://127.0.0.1:3000",  # Alternative localhost
        # Add your production frontend URL here when deploying
    ],
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["*"],
)
mongo = AsyncIOMotorClient(MONGODB_URI)
db = mongo[DB_NAME]
users_col = db["Users"]

twilio_client = TwilioClient(TW_SID, TW_AUTH) if TW_SID and TW_AUTH else None

security = HTTPBearer()

# Pydantic models
class SendOTPIn(BaseModel):
    phone: str = Field(..., example="+919876543210")

class VerifyOTPIn(BaseModel):
    phone: str = Field(..., example="+919876543210")
    code: str = Field(..., example="123456")

class UserOut(BaseModel):
    phone: str
    is_verified: bool
    created_at: datetime.datetime
    last_login: Optional[datetime.datetime] = None

# Utility functions
def normalize_phone(phone: str) -> str:
    """Normalize phone number.  
       - If E.164 (starts with +) return as is.
       - If 10 digits, assume +91 (India) and prefix.
       - If starts with 0 and length 11, replace leading 0 with +91.
       Adjust logic if you want different default behavior.
    """
    phone = phone.strip()
    if phone.startswith("+"):
        return phone
    digits = "".join(ch for ch in phone if ch.isdigit())
    if len(digits) == 10:
        return "+91" + digits
    if len(digits) == 11 and digits.startswith("0"):
        return "+91" + digits[1:]
    # fallback: add plus sign if missing
    return "+" + digits

def create_jwt_token(phone: str) -> str:
    now = datetime.datetime.utcnow()
    payload = {
        "sub": phone,
        "iat": now,
        "exp": now + datetime.timedelta(minutes=JWT_EXPIRES_MINUTES),
    }
    token = jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)
    # PyJWT in some versions returns bytes
    if isinstance(token, bytes):
        token = token.decode("utf-8")
    return token

async def ensure_indexes():
    # ensure a unique index on phone
    await users_col.create_index("phone", unique=True)

@app.on_event("startup")
async def on_startup():
    await ensure_indexes()

# Endpoints
@app.post("/auth/send-otp", status_code=202)
async def send_otp(payload: SendOTPIn):
    phone = normalize_phone(payload.phone)
    # Upsert user record (create if not exists)
    now = datetime.datetime.utcnow()
    await users_col.update_one(
        {"phone": phone},
        {
            "$setOnInsert": {"phone": phone, "created_at": now, "is_verified": False},
            "$set": {"last_otp_sent_at": now}
        },
        upsert=True
    )

    if not twilio_client:
        raise HTTPException(status_code=500, detail="Twilio client not configured on server.")

    try:
        verification = twilio_client.verify.v2.services(TW_VERIFY_SID).verifications.create(
            to=phone, channel="sms"
        )
    except Exception as e:
        # Twilio error (bad number, not supported country, missing creds, etc.)
        raise HTTPException(status_code=500, detail=f"Twilio error: {str(e)}")

    # Twilio returns status "pending" when message sent
    return {"status": verification.status, "message": "OTP sent (if phone reachable)."}

@app.post("/auth/verify-otp")
async def verify_otp(payload: VerifyOTPIn):
    phone = normalize_phone(payload.phone)

    if not twilio_client:
        raise HTTPException(status_code=500, detail="Twilio client not configured on server.")

    try:
        check = twilio_client.verify.v2.services(TW_VERIFY_SID).verification_checks.create(
            to=phone, code=payload.code
        )
    except Exception as e:
        # Twilio error (bad request, malformed code, etc.)
        raise HTTPException(status_code=400, detail=f"Verification failed: {str(e)}")

    # check.status is often 'approved' or 'pending'
    if getattr(check, "status", "").lower() != "approved":
        raise HTTPException(status_code=400, detail="Invalid OTP or verification not approved.")

    # Mark user verified and set last_login
    now = datetime.datetime.utcnow()
    result = await users_col.update_one(
        {"phone": phone},
        {"$set": {"is_verified": True, "last_login": now}},
        upsert=True,
    )
    # Return JWT token for the session
    token = create_jwt_token(phone)
    return {"status": "approved", "token": token}

# Example protected endpoint
async def get_current_user(creds: HTTPAuthorizationCredentials = Depends(security)):
    token = creds.credentials
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        phone = payload.get("sub")
        if not phone:
            raise HTTPException(status_code=401, detail="Invalid token (no subject).")
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expired.")
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid token.")

    user_doc = await users_col.find_one({"phone": phone}, {"_id": 0})
    if not user_doc:
        raise HTTPException(status_code=404, detail="User not found.")
    return user_doc

@app.get("/me", response_model=UserOut)
async def me(user=Depends(get_current_user)):
    # user is the raw document; Pydantic will validate needed fields
    return user
