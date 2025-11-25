"""WLO Duplicate Detection API - FastAPI Application."""

from contextlib import asynccontextmanager
import time
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from loguru import logger
import sys

from app.models import (
    HashDetectionRequest,
    HashMetadataRequest,
    EmbeddingDetectionRequest,
    EmbeddingMetadataRequest,
    DetectionResponse,
    HealthResponse,
    ContentMetadata,
    SearchField,
    CandidateStats,
    EmbeddingRequest,
    EmbeddingBatchRequest,
    EmbeddingResponse,
    EmbeddingBatchResponse,
)
from app.wlo_client import WLOClient
from app.hash_detector import hash_detector
from app.embedding_detector import embedding_detector, is_model_loaded, is_embedding_available, get_current_model_name
from app.config import detection_config

# Configure logging with JSON format for production
logger.remove()
logger.add(
    sys.stderr, 
    level="INFO", 
    format="{time:YYYY-MM-DD HH:mm:ss} | {level:<8} | {message}",
    colorize=True
)

# Rate limiter setup
limiter = Limiter(key_func=get_remote_address)

# Request timeout (seconds)
REQUEST_TIMEOUT = 55


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan handler."""
    logger.info("WLO Duplicate Detection API starting...")
    yield
    logger.info("WLO Duplicate Detection API shutting down...")


# Create FastAPI app
app = FastAPI(
    title="WLO Duplicate Detection API",
    description="""
API für die Erkennung von Dubletten (ähnlichen Inhalten) im WLO-Repository.

## Funktionen

- **Hash-basierte Erkennung**: Nutzt MinHash für schnelle Ähnlichkeitsberechnung basierend auf Textshingles
- **Embedding-basierte Erkennung**: Nutzt Sentence-Transformers für semantische Ähnlichkeit

## Ablauf

1. **Metadaten laden**: Vollständige Metadaten des Inhalts werden von WLO heruntergeladen
2. **Kandidatensuche**: Suche nach potenziellen Duplikaten über:
   - Titel (ngsearchword)
   - Beschreibung
   - Keywords
   - URL
3. **Ähnlichkeitsberechnung**: Vergleich mit Hash- oder Embedding-Verfahren
4. **Ergebnis**: Liste der potenziellen Duplikate mit Ähnlichkeitswerten

## Eingabemöglichkeiten

- **Per Node-ID**: Für bestehende WLO-Inhalte
- **Per Metadaten**: Für neue, noch nicht publizierte Inhalte
    """,
    version="1.0.0",
    license_info={
        "name": "MIT",
    },
    lifespan=lifespan,
)

# Add rate limiter
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Request logging middleware
@app.middleware("http")
async def log_requests(request: Request, call_next):
    """Log all requests with timing."""
    start_time = time.time()
    
    response = await call_next(request)
    
    duration = time.time() - start_time
    logger.info(
        f"{request.method} {request.url.path} - {response.status_code} - {duration:.2f}s"
    )
    
    return response


# ============================================================================
# Helper Functions
# ============================================================================

def get_metadata_from_node(node_id: str, environment) -> tuple[ContentMetadata, str]:
    """
    Fetch and extract metadata from a WLO node.
    
    Returns:
        Tuple of (ContentMetadata, error_message or None)
    """
    client = WLOClient(environment=environment)
    
    node_data = client.get_node_metadata(node_id)
    if not node_data:
        return None, f"Node {node_id} not found in {environment.value} environment"
    
    metadata = client.extract_content_metadata(node_data)
    if not metadata.has_content():
        return None, f"Node {node_id} has no searchable content (no title, description, keywords, or URL)"
    
    return metadata, None


def count_candidates(candidates: dict) -> int:
    """Count total unique candidates."""
    seen = set()
    for field_candidates in candidates.values():
        for c in field_candidates:
            node_id = c.get("ref", {}).get("id")
            if node_id:
                seen.add(node_id)
    return len(seen)


def build_candidate_stats(search_info: dict, field_similarities: dict = None) -> list[CandidateStats]:
    """Build CandidateStats list from search info and similarities."""
    field_similarities = field_similarities or {}
    stats = []
    for field, info in search_info.items():
        search_val = info.get("search_value")
        # Truncate search value for display
        if search_val and len(search_val) > 80:
            search_val = search_val[:80] + "..."
        
        highest_sim = field_similarities.get(field)
        
        # Get normalized search info if available
        normalized_search = info.get("normalized_search")
        if normalized_search and len(normalized_search) > 50:
            normalized_search = normalized_search[:50] + "..."
        
        stats.append(CandidateStats(
            field=field,
            search_value=search_val,
            candidates_found=info.get("count", 0),
            highest_similarity=highest_sim,
            original_count=info.get("original_count"),
            normalized_search=normalized_search,
            normalized_count=info.get("normalized_count")
        ))
    return stats


# ============================================================================
# Health Check
# ============================================================================

@app.get(
    "/health",
    response_model=HealthResponse,
    tags=["Status"],
    summary="Health Check",
    description="Prüft den Status der API und ob das Embedding-Modell geladen ist."
)
async def health_check():
    """Check API health status."""
    return HealthResponse(
        status="healthy",
        hash_detection_available=True,
        embedding_detection_available=is_embedding_available(),
        embedding_model_loaded=is_model_loaded(),
        embedding_model_name=get_current_model_name(),
        version="1.0.0"
    )


# ============================================================================
# Hash-Based Detection Endpoints
# ============================================================================

@app.post(
    "/detect/hash/by-node",
    response_model=DetectionResponse,
    tags=["Hash-basierte Erkennung"],
    summary="Dublettenerkennung per Node-ID (Hash)",
    description="""
