from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.api.health import router as health_router
from app.ws.router import router as ws_router

app = FastAPI(
    title="xX_DarkMessenger_Xx API",
    description="Real-time backend for the emo/2007 MSN Messenger clone.",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health_router)
app.include_router(ws_router)
