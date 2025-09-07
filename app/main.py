# app/main.py
import logging
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.logging_config import configure_logging
from app.db import ensure_indexes
from app.routes import auth, users

configure_logging()
logger = logging.getLogger("brahmamatch-backend")

app = FastAPI(title="BrahmaMatch Auth Service")

# -----------------------
# CORS - allow your frontend(s)
# -----------------------
origins = [
    "http://localhost:3000",
    "http://127.0.0.1:3000",
    # add other allowed origins here (e.g. staging URL)
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,            # do NOT use ["*"] if allow_credentials=True in production
    allow_credentials=True,           # set to True if the frontend sends cookies or credentials
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS", "PATCH"],
    allow_headers=["*"],              # or list specific headers like ["Authorization","Content-Type"]
)

# register routers (keep these after middleware)
app.include_router(auth.router)
app.include_router(users.router)

@app.on_event("startup")
async def startup():
    try:
        await ensure_indexes()
        logger.info("Indexes ready.")
    except Exception as e:
        logger.error("Startup index error: %s", e)
