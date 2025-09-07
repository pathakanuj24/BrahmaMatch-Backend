
# main.py
import datetime
import logging
from typing import Optional, List, Any, Dict

from fastapi import FastAPI, HTTPException, Depends, Query, Path, Body, status
from pydantic import BaseModel, Field, constr
from motor.motor_asyncio import AsyncIOMotorClient
from fastapi.middleware.cors import CORSMiddleware

from twilio.rest import Client as TwilioClient
import jwt
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from bson import ObjectId


from app.config import (
    MONGODB_URI,
    DB_NAME,
    TW_SID,
    TW_AUTH,
    TW_VERIFY_SID,
    JWT_SECRET,
    JWT_ALGORITHM,
    JWT_EXPIRES_MINUTES,
)

# -------- logger ----------
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("brahmamatch-backend")

# -------- FastAPI app ----------
app = FastAPI(title="OTP Login User Service")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://127.0.0.1:3000",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# -------- Database client (defensive) ----------
if not MONGODB_URI:
    logger.warning(
        "MONGODB_URI not set; defaulting to mongodb://localhost:27017 for local dev."
    )
    _mongodb_uri = "mongodb://localhost:27017"
else:
    _mongodb_uri = MONGODB_URI

try:
    mongo = AsyncIOMotorClient(_mongodb_uri)
    db = mongo[DB_NAME]
    users_col = db["Users"]
except Exception as e:
    raise RuntimeError(f"Failed to create Mongo client with MONGODB_URI={_mongodb_uri!r}: {e}")

# -------- Twilio client (optional in local dev) ----------
twilio_client = None
if TW_SID and TW_AUTH:
    try:
        twilio_client = TwilioClient(TW_SID, TW_AUTH)
    except Exception as e:
        logger.warning("Failed to initialize Twilio client: %s", e)
else:
    logger.warning("Twilio credentials not fully set. OTP sending will fail until configured.")

# -------- security ----------
security = HTTPBearer()

# -------- Pydantic models ----------
phone_var = constr(strip_whitespace=True, min_length=6)

class SendOTPIn(BaseModel):
    phone: phone_var = Field(..., example="+919876543210")


class VerifyOTPIn(BaseModel):
    phone: phone_var = Field(..., example="+919876543210")
    code: str = Field(..., example="123456")


# Minimal user output shape per your request:
class UserOut(BaseModel):
    user_id: str
    phone: str
    is_verified: bool
    created_at: datetime.datetime
    last_login: Optional[datetime.datetime] = None


# -------- Utility functions ----------
def normalize_phone(phone: str) -> str:
    phone = phone.strip()
    if phone.startswith("+"):
        return phone
    digits = "".join(ch for ch in phone if ch.isdigit())
    if len(digits) == 10:
        return "+91" + digits
    if len(digits) == 11 and digits.startswith("0"):
        return "+91" + digits[1:]
    return "+" + digits


def create_jwt_token(phone: str) -> str:
    now = datetime.datetime.now(datetime.timezone.utc)
    payload = {
        "sub": phone,
        "iat": now,
        "exp": now + datetime.timedelta(minutes=JWT_EXPIRES_MINUTES),
    }
    token = jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)
    if isinstance(token, bytes):
        token = token.decode("utf-8")
    return token


async def ensure_indexes():
    # unique index on phone and user_id
    await users_col.create_index("phone", unique=True)
    await users_col.create_index("user_id", unique=True, sparse=True)


# -------- Startup / Health checks ----------
@app.on_event("startup")
async def on_startup():
    try:
        await db.command("ping")
        logger.info("MongoDB ping successful.")
    except Exception as e:
        logger.error("MongoDB ping failed: %s", e)

    try:
        await ensure_indexes()
        logger.info("Indexes ensured on Users collection.")
    except Exception as e:
        logger.error("Failed to ensure indexes: %s", e)


# -------- Endpoints: OTP flow & user id creation ----------
@app.post("/auth/send-otp", status_code=202)
async def send_otp(payload: SendOTPIn):
    phone = normalize_phone(payload.phone)

    now = datetime.datetime.now(datetime.timezone.utc)
    try:
        # NOTE: do NOT create profile/full_name fields here (per request).
        await users_col.update_one(
            {"phone": phone},
            {
                "$setOnInsert": {
                    "phone": phone,
                    "created_at": now,
                    "is_verified": False,
                },
                "$set": {"last_otp_sent_at": now},
            },
            upsert=True,
        )
    except Exception as e:
        logger.error("DB upsert failed for phone %s: %s", phone, e)
        raise HTTPException(status_code=500, detail="Database error while saving user record.")

    if not twilio_client or not TW_VERIFY_SID:
        raise HTTPException(
            status_code=500,
            detail="Twilio client or Verify service not configured on server. OTP cannot be sent.",
        )

    try:
        verification = twilio_client.verify.v2.services(TW_VERIFY_SID).verifications.create(
            to=phone, channel="sms"
        )
    except Exception as e:
        logger.exception("Twilio verify create error for %s: %s", phone, e)
        raise HTTPException(status_code=500, detail=f"Twilio error: {str(e)}")

    return {"status": getattr(verification, "status", "unknown"), "message": "OTP send attempted."}