Erkennt Dubletten für einen bestehenden WLO-Inhalt anhand seiner Node-ID.

**Ablauf:**
1. Metadaten werden von WLO geladen
2. Kandidatensuche über ausgewählte Felder
3. MinHash-Vergleich mit Schwellenwert

**Schwellenwert:** 0.8 bedeutet 80% Ähnlichkeit der Shingles.

**Rate Limit:** 100 Requests pro Minute
    """
)
@limiter.limit("100/minute")
async def detect_hash_by_node(request: Request, body: HashDetectionRequest):
    """Hash-based duplicate detection by node ID."""
    logger.info(f"Hash detection for node {body.node_id} in {body.environment.value}")
    
    # Fetch metadata
    metadata, error = get_metadata_from_node(body.node_id, body.environment)
    if error:
        return DetectionResponse(
            success=False,
            source_node_id=body.node_id,
            method="hash",
            threshold=body.similarity_threshold,
            error=error
        )
    
    # Search for candidates
    client = WLOClient(environment=body.environment)
    candidates, search_info = client.search_candidates(
        metadata=metadata,
        search_fields=body.search_fields,
        max_candidates=body.max_candidates,
        exclude_node_id=body.node_id
    )
    
    total_candidates = count_candidates(candidates)
    
    # Find duplicates
    duplicates, field_similarities = hash_detector.find_duplicates(
        source_metadata=metadata,
        candidates=candidates,
        threshold=body.similarity_threshold
    )
    
    candidate_stats = build_candidate_stats(search_info, field_similarities)
    
    return DetectionResponse(
        success=True,
        source_node_id=body.node_id,
        source_metadata=metadata,
        method="hash",
        threshold=body.similarity_threshold,
        candidate_search_results=candidate_stats,
        total_candidates_checked=total_candidates,
        duplicates=duplicates
    )


@app.post(
    "/detect/hash/by-metadata",
    response_model=DetectionResponse,
    tags=["Hash-basierte Erkennung"],
    summary="Dublettenerkennung per Metadaten (Hash)",
    description="""
Erkennt Dubletten für einen neuen Inhalt anhand direkt eingegebener Metadaten.

**Ideal für:**
- Neue, noch nicht publizierte Inhalte
- Vorab-Prüfung vor dem Import

**Schwellenwert:** 0.8 bedeutet 80% Ähnlichkeit der Shingles.

**Rate Limit:** 100 Requests pro Minute
    """
)
@limiter.limit("100/minute")
async def detect_hash_by_metadata(request: Request, body: HashMetadataRequest):
    """Hash-based duplicate detection by metadata."""
    logger.info(f"Hash detection by metadata in {body.environment.value}")
    
    if not body.metadata.has_content():
        return DetectionResponse(
            success=False,
            source_metadata=body.metadata,
            method="hash",
            threshold=body.similarity_threshold,
            error="No searchable content provided (need at least title, description, keywords, or URL)"
        )
    
    # Search for candidates
    client = WLOClient(environment=body.environment)
    candidates, search_info = client.search_candidates(
        metadata=body.metadata,
        search_fields=body.search_fields,
        max_candidates=body.max_candidates
    )
    
    total_candidates = count_candidates(candidates)
    
    # Find duplicates
    duplicates, field_similarities = hash_detector.find_duplicates(
        source_metadata=body.metadata,
        candidates=candidates,
        threshold=body.similarity_threshold
    )
    
    candidate_stats = build_candidate_stats(search_info, field_similarities)
    
    return DetectionResponse(
        success=True,
        source_metadata=body.metadata,
        method="hash",
        threshold=body.similarity_threshold,
        candidate_search_results=candidate_stats,
        total_candidates_checked=total_candidates,
        duplicates=duplicates
    )


# ============================================================================
# Embedding-Based Detection Endpoints
# ============================================================================

@app.post(
    "/detect/embedding/by-node",
    response_model=DetectionResponse,
    tags=["Embedding-basierte Erkennung"],
    summary="Dublettenerkennung per Node-ID (Embedding)",
    description="""
