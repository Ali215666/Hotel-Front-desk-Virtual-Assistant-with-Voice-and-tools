"""
Main FastAPI application entry point for Hotel Front Desk AI system.
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import logging

from app.routes import router
from app.websocket_manager import WebSocketManager
from app.dependencies import (
    get_websocket_manager,
    get_ollama_client,
    get_prompt_builder,
    get_crm_tool,
    get_tool_orchestrator,
)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def create_app() -> FastAPI:
    """
    Create and configure the FastAPI application.
    
    Returns:
        FastAPI: Configured application instance
    """
    app = FastAPI(
        title="Hotel Front Desk AI API",
        description="Conversational AI system for hotel front desk operations",
        version="1.0.0"
    )
    
    # Configure CORS
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],  # Configure appropriately for production
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    
    # Include routers
    app.include_router(router)
    
    @app.on_event("startup")
    async def startup_event():
        """Initialize services on application startup."""
        import asyncio
        import sys
        import os
        
        logger.info("=" * 60)
        logger.info("Starting Hotel Front Desk AI API")
        logger.info("=" * 60)
        
        # Always set OpenWeather API key
        os.environ["OPENWEATHER_API_KEY"] = "6aa635255044c574ffc2b60d0181699f"
        logger.info(f"OpenWeather API key set: {os.getenv('OPENWEATHER_API_KEY')[:10]}...")
        
        logger.info("Initializing WebSocket Manager...")
        ws_manager = get_websocket_manager()
        logger.info(f"WebSocket Manager initialized: {ws_manager}")

        # Pre-warm the RAG index so the first user request is fast.
        # Runs in a thread-pool to avoid blocking uvicorn startup.

        # Ensure project root is on path so `rag` package is importable.
        _proj_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
        if _proj_root not in sys.path:
            sys.path.insert(0, _proj_root)

        async def _prewarm_rag():
            try:
                import time
                # Phase 1: Pre-warm embedding model (saves ~24 seconds on first query)
                logger.info("Phase 1: Pre-warming embedding model...")
                from rag.embeddings import prewarm_embedding_model
                start_emb = time.time()
                await asyncio.to_thread(prewarm_embedding_model)
                emb_time = (time.time() - start_emb) * 1000
                logger.info(f"✓ Embedding model pre-warmed in {emb_time:.0f}ms")
                
                # Pre-warm RAG index
                logger.info("Pre-warming RAG index...")
                from rag.retriever import prewarm as prewarm_rag
                start_rag = time.time()
                warmed = await asyncio.to_thread(prewarm_rag)
                rag_time = (time.time() - start_rag) * 1000
                if warmed:
                    logger.info(f"✓ RAG index pre-warmed in {rag_time:.0f}ms")
                else:
                    logger.warning("RAG pre-warm did not complete; first retrieval may be slower.")
            except Exception as exc:  # noqa: BLE001
                logger.warning("RAG pre-warm skipped (non-fatal): %s", exc)

        async def _prewarm_ollama():
            try:
                ollama_client = get_ollama_client()
                prompt_builder = get_prompt_builder()
                warmup_prompt = prompt_builder.build_prompt([], "Hello")
                warmed = await asyncio.to_thread(ollama_client.prewarm, warmup_prompt)
                if warmed:
                    logger.info("Ollama model pre-warmed successfully.")
                else:
                    logger.warning("Ollama pre-warm did not complete; first request may be slower.")
            except Exception as exc:  # noqa: BLE001
                logger.warning("Ollama pre-warm skipped (non-fatal): %s", exc)

        async def _prewarm_tools():
            """
            Warm internal tool paths without external API calls.
            """
            try:
                crm_tool = get_crm_tool()
                await crm_tool.init_db()

                orchestrator = get_tool_orchestrator()
                # Warm JSON extraction and calculator path (cheap/local).
                await orchestrator.execute_tool_calls(
                    '{"tool":"calculate_room_cost","room_type":"Standard","check_in":"2026-05-05","check_out":"2026-05-06"}',
                    user_message="calculate standard room cost from 2026-05-05 to 2026-05-06",
                )
                logger.info("Tool orchestrator pre-warmed successfully.")
            except Exception as exc:  # noqa: BLE001
                logger.warning("Tool pre-warm skipped (non-fatal): %s", exc)

        asyncio.create_task(_prewarm_rag())
        asyncio.create_task(_prewarm_ollama())
        asyncio.create_task(_prewarm_tools())

        logger.info("Application startup complete")
        logger.info(f"API available at: http://0.0.0.0:8000")
        logger.info(f"WebSocket endpoint: ws://0.0.0.0:8000/ws/chat")
        logger.info(f"Voice WebSocket endpoint: ws://0.0.0.0:8000/ws/voice_chat")
        logger.info(f"REST endpoint: http://0.0.0.0:8000/api/chat")
        logger.info("=" * 60)
    
    @app.on_event("shutdown")
    async def shutdown_event():
        """Cleanup on application shutdown."""
        logger.info("Shutting down Hotel Front Desk AI API...")
        logger.info("Application shutdown complete")
    
    return app


app = create_app()


@app.get("/")
async def root():
    """Health check endpoint."""
    return {"status": "online", "service": "Hotel Front Desk AI API"}


@app.get("/health")
async def health_check():
    """Detailed health check endpoint."""
    return {
        "status": "healthy",
        "service": "Hotel Front Desk AI API",
        "version": "1.0.0"
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=False)
