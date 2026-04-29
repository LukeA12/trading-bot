#!/usr/bin/env python3
"""Launch the automated trading platform."""
import os
import uvicorn
from backend.storage.models import bootstrap_db

if __name__ == "__main__":
    print("Initializing database...")
    bootstrap_db()

    port = int(os.environ.get("PORT", 8000))
    print(f"Starting server on http://0.0.0.0:{port}")
    print(f"API docs available at http://localhost:{port}/docs")

    uvicorn.run(
        "backend.server.app:app",
        host="0.0.0.0",
        port=port,
        reload=os.environ.get("RAILWAY_ENVIRONMENT") is None
    )
