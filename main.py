"""
P&ID Markup Comparison API — Python / FastAPI
============================================
Converts two P&ID PDF documents (one with markup, one with applied changes)
through vision AI to verify whether every handwritten markup was correctly applied.

Startup:
    uvicorn main:app --host 0.0.0.0 --port 8080 --reload

Environment variables:
    OLLAMA_BASE_URL — Ollama service URL (default http://localhost:11434)
    OLLAMA_MODEL    — Vision model name (default llama3.2-vision)
"""


import os
from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from routes.health import router as health_router
from routes.pid import router as pid_router

load_dotenv()


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Create uploads directory on startup
    os.makedirs("uploads", exist_ok=True)
    print("✅  Uploads directory ready")
    yield
    print("🛑  Shutting down")


app = FastAPI(
    title="P&ID Markup Comparison API",
    version="1.0.0",
    description=(
        "Vision-AI–powered API that reads P&ID documents, detects handwritten "
        "colour-coded markup (Red=addition, Blue=comment, Green=deletion), and "
        "verifies whether each markup was correctly applied in a revised document."
    ),
    lifespan=lifespan,
)

# ─── CORS ────────────────────────────────────────────────────────────────────
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ─── Routers ─────────────────────────────────────────────────────────────────
app.include_router(health_router, prefix="/api")
app.include_router(pid_router, prefix="/api/pid")


if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", "8080"))
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=True)
