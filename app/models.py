"""Pydantic models for WLO Duplicate Detection API."""

from typing import Optional, List, Dict, Any, Tuple
from urllib.parse import urlparse, urlunparse
from pydantic import BaseModel, Field
from enum import Enum
import requests
from loguru import logger

from app.config import Environment


def normalize_title(title: Optional[str]) -> Optional[str]:
    """
    Normalize title for better duplicate matching.
    
    Normalizations:
    - Remove common suffixes (- Wikipedia, | Klexikon, etc.)
    - Remove publisher names in brackets
    - Strip extra whitespace
    
    Examples:
        "Islam - Wikipedia" -> "Islam"
        "Mathematik | Klexikon" -> "Mathematik"
        "Geschichte (planet-schule.de)" -> "Geschichte"
    """
    if not title or not title.strip():
        return None
    
    title = title.strip()
    
    # Common suffixes to remove (case-insensitive patterns)
    suffixes = [
        r'\s*[-–—|:]\s*Wikipedia.*$',
        r'\s*[-–—|:]\s*Klexikon.*$',
        r'\s*[-–—|:]\s*Wikibooks.*$',
        r'\s*[-–—|:]\s*Wikiversity.*$',
        r'\s*[-–—|:]\s*planet-schule.*$',
        r'\s*[-–—|:]\s*Planet Schule.*$',
        r'\s*[-–—|:]\s*Lehrer-Online.*$',
        r'\s*[-–—|:]\s*Lernhelfer.*$',
        r'\s*[-–—|:]\s*sofatutor.*$',
        r'\s*[-–—|:]\s*learningapps.*$',
        r'\s*[-–—|:]\s*serlo.*$',
        r'\s*\([^)]*\.(de|com|org|net|edu)\)$',  # (example.de)
        r'\s*\|\s*[^|]+$',  # | anything at the end
    ]
    
    import re
    normalized = title
    for pattern in suffixes:
        normalized = re.sub(pattern, '', normalized, flags=re.IGNORECASE)
    
    normalized = normalized.strip()
    normalized = normalized.replace('&', '')
    normalized = normalized.replace('  ', ' ')
    logger.debug(f"Normalized title: '{normalized}'")
    
    # Return None if normalized is empty or same as original
    if not normalized:
        return None
    
    return normalized if normalized != title else None


def normalize_url(url: Optional[str]) -> Optional[str]:
    """
    Normalize URL for better duplicate matching.
    
    Normalizations:
    - Lowercase
    - Remove protocol (http/https)
    - Remove www. prefix
    - Remove trailing slashes
    - Remove common tracking parameters
    - YouTube: Extract video/channel ID for canonical form
    
    Examples:
        https://www.Example.com/Page/ -> example.com/page
        http://example.com/page?utm_source=x -> example.com/page
        https://youtu.be/dQw4w9WgXcQ -> youtube.com/watch?v=dQw4w9WgXcQ
        https://www.youtube.com/embed/dQw4w9WgXcQ -> youtube.com/watch?v=dQw4w9WgXcQ
    """
    if not url or not url.strip():
        return None
    
    url = url.strip().lower()
    
    try:
        parsed = urlparse(url)
        
        # Get host without www.
        host = parsed.netloc
        if host.startswith('www.'):
            host = host[4:]
        
        # YouTube special handling
        if 'youtube.com' in host or 'youtu.be' in host:
            return _normalize_youtube_url(url, parsed, host)
        
        # Get path without trailing slash
        path = parsed.path.rstrip('/')
        
        # Reconstruct normalized URL (no protocol, no query)
        normalized = host + path
        
        return normalized if normalized else None
        
    except Exception:
        # If parsing fails, return lowercase stripped version
        return url.strip().lower()


