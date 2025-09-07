# app/routes/users.py
"""
User & Profile HTTP routes.

This module exposes:
- user-related endpoints (current user info, list users, get user by id)
- profile endpoints (owner-only create/read/update, admin-style CRUD)
- image upload endpoints (profile image + gallery image) which accept multipart file uploads
"""

from typing import Dict, List

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

import base64

from ..schemas import UserOut
from ..db import users_col
from ..utils import decode_jwt_token
from app.schemas import ProfileIn, ProfileOut
from app.services import profile_service  # ensure package import path matches

router = APIRouter(tags=["users"])
security = HTTPBearer()


async def get_current_user(creds: HTTPAuthorizationCredentials = Depends(security)) -> Dict:
    """
    Dependency to extract the current user from an Authorization Bearer token.

    Decodes the JWT token, reads the phone number from the token payload ("sub"),
    fetches the user document from `users_col` and returns a minimal user object.

    Raises:
        HTTPException(401) if the token is invalid or missing the subject.
        HTTPException(404) if the user is not found in the database.

    Returns:
        dict: Minimal user data with keys:
            - user_id (str)
            - phone (str)
            - is_verified (bool)
            - created_at (datetime)
            - last_login (datetime | None)
    """
    token = creds.credentials
    try:
        payload = decode_jwt_token(token)
        phone = payload.get("sub")
        if not phone:
            raise HTTPException(status_code=401, detail="Invalid token (no subject).")
    except Exception:
        # Hide decode errors from the client for security, return a generic 401.
        raise HTTPException(status_code=401, detail="Invalid token.")

    # Fetch user document by phone number
    user_doc = await users_col.find_one({"phone": phone}, {"_id": 0})
    if not user_doc:
        raise HTTPException(status_code=404, detail="User not found.")

    user_response = {
        "user_id": user_doc.get("user_id"),
        "phone": user_doc["phone"],
        "is_verified": user_doc.get("is_verified", False),
        "created_at": user_doc.get("created_at"),
        "last_login": user_doc.get("last_login"),
    }
    return user_response


@router.get("/user/me", response_model=UserOut)
async def me(user: Dict = Depends(get_current_user)):
    """
    Return minimal information about the current authenticated user.

    Uses the `get_current_user` dependency to obtain the user object from the JWT.
    """
    return user


@router.get("/users", response_model=List[UserOut])
async def list_users(skip: int = 0, limit: int = 50):
    """
    List users (admin-style). Pagination via `skip` and `limit`.

    This returns the minimal user document values that the frontend expects.
    """
    cursor = users_col.find({}, {"_id": 0}).skip(skip).limit(limit).sort("created_at", 1)
    docs = await cursor.to_list(length=limit)
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
    # Helpful debug log for dev — will print to stdout when called
    print(f"Listed {len(results)} users (skip={skip}, limit={limit})")
    return results


@router.get("/users/{user_id}", response_model=UserOut)
async def get_user_by_id(user_id: str):
    """
    Fetch a single user by their `user_id` (hex string).
    Returns 404 if the user is not found.
    """
    doc = await users_col.find_one({"user_id": user_id}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail="User not found")
    return {
        "user_id": doc.get("user_id"),
        "phone": doc.get("phone"),
        "is_verified": doc.get("is_verified", False),
        "created_at": doc.get("created_at"),
        "last_login": doc.get("last_login"),
    }


# ----------------------------
# Profile routes (owner-only)
# ----------------------------

@router.post("/user/createProfile", response_model=ProfileOut)
async def upsert_my_profile(payload: ProfileIn, current_user: Dict = Depends(get_current_user)):
    """
    Create or update the authenticated user's profile.

    This endpoint is owner-only: it uses the token -> user mapping and ignores any
    `user_id` provided in the payload (the service will use the authenticated user's id).
    """
    user_id = current_user.get("user_id")
    doc = await profile_service.create_or_update_profile(user_id, payload.dict(exclude_none=True))
    return doc


@router.get("/user/myProfile", response_model=ProfileOut)
async def read_my_profile(current_user: Dict = Depends(get_current_user)):
    """
    Get the authenticated user's profile (owner-only).
    Returns 404 if the profile does not exist.
    """
    user_id = current_user.get("user_id")
    doc = await profile_service.get_profile(user_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Profile not found")
    return doc


@router.get("/profiles", response_model=List[ProfileOut])
async def list_profiles(skip: int = 0, limit: int = 50):
    """
    List profiles (admin-style). This endpoint returns raw profile documents up to `limit`.
    Note: this uses `profile_service.profiles_col` — ensure `profile_service` exposes `profiles_col`
    or adjust to fetch from your DB collection directly.
    """
    # Using the collection exposed by the profile service for listing
    cursor = profile_service.profiles_col.find({}, {"_id": 0}).skip(skip).limit(limit).sort("created_at", 1)
    docs = await cursor.to_list(length=limit)
    return docs


@router.get("/profiles/{user_id}", response_model=ProfileOut)
async def get_profile_by_userid(user_id: str):
    """
    Fetch a profile by `user_id`. Returns 404 if not found.
    """
    doc = await profile_service.get_profile(user_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Profile not found")
    return doc


@router.delete("/profiles/{user_id}")
async def delete_profile_by_userid(user_id: str):
    """
    Delete a profile document by `user_id`.
    Returns {"status": "deleted"} on success, or 404 if not found.
    """
    ok = await profile_service.delete_profile(user_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Profile not found")
    return {"status": "deleted"}


# ----------------------------
# Image upload endpoints (owner-only)
# ----------------------------

@router.post("/user/profile/upload-profile-image")
async def upload_profile_image(file: UploadFile = File(...), current_user: Dict = Depends(get_current_user)):
    """
    Upload and set the authenticated user's profile image.

    - Expects multipart/form-data with field name `file`.
    - Encodes the image to base64 and stores it via `profile_service.add_profile_image`.
    - NOTE: currently stores plain base64. If you prefer a data URI (with MIME),
      modify `profile_service.add_profile_image` or update this handler to prepend
      `data:<mime>;base64,` before saving.
    """
    user_id = current_user.get("user_id")
    raw = await file.read()

    # Optional size check (uncomment if you want to enforce a limit)
    # MAX_BYTES = 3 * 1024 * 1024  # 3 MB
    # if len(raw) > MAX_BYTES:
    #     raise HTTPException(status_code=413, detail="File too large (max 3MB)")

    b64 = base64.b64encode(raw).decode("utf-8")
    await profile_service.add_profile_image(user_id, b64)
    return {"message": "Profile image uploaded", "user_id": user_id}


@router.post("/user/profile/upload-gallery-image")
async def upload_gallery_image(file: UploadFile = File(...), current_user: Dict = Depends(get_current_user)):
    """
    Upload a gallery image for the authenticated user.

    - Accepts multipart/form-data with field `file`.
    - Encodes bytes to base64 and appends to the user's `gallery_images` array.
    """
    user_id = current_user.get("user_id")
    raw = await file.read()
    b64 = base64.b64encode(raw).decode("utf-8")
    await profile_service.add_gallery_image(user_id, b64)
    return {"message": "Gallery image added", "user_id": user_id}
