# app/services/user_service.py
from ..db import users_col
from bson import ObjectId
import datetime
from typing import Optional, Dict, Any
from pymongo.errors import DuplicateKeyError

async def ensure_user_on_send(phone: str, now: datetime.datetime):
    await users_col.update_one(
        {"phone": phone},
        {"$setOnInsert": {"phone": phone, "created_at": now, "is_verified": False},
         "$set": {"last_otp_sent_at": now}},
        upsert=True
    )

async def create_or_attach_user_id(phone: str, now: datetime.datetime) -> Dict[str, Any]:
    """
    Ensure user exists and has a string hex user_id. Return the user doc (without _id).
    """
    user_doc = await users_col.find_one({"phone": phone})
    if not user_doc:
        new_user = {
            "user_id": str(ObjectId()),
            "phone": phone,
            "created_at": now,
            "is_verified": True,
            "last_login": now,
        }
        try:
            await users_col.insert_one(new_user)
            return new_user
        except DuplicateKeyError:
            # extremely unlikely; fetch existing
            user_doc = await users_col.find_one({"phone": phone})
            return user_doc
    else:
        if "user_id" not in user_doc:
            gen_id = str(ObjectId())
            try:
                await users_col.update_one({"phone": phone}, {"$set": {"user_id": gen_id}})
                user_doc["user_id"] = gen_id
            except DuplicateKeyError:
                # collision: get the current doc
                user_doc = await users_col.find_one({"phone": phone})
        await users_col.update_one({"phone": phone}, {"$set": {"is_verified": True, "last_login": now}})
        return await users_col.find_one({"phone": phone}, {"_id": 0})