def _normalize_youtube_url(url: str, parsed, host: str) -> Optional[str]:
    """
    Normalize YouTube URLs to canonical form.
    
    Video formats -> youtube.com/watch?v=VIDEO_ID
    - youtube.com/watch?v=ID (with optional &t=, &list=, &index=)
    - youtu.be/ID (with optional ?t=)
    - youtube.com/embed/ID
    - youtube.com/v/ID
    - youtube.com/shorts/ID
    - youtube.com/live/ID
    - m.youtube.com/watch?v=ID
    
    Channel formats -> youtube.com/channel/CHANNEL_ID or youtube.com/@USERNAME
    - youtube.com/channel/ID
    - youtube.com/channel/ID/live
    - youtube.com/c/NAME
    - youtube.com/user/NAME
    - youtube.com/@username
    
    Playlist formats -> youtube.com/playlist?list=PLAYLIST_ID
    """
    import re
    from urllib.parse import parse_qs
    
    path = parsed.path
    query = parse_qs(parsed.query)
    
    # Extract video ID from various formats
    video_id = None
    
    # youtu.be/VIDEO_ID or youtu.be/VIDEO_ID?t=60
    if 'youtu.be' in host:
        video_id = path.strip('/').split('/')[0]  # Get first path segment
        if '?' in video_id:
            video_id = video_id.split('?')[0]
    
    # youtube.com/watch?v=VIDEO_ID (ignore other params like t=, list=, index=)
    elif '/watch' in path and 'v' in query:
        video_id = query['v'][0]
    
    # youtube.com/embed/VIDEO_ID
    elif '/embed/' in path:
        match = re.search(r'/embed/([a-zA-Z0-9_-]{11})', path)
        if match:
            video_id = match.group(1)
    
    # youtube.com/v/VIDEO_ID (legacy)
    elif '/v/' in path:
        match = re.search(r'/v/([a-zA-Z0-9_-]{11})', path)
        if match:
            video_id = match.group(1)
    
    # youtube.com/shorts/VIDEO_ID
    elif '/shorts/' in path:
        match = re.search(r'/shorts/([a-zA-Z0-9_-]{11})', path)
        if match:
            video_id = match.group(1)
    
    # youtube.com/live/VIDEO_ID
    elif '/live/' in path:
        match = re.search(r'/live/([a-zA-Z0-9_-]{11})', path)
        if match:
            video_id = match.group(1)
    
    # If video ID found (11 chars), return canonical form
    if video_id and len(video_id) == 11:
        return f"youtube.com/watch?v={video_id}"
    
    # Handle standalone playlists (not video in playlist)
    if '/playlist' in path and 'list' in query:
        playlist_id = query['list'][0]
        return f"youtube.com/playlist?list={playlist_id}"
    
    # Handle channels
    # youtube.com/@username
    if path.startswith('/@'):
        username = path[2:].split('/')[0]  # Get handle without /live etc
        return f"youtube.com/@{username}"
    
    # youtube.com/channel/ID or youtube.com/channel/ID/live
    if '/channel/' in path:
        match = re.search(r'/channel/([a-zA-Z0-9_-]+)', path)
        if match:
            return f"youtube.com/channel/{match.group(1)}"
    
    # youtube.com/c/NAME or youtube.com/user/NAME
    if '/c/' in path:
        match = re.search(r'/c/([^/]+)', path)
        if match:
            return f"youtube.com/c/{match.group(1)}"
    
    if '/user/' in path:
        match = re.search(r'/user/([^/]+)', path)
        if match:
            return f"youtube.com/user/{match.group(1)}"
    
    # Fallback: just return normalized youtube URL
    return f"youtube.com{path.rstrip('/')}"


def generate_url_search_variants(url: Optional[str]) -> List[str]:
    """
    Generate URL variants for candidate search.
    
    Since we don't know which format is stored in WLO, we search with multiple variants.
    
    Returns list of unique URL variants to search with.
    """
    if not url or not url.strip():
        return []
    
    from urllib.parse import urlparse
    
    url = url.strip()
    variants = set()
    
    # Add original
    variants.add(url)
    
    try:
        parsed = urlparse(url.lower())
        host = parsed.netloc
        path = parsed.path.rstrip('/')
        
        # YouTube: use specialized variant generation only
        if 'youtube.com' in host or 'youtu.be' in host:
            yt_variants = _generate_youtube_variants(url, parsed)
            variants.update(yt_variants)
            # Add original URL forms too
            variants.add(url)
            variants.add(url.lower())
            return [v for v in variants if v and v.strip()]
        
        # Non-YouTube URLs: generate protocol/www variants
        base_host = host.replace('www.', '') if host.startswith('www.') else host
        www_host = f"www.{base_host}" if not host.startswith('www.') else host
        
        # Generate protocol + host + path combinations
        for protocol in ['https://', 'http://']:
            for h in [base_host, www_host]:
                variants.add(f"{protocol}{h}{path}")
                variants.add(f"{protocol}{h}{path}/")  # with trailing slash
        
        # Also add without protocol (for ngsearchword)
        variants.add(f"{base_host}{path}")
        
    except Exception:
        pass
    
    # Remove empty strings and return unique list
    return [v for v in variants if v and v.strip()]


