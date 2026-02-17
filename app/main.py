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
    DetectionResponse,
    HealthResponse,
    ContentMetadata,
    SearchField,
    CandidateStats,
    EnrichmentInfo,
    resolve_url_redirect,
    normalize_url,
)
from app.wlo_client import WLOClient
from app.hash_detector import hash_detector
from app.config import detection_config

# Configure logging with JSON format for production
logger.remove()
logger.add(
    sys.stderr, 
    level="DEBUG", 
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

- **Hash-basierte Erkennung (MinHash)**: Schnelle Ähnlichkeitsberechnung basierend auf Textshingles
- **URL-Normalisierung**: Erkennt identische URLs trotz unterschiedlicher Schreibweise
- **Titel-Normalisierung**: Entfernt Publisher-Suffixe für bessere Kandidatensuche
- **URL-Exact-Match**: URLs werden immer verglichen - exakte Übereinstimmung = Dublette
- **Flexible Eingabe**: Per Node-ID oder direkte Metadateneingabe
- **Erweiterte Kandidatensuche**: Original + normalisierte Suchen für mehr Treffer
- **Paginierung**: Automatische Paginierung für große Kandidatenmengen (>100)
- **Rate Limiting**: Schutz vor Überlastung (100 Requests/Minute für Detection-Endpoints)

## Ablauf

1. **Metadaten laden**: Vollständige Metadaten des Inhalts werden von WLO heruntergeladen
2. **Kandidatensuche**: Suche nach potenziellen Duplikaten über:
   - Titel (ngsearchword)
   - Beschreibung
   - Keywords
   - URL
3. **Ähnlichkeitsberechnung**: Vergleich mit Hash-Verfahren
4. **Ergebnis**: Liste der potenziellen Duplikate mit Ähnlichkeitswerten

## Eingabemöglichkeiten

- **Per Node-ID**: Für bestehende WLO-Inhalte
- **Per Metadaten**: Für neue, noch nicht publizierte Inhalte

## Response-Format

Die API gibt strukturierte Responses mit detaillierten Informationen zurück:
- `source_metadata`: Die verwendeten Metadaten
- `method`: Erkennungsmethode (hash)
- `threshold`: Verwendeter Schwellenwert
- `enrichment`: Informationen zur Metadaten-Anreicherung
- `candidate_search_results`: Suchstatistiken pro Feld
- `total_candidates_checked`: Gesamtzahl geprüfter Kandidaten
- `duplicates`: Liste der gefundenen Dubletten

Bei Fehlern wird eine HTTP-Exception mit entsprechendem Status-Code zurückgegeben.
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

def get_metadata_from_node(node_id: str) -> tuple[ContentMetadata, str]:
    """
    Fetch and extract metadata from a WLO node.
    
    Returns:
        Tuple of (ContentMetadata, error_message or None)
    """
    client = WLOClient()
    
    node_data = client.get_node_metadata(node_id)
    if not node_data:
        return None, f"Node {node_id} not found"
    
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


def enrich_metadata_from_candidates(
    metadata: ContentMetadata,
    candidates: dict,
    client: WLOClient
) -> tuple[ContentMetadata, EnrichmentInfo]:
    """
    Enrich sparse source metadata by fetching full metadata from a matching candidate.
    
    This is useful when only URL or title is provided - we find a matching node
    and use its metadata to expand the candidate search.
    
    Args:
        metadata: Original source metadata (possibly sparse)
        candidates: Dict of search_field -> candidate nodes from initial search
        client: WLO client for fetching node metadata
        
    Returns:
        Tuple of (enriched_metadata, enrichment_info)
    """
    enrichment_info = EnrichmentInfo(enriched=False)
    
    # Check if metadata is already complete (has title AND (description OR keywords))
    has_title = bool(metadata.title and metadata.title.strip() and metadata.title.strip().lower() != "string")
    has_description = bool(metadata.description and metadata.description.strip() and metadata.description.strip().lower() != "string")
    has_keywords = bool(metadata.keywords and any(k and k.strip() and k.strip().lower() != "string" for k in metadata.keywords))
    
    # If we already have title + at least one other field, no need to enrich
    if has_title and (has_description or has_keywords):
        logger.debug("Metadata already complete, skipping enrichment")
        return metadata, enrichment_info
    
    # Find best candidate for enrichment - prefer URL exact match, then title match
    enrichment_node_id = None
    enrichment_field = None
    
    # Normalize source URLs for matching
    source_norm_url = normalize_url(metadata.url)
    source_norm_redirect = normalize_url(metadata.redirect_url) if metadata.redirect_url else None
    
    # First, look for URL exact match
    if "url" in candidates:
        for candidate in candidates["url"]:
            node_id = candidate.get("ref", {}).get("id")
            if not node_id:
                continue
            
            properties = candidate.get("properties", {})
            candidate_url = None
            for key in ["ccm:wwwurl", "cclom:location"]:
                if key in properties:
                    val = properties[key]
                    candidate_url = val[0] if isinstance(val, list) else val
                    break
            
            candidate_norm_url = normalize_url(candidate_url)
            
            # Check if URLs match (original or redirect)
            if candidate_norm_url:
                if (source_norm_url and source_norm_url == candidate_norm_url) or \
                   (source_norm_redirect and source_norm_redirect == candidate_norm_url):
                    enrichment_node_id = node_id
                    enrichment_field = "url"
                    logger.info(f"Found URL match for enrichment: {node_id}")
                    break
    
    # If no URL match, look for title match
    if not enrichment_node_id and "title" in candidates and has_title:
        source_title_lower = metadata.title.strip().lower()
        for candidate in candidates["title"]:
            node_id = candidate.get("ref", {}).get("id")
            if not node_id:
                continue
            
            properties = candidate.get("properties", {})
            candidate_title = None
            for key in ["cclom:title", "cm:name"]:
                if key in properties:
                    val = properties[key]
                    candidate_title = val[0] if isinstance(val, list) else val
                    break
            
            if candidate_title and candidate_title.strip().lower() == source_title_lower:
                enrichment_node_id = node_id
                enrichment_field = "title"
                logger.info(f"Found title match for enrichment: {node_id}")
                break
    
    # If no enrichment source found, return original metadata
    if not enrichment_node_id:
        logger.debug("No suitable candidate found for metadata enrichment")
        return metadata, enrichment_info
    
    # Fetch full metadata from the enrichment source
    node_data = client.get_node_metadata(enrichment_node_id)
    if not node_data:
        logger.warning(f"Failed to fetch metadata for enrichment from node {enrichment_node_id}")
        return metadata, enrichment_info
    
    enrichment_metadata = client.extract_content_metadata(node_data, resolve_redirects=False)
    
    # Merge: add fields that are missing in source
    fields_added = []
    enriched_title = metadata.title
    enriched_description = metadata.description
    enriched_keywords = metadata.keywords
    enriched_url = metadata.url
    enriched_redirect_url = metadata.redirect_url
    
    if not has_title and enrichment_metadata.title:
        enriched_title = enrichment_metadata.title
        fields_added.append("title")
    
    if not has_description and enrichment_metadata.description:
        enriched_description = enrichment_metadata.description
        fields_added.append("description")
    
    if not has_keywords and enrichment_metadata.keywords:
        enriched_keywords = enrichment_metadata.keywords
        fields_added.append("keywords")
    
    # Add URL if we don't have one
    if not metadata.url and enrichment_metadata.url:
        enriched_url = enrichment_metadata.url
        fields_added.append("url")
    
    if fields_added:
        enriched = ContentMetadata(
            title=enriched_title,
            description=enriched_description,
            keywords=enriched_keywords,
            url=enriched_url,
            redirect_url=enriched_redirect_url
        )
        enrichment_info = EnrichmentInfo(
            enriched=True,
            enrichment_source_node_id=enrichment_node_id,
            enrichment_source_field=enrichment_field,
            fields_added=fields_added
        )
        logger.info(f"Enriched metadata from node {enrichment_node_id} ({enrichment_field}): added {fields_added}")
        return enriched, enrichment_info
    
    return metadata, enrichment_info


# ============================================================================
# Health Check
# ============================================================================

@app.get(
    "/health",
    response_model=HealthResponse,
    tags=["Status"],
    summary="Health Check",
    description="Prüft den Status der API."
)
async def health_check():
    """Check API health status."""
    return HealthResponse(
        status="healthy",
        hash_detection_available=True,
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
2. Metadaten-Anreicherung (automatisch, wenn unvollständig)
3. Kandidatensuche über ausgewählte Felder
4. MinHash-Vergleich mit Schwellenwert

**Schwellenwert:** 0.9 bedeutet 90% Ähnlichkeit der Shingles.

**Rate Limit:** 100 Requests pro Minute

**WLO-Konfiguration:** Die WLO REST API Base-URL wird über die Umgebungsvariable `WLO_BASE_URL` konfiguriert.
Default: `https://repository.staging.openeduhub.net/edu-sharing/rest`

**Request-Parameter:**
- `node_id` (string, erforderlich): Node-ID des zu prüfenden Inhalts
- `similarity_threshold` (float, default: 0.9): Mindestähnlichkeit (0-1)
- `search_fields` (array, default: ["title", "description", "url"]): Suchfelder
- `max_candidates` (int, default: 100): Max. Kandidaten pro Feld (1-1000)
    """
)
@limiter.limit("100/minute")
async def detect_hash_by_node(request: Request, body: HashDetectionRequest):
    """Hash-based duplicate detection by node ID."""
    logger.info(f"Hash detection for node {body.node_id}")
    
    # Fetch metadata
    metadata, error = get_metadata_from_node(body.node_id)
    if error:
        raise HTTPException(status_code=400, detail=error)
    
    # Search for candidates
    client = WLOClient()
    candidates, search_info = client.search_candidates(
        metadata=metadata,
        search_fields=body.search_fields,
        max_candidates=body.max_candidates,
        exclude_node_id=body.node_id
    )
    
    # Enrich metadata from candidates (always enabled)
    enrichment_info = None
    metadata, enrichment_info = enrich_metadata_from_candidates(metadata, candidates, client)
    
    # If enriched, re-search with all fields to expand candidate pool
    if enrichment_info.fields_added:
        logger.info(f"Re-searching with enriched metadata (added: {enrichment_info.fields_added})")
        all_fields = [SearchField.TITLE, SearchField.DESCRIPTION, SearchField.KEYWORDS, SearchField.URL]
        enriched_candidates, enriched_search_info = client.search_candidates(
            metadata=metadata,
            search_fields=all_fields,
            max_candidates=body.max_candidates,
            exclude_node_id=body.node_id
        )
        for field, field_candidates in enriched_candidates.items():
            if field not in candidates:
                candidates[field] = field_candidates
            else:
                existing_ids = {c.get("ref", {}).get("id") for c in candidates[field]}
                for c in field_candidates:
                    if c.get("ref", {}).get("id") not in existing_ids:
                        candidates[field].append(c)
        for field, info in enriched_search_info.items():
            if field not in search_info:
                search_info[field] = info
    
    total_candidates = count_candidates(candidates)
    
    # Find duplicates
    duplicates, field_similarities = hash_detector.find_duplicates(
        source_metadata=metadata,
        candidates=candidates,
        threshold=body.similarity_threshold
    )
    
    candidate_stats = build_candidate_stats(search_info, field_similarities)
    
    return DetectionResponse(
        source_metadata=metadata,
        threshold=body.similarity_threshold,
        enrichment=enrichment_info,
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

**Schwellenwert:** 0.9 bedeutet 90% Ähnlichkeit der Shingles.

**Rate Limit:** 100 Requests pro Minute

**WLO-Konfiguration:** Die WLO REST API Base-URL wird über die Umgebungsvariable `WLO_BASE_URL` konfiguriert.
Default: `https://repository.staging.openeduhub.net/edu-sharing/rest`

**Request-Parameter:**
- `metadata` (object, erforderlich): Metadaten des zu prüfenden Inhalts
  - `title` (string, optional): Titel des Inhalts
  - `description` (string, optional): Beschreibungstext
  - `keywords` (array[string], optional): Liste von Schlagwörtern
  - `url` (string, optional): URL des Inhalts
- `similarity_threshold` (float, default: 0.9): Mindestähnlichkeit (0-1)
- `search_fields` (array, default: ["title", "description", "url"]): Suchfelder
- `max_candidates` (int, default: 100): Max. Kandidaten pro Feld (1-1000)
    """
)
@limiter.limit("100/minute")
async def detect_hash_by_metadata(request: Request, body: HashMetadataRequest):
    """Hash-based duplicate detection by metadata."""
    logger.info(f"Hash detection by metadata")
    
    if not body.metadata.has_content():
        raise HTTPException(
            status_code=400,
            detail="No searchable content provided (need at least title, description, keywords, or URL)"
        )
    
    # Resolve URL redirects if URL is provided and no redirect_url set yet
    metadata = body.metadata
    if metadata.url and not metadata.redirect_url:
        final_url, was_redirected = resolve_url_redirect(metadata.url)
        if was_redirected and final_url:
            metadata = ContentMetadata(
                title=metadata.title,
                description=metadata.description,
                keywords=metadata.keywords,
                url=metadata.url,
                redirect_url=final_url
            )
            logger.info(f"Resolved redirect for input URL: {metadata.url[:50]}... -> {final_url[:50]}...")
    
    # Search for candidates
    client = WLOClient()
    candidates, search_info = client.search_candidates(
        metadata=metadata,
        search_fields=body.search_fields,
        max_candidates=body.max_candidates
    )
    
    # Enrich metadata from candidates (always enabled)
    enrichment_info = None
    metadata, enrichment_info = enrich_metadata_from_candidates(metadata, candidates, client)
    
    # If enriched, re-search with all fields to expand candidate pool
    if enrichment_info.fields_added:
        logger.info(f"Re-searching with enriched metadata (added: {enrichment_info.fields_added})")
        all_fields = [SearchField.TITLE, SearchField.DESCRIPTION, SearchField.KEYWORDS, SearchField.URL]
        enriched_candidates, enriched_search_info = client.search_candidates(
            metadata=metadata,
            search_fields=all_fields,
            max_candidates=body.max_candidates
        )
        # Merge candidates (enriched search may find more)
        for field, field_candidates in enriched_candidates.items():
            if field not in candidates:
                candidates[field] = field_candidates
            else:
                existing_ids = {c.get("ref", {}).get("id") for c in candidates[field]}
                for c in field_candidates:
                    if c.get("ref", {}).get("id") not in existing_ids:
                        candidates[field].append(c)
        # Merge search info
        for field, info in enriched_search_info.items():
            if field not in search_info:
                search_info[field] = info
    
    total_candidates = count_candidates(candidates)
    
    # Find duplicates
    duplicates, field_similarities = hash_detector.find_duplicates(
        source_metadata=metadata,
        candidates=candidates,
        threshold=body.similarity_threshold
    )
    
    candidate_stats = build_candidate_stats(search_info, field_similarities)
    
    return DetectionResponse(
        source_metadata=metadata,
        threshold=body.similarity_threshold,
        enrichment=enrichment_info,
        candidate_search_results=candidate_stats,
        total_candidates_checked=total_candidates,
        duplicates=duplicates
    )


# ============================================================================
# Embedding-Based Detection Endpoints
# ============================================================================






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
            "health": "/health"
        }
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
