"""
SmartSched AI v2 – Application Entry Point
"""
from contextlib import asynccontextmanager
from backend.api import app

try:
    from logger import logger
except Exception:
    import logging
    logger = logging.getLogger("smartsched")

if __name__ == "__main__":
    import uvicorn
    logger.info("Starting SmartSched AI v2...")
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
        log_level="info",
    )