def _generate_youtube_variants(url: str, parsed) -> List[str]:
    """Generate YouTube URL variants for search."""
    import re
    from urllib.parse import parse_qs
    
    variants = []
    path = parsed.path
    query = parse_qs(parsed.query)
    
    # Extract video ID
    video_id = None
    
    if 'youtu.be' in parsed.netloc:
        video_id = path.strip('/').split('/')[0]
        if '?' in video_id:
            video_id = video_id.split('?')[0]
    elif '/watch' in path and 'v' in query:
        video_id = query['v'][0]
    elif '/embed/' in path:
        match = re.search(r'/embed/([a-zA-Z0-9_-]{11})', path)
        if match:
            video_id = match.group(1)
    elif '/v/' in path:
        match = re.search(r'/v/([a-zA-Z0-9_-]{11})', path)
        if match:
            video_id = match.group(1)
    elif '/shorts/' in path:
        match = re.search(r'/shorts/([a-zA-Z0-9_-]{11})', path)
        if match:
            video_id = match.group(1)
    elif '/live/' in path:
        match = re.search(r'/live/([a-zA-Z0-9_-]{11})', path)
        if match:
            video_id = match.group(1)
    
    # Generate all video URL formats for search
    if video_id and len(video_id) == 11:
        variants.extend([
            # Standard watch URLs
            f"https://www.youtube.com/watch?v={video_id}",
            f"https://youtube.com/watch?v={video_id}",
            f"http://www.youtube.com/watch?v={video_id}",
            f"http://youtube.com/watch?v={video_id}",
            # Short URLs
            f"https://youtu.be/{video_id}",
            f"http://youtu.be/{video_id}",
            # Embed URLs
            f"https://www.youtube.com/embed/{video_id}",
            f"http://www.youtube.com/embed/{video_id}",
            # Legacy v/ format
            f"https://www.youtube.com/v/{video_id}",
            # Shorts
            f"https://www.youtube.com/shorts/{video_id}",
            # Live
            f"https://www.youtube.com/live/{video_id}",
            # Mobile
            f"https://m.youtube.com/watch?v={video_id}",
            # Just the ID for ngsearchword
            video_id,
        ])
    
    # Handle playlists
    if 'list' in query:
        playlist_id = query['list'][0]
        variants.extend([
            f"https://www.youtube.com/playlist?list={playlist_id}",
            f"https://youtube.com/playlist?list={playlist_id}",
            playlist_id,
        ])
    
    return variants


def resolve_url_redirect(url: Optional[str], timeout: int = 10) -> Tuple[Optional[str], bool]:
    """
    Resolve URL redirects by following the redirect chain.
    
    Args:
        url: URL to resolve
        timeout: Request timeout in seconds
        
    Returns:
        Tuple of (final_url, was_redirected)
        - final_url: The URL after following all redirects, or None on error
        - was_redirected: True if URL was redirected to a different location
    """
    if not url or not url.strip():
        return None, False
    
    url = url.strip()
    
    # Skip non-http URLs
    if not url.startswith(('http://', 'https://')):
        return None, False
    
    try:
        # Use HEAD request to check for redirects (faster, no content download)
        response = requests.head(
            url, 
            allow_redirects=True, 
            timeout=timeout,
            headers={'User-Agent': 'Mozilla/5.0 (compatible; WLO-Duplicate-Detector/1.0)'}
        )
        
        final_url = response.url
        
        # Check if we were redirected
        was_redirected = final_url != url and normalize_url(final_url) != normalize_url(url)
        
        if was_redirected:
            logger.info(f"URL redirect detected: {url[:60]}... -> {final_url[:60]}...")
        
        return final_url, was_redirected
        
    except requests.exceptions.TooManyRedirects:
        logger.warning(f"Too many redirects for URL: {url[:60]}...")
        return None, False
    except requests.exceptions.Timeout:
        logger.warning(f"Timeout resolving redirect for URL: {url[:60]}...")
        return None, False
    except requests.exceptions.RequestException as e:
        logger.debug(f"Could not resolve redirect for URL {url[:60]}...: {e}")
        return None, False