Erkennt semantisch ähnliche Inhalte für einen bestehenden WLO-Inhalt.

**Modell:** Konfigurierbar (siehe /health für aktuelles Modell)

**Vorteile:**
- Erkennt auch semantisch ähnliche Inhalte (nicht nur wörtliche Übereinstimmungen)
- Besser für umformulierte Texte

**Hinweis:** Beim ersten Aufruf wird das Modell geladen (kann einige Sekunden dauern).

**Schwellenwert:** 0.95 (Standard) bedeutet 95% semantische Ähnlichkeit.

**Rate Limit:** 100 Requests pro Minute
    """
)
@limiter.limit("100/minute")
async def detect_embedding_by_node(request: Request, body: EmbeddingDetectionRequest):
    """Embedding-based duplicate detection by node ID."""
    logger.info(f"Embedding detection for node {body.node_id} in {body.environment.value}")
    
    # Fetch metadata
    metadata, error = get_metadata_from_node(body.node_id, body.environment)
    if error:
        return DetectionResponse(
            success=False,
            source_node_id=body.node_id,
            method="embedding",
            threshold=body.similarity_threshold,
            error=error
        )
    
    # Search for candidates
    client = WLOClient(environment=body.environment)
    candidates, search_info = client.search_candidates(
        metadata=metadata,
        search_fields=body.search_fields,
        max_candidates=body.max_candidates,
        exclude_node_id=body.node_id
    )
    
    total_candidates = count_candidates(candidates)
    
    # Find duplicates
    try:
        duplicates, field_similarities = embedding_detector.find_duplicates(
            source_metadata=metadata,
            candidates=candidates,
            threshold=body.similarity_threshold
        )
    except RuntimeError as e:
        return DetectionResponse(
            success=False,
            source_node_id=body.node_id,
            source_metadata=metadata,
            method="embedding",
            threshold=body.similarity_threshold,
            error=str(e)
        )
    
    candidate_stats = build_candidate_stats(search_info, field_similarities)
    
    return DetectionResponse(
        success=True,
        source_node_id=body.node_id,
        source_metadata=metadata,
        method="embedding",
        threshold=body.similarity_threshold,
        candidate_search_results=candidate_stats,
        total_candidates_checked=total_candidates,
        duplicates=duplicates
    )


@app.post(
    "/detect/embedding/by-metadata",
    response_model=DetectionResponse,
    tags=["Embedding-basierte Erkennung"],
    summary="Dublettenerkennung per Metadaten (Embedding)",
    description="""
Erkennt semantisch ähnliche Inhalte für einen neuen Inhalt anhand direkt eingegebener Metadaten.

**Modell:** Konfigurierbar (siehe /health für aktuelles Modell)

**Ideal für:**
- Neue, noch nicht publizierte Inhalte
- Vorab-Prüfung vor dem Import
- Semantische Ähnlichkeitssuche

**Schwellenwert:** 0.95 (Standard) bedeutet 95% semantische Ähnlichkeit.

**Rate Limit:** 100 Requests pro Minute
    """
)
@limiter.limit("100/minute")
async def detect_embedding_by_metadata(request: Request, body: EmbeddingMetadataRequest):
    """Embedding-based duplicate detection by metadata."""
    logger.info(f"Embedding detection by metadata in {body.environment.value}")
    
    if not body.metadata.has_content():
        return DetectionResponse(
            success=False,
            source_metadata=body.metadata,
            method="embedding",
            threshold=body.similarity_threshold,
            error="No searchable content provided (need at least title, description, keywords, or URL)"
        )
    
    # Search for candidates
    client = WLOClient(environment=body.environment)
    candidates, search_info = client.search_candidates(
        metadata=body.metadata,
        search_fields=body.search_fields,
        max_candidates=body.max_candidates
    )
    
    total_candidates = count_candidates(candidates)
    
    # Find duplicates
    try:
        duplicates, field_similarities = embedding_detector.find_duplicates(
            source_metadata=body.metadata,
            candidates=candidates,
            threshold=body.similarity_threshold
        )
    except RuntimeError as e:
        return DetectionResponse(
            success=False,
            source_metadata=body.metadata,
            method="embedding",
            threshold=body.similarity_threshold,
            error=str(e)
        )
    
    candidate_stats = build_candidate_stats(search_info, field_similarities)
    
    return DetectionResponse(
        success=True,
        source_metadata=body.metadata,
        method="embedding",
        threshold=body.similarity_threshold,
        candidate_search_results=candidate_stats,
        total_candidates_checked=total_candidates,
        duplicates=duplicates
    )


# ============================================================================
# Embedding Endpoints (for general use)
# ============================================================================

@app.post(
    "/embed",
    response_model=EmbeddingResponse,
    tags=["Embeddings"],
    summary="Text zu Embedding",
    description="""
