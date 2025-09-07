# app/routes/auth.py
from fastapi import APIRouter, HTTPException
from ..schemas import SendOTPIn, VerifyOTPIn
from ..utils import normalize_phone, create_jwt_token
from ..services.twilio_service import send_verification_sms, check_verification_code
from ..services.user_service import ensure_user_on_send, create_or_attach_user_id
import datetime

router = APIRouter(prefix="/auth", tags=["auth"])

@router.post("/send-otp", status_code=202)
async def send_otp(payload: SendOTPIn):
    phone = normalize_phone(payload.phone)
    now = datetime.datetime.now(datetime.timezone.utc)
    try:
        await ensure_user_on_send(phone, now)
    except Exception as e:
        raise HTTPException(status_code=500, detail="DB error")

    try:
        verification = send_verification_sms(phone)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Twilio error: {e}")

    return {"status": getattr(verification, "status", "unknown"), "message": "OTP send attempted."}

@router.post("/verify-otp")
async def verify_otp(payload: VerifyOTPIn):
    phone = normalize_phone(payload.phone)
    try:
        check = check_verification_code(phone, payload.code)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Verification failed: {e}")

    if getattr(check, "status", "").lower() != "approved":
        raise HTTPException(status_code=400, detail="Invalid OTP or verification not approved.")

    now = datetime.datetime.now(datetime.timezone.utc)
    try:
        created_user = await create_or_attach_user_id(phone, now)
    except Exception as e:
        raise HTTPException(status_code=500, detail="DB error creating user")

    token = create_jwt_token(phone)
    return {"status": "approved", "token": token, "user_id": created_user["user_id"]}