class SearchField(str, Enum):
    """Available metadata fields for candidate search."""
    TITLE = "title"
    DESCRIPTION = "description"
    URL = "url"


class ContentMetadata(BaseModel):
    """Content metadata for duplicate detection."""
    title: Optional[str] = Field(default=None, description="Title of the content")
    description: Optional[str] = Field(default=None, description="Description text")
    keywords: Optional[List[str]] = Field(default=None, description="List of keywords")
    url: Optional[str] = Field(default=None, description="Content URL (ccm:wwwurl)")
    redirect_url: Optional[str] = Field(default=None, description="Resolved redirect URL (if different from url)")
    
    @property
    def normalized_url(self) -> Optional[str]:
        """Get normalized URL for duplicate matching."""
        return normalize_url(self.url)
    
    @property
    def normalized_redirect_url(self) -> Optional[str]:
        """Get normalized redirect URL for duplicate matching."""
        return normalize_url(self.redirect_url)
    
    def get_all_urls(self) -> List[str]:
        """Get all URLs (original + redirect) for searching."""
        urls = []
        if self.url:
            urls.append(self.url)
        if self.redirect_url and self.redirect_url != self.url:
            urls.append(self.redirect_url)
        return urls
    
    def get_searchable_text(self) -> str:
        """Get combined searchable text from all fields."""
        parts = []
        if self.title:
            parts.append(self.title)
        if self.description:
            parts.append(self.description)
        if self.keywords:
            parts.append(" ".join(self.keywords))
        return " ".join(parts)
    
    def has_content(self) -> bool:
        """Check if there is any content to search with."""
        return bool(self.title or self.description or self.keywords or self.url)


class DuplicateCandidate(BaseModel):
    """A potential duplicate candidate."""
    node_id: str = Field(..., description="Node ID of the candidate")
    title: Optional[str] = Field(default=None, description="Title of the candidate")
    description: Optional[str] = Field(default=None, description="Description of the candidate")
    keywords: Optional[List[str]] = Field(default=None, description="Keywords of the candidate")
    url: Optional[str] = Field(default=None, description="URL of the candidate")
    similarity_score: float = Field(..., description="Similarity score (0-1)")
    match_source: str = Field(..., description="Which search field found this candidate")


class DetectionRequest(BaseModel):
    """Base request for duplicate detection."""
    environment: Environment = Field(
        default=Environment.PRODUCTION,
        description="WLO environment (production or staging)"
    )
    search_fields: List[SearchField] = Field(
        default=[SearchField.TITLE, SearchField.DESCRIPTION, SearchField.URL],
        description="Metadata fields to use for candidate search"
    )
    max_candidates: int = Field(
        default=100,
        ge=1,
        le=1000,
        description="Maximum candidates per search field (pagination used if > 100)"
    )
    enrich_from_candidates: bool = Field(
        default=True,
        description="If true, enrich sparse metadata from first URL/title match to expand candidate search"
    )


class NodeIdRequest(DetectionRequest):
    """Request for detection by Node ID."""
    node_id: str = Field(..., description="Node ID of the content to check")


class MetadataRequest(DetectionRequest):
    """Request for detection by direct metadata input."""
    metadata: ContentMetadata = Field(..., description="Content metadata to check for duplicates")


class HashDetectionRequest(NodeIdRequest):
    """Request for hash-based duplicate detection by Node ID."""
    similarity_threshold: float = Field(
        default=0.9,
        ge=0.0,
        le=1.0,
        description="Minimum similarity score for hash-based matching (0-1)"
    )


class HashMetadataRequest(MetadataRequest):
    """Request for hash-based detection with direct metadata."""
    similarity_threshold: float = Field(
        default=0.9,
        ge=0.0,
        le=1.0,
        description="Minimum similarity score for hash-based matching (0-1)"
    )


