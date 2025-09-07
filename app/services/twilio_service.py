# app/services/twilio_service.py
import logging
from twilio.rest import Client as TwilioClient
from ..config import TW_SID, TW_AUTH, TW_VERIFY_SID

logger = logging.getLogger("Brahmamatch-backend")

twilio_client = None
if TW_SID and TW_AUTH:
    try:
        twilio_client = TwilioClient(TW_SID, TW_AUTH)
    except Exception as e:
        logger.warning("Failed to init Twilio client: %s", e)
else:
    logger.warning("Twilio not configured; OTP sending will fail in dev.")

def send_verification_sms(phone: str):
    if not twilio_client or not TW_VERIFY_SID:
        raise RuntimeError("Twilio not configured")
    return twilio_client.verify.v2.services(TW_VERIFY_SID).verifications.create(to=phone, channel="sms")

def check_verification_code(phone: str, code: str):
    if not twilio_client or not TW_VERIFY_SID:
        raise RuntimeError("Twilio not configured")
    return twilio_client.verify.v2.services(TW_VERIFY_SID).verification_checks.create(to=phone, code=code)