Erzeugt einen Embedding-Vektor für einen Text.

**Modell:** Konfigurierbar (siehe /health für aktuelles Modell)

**Ausgabe:** 384-dimensionaler Vektor

**Kein Rate Limit** - für intensive Nutzung geeignet.
    """
)
async def create_embedding(body: EmbeddingRequest):
    """Create embedding for a single text."""
    logger.info(f"Embedding request for text ({len(body.text)} chars)")
    
    if not is_embedding_available():
        return EmbeddingResponse(
            success=False,
            text=body.text,
            embedding=[],
            dimensions=0,
            model="",
            error="Embedding model not available"
        )
    
    try:
        embedding = embedding_detector.compute_embedding(body.text)
        
        if embedding is None:
            return EmbeddingResponse(
                success=False,
                text=body.text,
                embedding=[],
                dimensions=0,
                model=get_current_model_name(),
                error="Could not compute embedding"
            )
        
        return EmbeddingResponse(
            success=True,
            text=body.text,
            embedding=embedding.tolist(),
            dimensions=len(embedding),
            model=get_current_model_name()
        )
    except Exception as e:
        logger.error(f"Embedding failed: {e}")
        return EmbeddingResponse(
            success=False,
            text=body.text,
            embedding=[],
            dimensions=0,
            model=get_current_model_name(),
            error=str(e)
        )


@app.post(
    "/embed/batch",
    response_model=EmbeddingBatchResponse,
    tags=["Embeddings"],
    summary="Batch Text zu Embeddings",
    description="""
Erzeugt Embedding-Vektoren für mehrere Texte gleichzeitig.

**Modell:** Konfigurierbar (siehe /health für aktuelles Modell)

**Ausgabe:** Liste von 384-dimensionalen Vektoren

**Kein Rate Limit** - für intensive Nutzung geeignet.

**Effizienter** als einzelne Aufrufe bei vielen Texten.
    """
)
async def create_embeddings_batch(body: EmbeddingBatchRequest):
    """Create embeddings for multiple texts."""
    logger.info(f"Batch embedding request for {len(body.texts)} texts")
    
    if not is_embedding_available():
        return EmbeddingBatchResponse(
            success=False,
            embeddings=[],
            dimensions=0,
            count=0,
            model="",
            error="Embedding model not available"
        )
    
    try:
        embeddings = embedding_detector.batch_compute_embeddings(body.texts)
        
        # Convert to lists and filter None values
        result_embeddings = []
        for emb in embeddings:
            if emb is not None:
                result_embeddings.append(emb.tolist())
            else:
                result_embeddings.append([])
        
        dimensions = len(result_embeddings[0]) if result_embeddings and result_embeddings[0] else 0
        
        return EmbeddingBatchResponse(
            success=True,
            embeddings=result_embeddings,
            dimensions=dimensions,
            count=len(result_embeddings),
            model=get_current_model_name()
        )
    except Exception as e:
        logger.error(f"Batch embedding failed: {e}")
        return EmbeddingBatchResponse(
            success=False,
            embeddings=[],
            dimensions=0,
            count=0,
            model=get_current_model_name(),
            error=str(e)
        )


# ============================================================================
# Root Endpoint
# ============================================================================

@app.get(
    "/",
    tags=["Status"],
    summary="API Info",
    description="Zeigt Basisinformationen zur API an."
)
async def root():
    """Root endpoint with API info."""
    return {
        "name": "WLO Duplicate Detection API",
        "version": "1.0.0",
        "docs": "/docs",
        "redoc": "/redoc",
        "endpoints": {
            "hash_by_node": "/detect/hash/by-node",
            "hash_by_metadata": "/detect/hash/by-metadata",
            "embedding_by_node": "/detect/embedding/by-node",
            "embedding_by_metadata": "/detect/embedding/by-metadata",
            "embed": "/embed",
            "embed_batch": "/embed/batch",
            "health": "/health"
        }
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
