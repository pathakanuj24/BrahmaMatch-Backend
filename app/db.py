# app/db.py
from motor.motor_asyncio import AsyncIOMotorClient
import logging
from .config import MONGODB_URI, DB_NAME

logger = logging.getLogger("Brahmamatch-backend")

if not MONGODB_URI:
    logger.warning("MONGODB_URI not set; defaulting to mongodb://localhost:27017 for local dev.")
    _uri = "mongodb://localhost:27017"
else:
    _uri = MONGODB_URI

client = AsyncIOMotorClient(_uri)
db = client[DB_NAME]

users_col = db["Users"]
profiles_col = db["Profiles"]   # <-- new


async def ensure_indexes():
    await users_col.create_index("phone", unique=True)
    await users_col.create_index("user_id", unique=True, sparse=True)
    await profiles_col.create_index("user_id", unique=True)