class EmbeddingDetectionRequest(NodeIdRequest):
    """Request for embedding-based duplicate detection by Node ID."""
    similarity_threshold: float = Field(
        default=0.95,
        ge=0.0,
        le=1.0,
        description="Minimum cosine similarity for embedding matching (0-1)"
    )


class EmbeddingMetadataRequest(MetadataRequest):
    """Request for embedding-based detection with direct metadata."""
    similarity_threshold: float = Field(
        default=0.95,
        ge=0.0,
        le=1.0,
        description="Minimum cosine similarity for embedding matching (0-1)"
    )


class CandidateStats(BaseModel):
    """Statistics about candidate search per field."""
    field: str = Field(..., description="Search field name")
    search_value: Optional[str] = Field(default=None, description="Value used for search (truncated)")
    candidates_found: int = Field(default=0, description="Total number of candidates found")
    highest_similarity: Optional[float] = Field(default=None, description="Highest similarity score among candidates (0-1)")
    # Detailed breakdown for normalized searches
    original_count: Optional[int] = Field(default=None, description="Candidates from original search")
    normalized_search: Optional[str] = Field(default=None, description="Normalized search value (if different)")
    normalized_count: Optional[int] = Field(default=None, description="Additional candidates from normalized search")


class EnrichmentInfo(BaseModel):
    """Information about metadata enrichment from candidates."""
    enriched: bool = Field(default=False, description="Whether metadata was enriched from candidates")
    enrichment_source_node_id: Optional[str] = Field(default=None, description="Node ID used for enrichment")
    enrichment_source_field: Optional[str] = Field(default=None, description="Field that triggered enrichment (url or title)")
    fields_added: List[str] = Field(default_factory=list, description="Fields that were added from enrichment")


class DetectionResponse(BaseModel):
    """Response from duplicate detection."""
    success: bool = Field(default=True)
    source_node_id: Optional[str] = Field(default=None, description="Node ID of source content (if provided)")
    source_metadata: Optional[ContentMetadata] = Field(default=None, description="Metadata used for detection")
    method: str = Field(..., description="Detection method used (hash or embedding)")
    threshold: float = Field(..., description="Similarity threshold used")
    enrichment: Optional[EnrichmentInfo] = Field(default=None, description="Metadata enrichment details")
    candidate_search_results: List[CandidateStats] = Field(
        default_factory=list, 
        description="Candidates found per search field"
    )
    total_candidates_checked: int = Field(default=0, description="Total unique candidates checked")
    duplicates: List[DuplicateCandidate] = Field(default_factory=list, description="List of potential duplicates")
    error: Optional[str] = Field(default=None, description="Error message if any")


class HealthResponse(BaseModel):
    """Health check response."""
    status: str = Field(default="healthy")
    hash_detection_available: bool = Field(default=True, description="Hash-based detection is always available")
    embedding_detection_available: bool = Field(default=False, description="Whether embedding detection is available")
    embedding_model_loaded: bool = Field(default=False, description="Whether embedding model is loaded")
    embedding_model_name: str = Field(default="", description="Name of the configured embedding model")
    version: str = Field(default="1.0.0")


class EmbeddingRequest(BaseModel):
    """Request for text embedding."""
    text: str = Field(..., description="Text to embed", min_length=1)
    

class EmbeddingBatchRequest(BaseModel):
    """Request for batch text embedding."""
    texts: List[str] = Field(..., description="List of texts to embed", min_length=1)


class EmbeddingResponse(BaseModel):
    """Response with embedding vector."""
    success: bool = Field(default=True)
    text: str = Field(..., description="Input text")
    embedding: List[float] = Field(..., description="Embedding vector")
    dimensions: int = Field(..., description="Number of dimensions")
    model: str = Field(..., description="Model used for embedding")
    error: Optional[str] = Field(default=None)


class EmbeddingBatchResponse(BaseModel):
    """Response with multiple embedding vectors."""
    success: bool = Field(default=True)
    embeddings: List[List[float]] = Field(..., description="List of embedding vectors")
    dimensions: int = Field(..., description="Number of dimensions per embedding")
    count: int = Field(..., description="Number of embeddings returned")
    model: str = Field(..., description="Model used for embedding")
    error: Optional[str] = Field(default=None)