@app.post("/auth/verify-otp")
async def verify_otp(payload: VerifyOTPIn):
    phone = normalize_phone(payload.phone)

    if not twilio_client or not TW_VERIFY_SID:
        raise HTTPException(status_code=500, detail="Twilio client or Verify service not configured on server.")

    try:
        check = twilio_client.verify.v2.services(TW_VERIFY_SID).verification_checks.create(
            to=phone, code=payload.code
        )
    except Exception as e:
        logger.exception("Twilio verification_checks error for %s: %s", phone, e)
        raise HTTPException(status_code=400, detail=f"Verification failed: {str(e)}")

    status_value = getattr(check, "status", "").lower()
    if status_value != "approved":
        raise HTTPException(status_code=400, detail="Invalid OTP or verification not approved.")

    now = datetime.datetime.now(datetime.timezone.utc)
    try:
        user_doc = await users_col.find_one({"phone": phone})
        if not user_doc:
            # create minimal user doc (no profile/full_name etc)
            new_user = {
                "user_id": str(ObjectId()),  # 24-char hex string
                "phone": phone,
                "created_at": now,
                "is_verified": True,
                "last_login": now,
            }
            await users_col.insert_one(new_user)
            created_user = new_user
        else:
            # if exists but no user_id assigned, assign one
            if "user_id" not in user_doc:
                gen_id = str(ObjectId())
                await users_col.update_one({"phone": phone}, {"$set": {"user_id": gen_id}})
                user_doc["user_id"] = gen_id
            # update verified status + last_login
            await users_col.update_one({"phone": phone}, {"$set": {"is_verified": True, "last_login": now}})
            # fetch latest doc
            created_user = await users_col.find_one({"phone": phone}, {"_id": 0})
    except Exception as e:
        logger.exception("Failed to set user_id or update user after verification for %s: %s", phone, e)
        raise HTTPException(status_code=500, detail="Database error while creating user record.")

    token = create_jwt_token(phone)
    # return token and user_id so front-end/Postman can use it immediately
    return {"status": "approved", "token": token, "user_id": created_user["user_id"]}


# -------- Protected helper & endpoint ----------
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
    # ensure returned doc matches minimal shape
    user_response = {
        "user_id": user_doc.get("user_id"),
        "phone": user_doc["phone"],
        "is_verified": user_doc.get("is_verified", False),
        "created_at": user_doc.get("created_at"),
        "last_login": user_doc.get("last_login"),
    }
    print("Current user fetched:", user_response)
    return user_response


@app.get("/me", response_model=UserOut)
async def me(user=Depends(get_current_user)):
    return user


# -------- CRUD endpoints for users (admin-style) ----------
@app.get("/users", response_model=List[UserOut])
async def list_users(skip: int = 0, limit: int = Query(50, le=200)):
    cursor = users_col.find({}, {"_id": 0}).skip(skip).limit(limit).sort("created_at", 1)
    docs = await cursor.to_list(length=limit)
    # normalize to minimal shape
    results = []
    for d in docs:
        results.append(
            {
                "user_id": d.get("user_id"),
                "phone": d.get("phone"),
                "is_verified": d.get("is_verified", False),
                "created_at": d.get("created_at"),
                "last_login": d.get("last_login"),
            }
        )
    return results


@app.get("/users/{user_id}", response_model=UserOut)
async def get_user_by_id(user_id: str = Path(...)):
    doc = await users_col.find_one({"user_id": user_id}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail="User not found.")
    return {
        "user_id": doc.get("user_id"),
        "phone": doc.get("phone"),
        "is_verified": doc.get("is_verified", False),
        "created_at": doc.get("created_at"),
        "last_login": doc.get("last_login"),
    }


@app.delete("/users/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_user(user_id: str = Path(...)):
    res = await users_col.delete_one({"user_id": user_id})
    if res.deleted_count == 0:
        raise HTTPException(status_code=404, detail="User not found.")
    return None



