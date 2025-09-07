# app/services/profile_service.py
from app.db import profiles_col
import datetime
from typing import Optional, Dict, Any
from pymongo.errors import DuplicateKeyError

async def create_or_update_profile(user_id: str, profile_data: Dict[str, Any]):
    now = datetime.datetime.now(datetime.timezone.utc)
    profile_data = {k: v for k, v in profile_data.items() if v is not None}
    profile_data["updated_at"] = now
    await profiles_col.update_one(
        {"user_id": user_id},
        {"$set": profile_data, "$setOnInsert": {"created_at": now, "user_id": user_id}},
        upsert=True,
    )
    return await profiles_col.find_one({"user_id": user_id}, {"_id": 0})

async def get_profile(user_id: str) -> Optional[Dict[str, Any]]:
    return await profiles_col.find_one({"user_id": user_id}, {"_id": 0})

async def delete_profile(user_id: str) -> bool:
    res = await profiles_col.delete_one({"user_id": user_id})
    return res.deleted_count > 0

async def add_profile_image(user_id: str, b64_str: str):
    now = datetime.datetime.now(datetime.timezone.utc)
    await profiles_col.update_one(
        {"user_id": user_id},
        {"$set": {"profile_image": b64_str, "updated_at": now}, "$setOnInsert": {"created_at": now, "user_id": user_id}},
        upsert=True,
    )
    return await get_profile(user_id)

async def add_gallery_image(user_id: str, b64_str: str):
    now = datetime.datetime.now(datetime.timezone.utc)
    await profiles_col.update_one(
        {"user_id": user_id},
        {"$push": {"gallery_images": b64_str}, "$setOnInsert": {"created_at": now, "user_id": user_id}},
        upsert=True,
    )
    return await get_profile(user_id)
