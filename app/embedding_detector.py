"""Embedding-based duplicate detection using sentence-transformers."""

from typing import List, Optional, Dict, Any
import numpy as np
from loguru import logger

from app.config import detection_config
from app.models import ContentMetadata, DuplicateCandidate, normalize_url

# Check if sentence-transformers is available
EMBEDDING_AVAILABLE = False
try:
    from sentence_transformers import SentenceTransformer
    EMBEDDING_AVAILABLE = True
except ImportError:
    logger.warning("sentence-transformers not installed. Embedding detection will be disabled.")

# Lazy load model to avoid startup delay
_model = None
_model_name = None


def cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
    """Compute cosine similarity between two vectors using numpy."""
    return float(np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b)))


def is_embedding_available() -> bool:
    """Check if embedding detection is available."""
    return EMBEDDING_AVAILABLE


def get_current_model_name() -> str:
    """Get the name of the currently loaded model."""
    if _model_name:
        return _model_name.split("/")[-1] if "/" in _model_name else _model_name
    return detection_config.embedding_model.split("/")[-1]


def get_embedding_model() -> "SentenceTransformer":
    """Get or load the embedding model (lazy initialization)."""
    global _model, _model_name
    
    if not EMBEDDING_AVAILABLE:
        raise RuntimeError(
            "Embedding detection is not available. "
            "Install sentence-transformers: pip install sentence-transformers"
        )
    
    model_id = detection_config.embedding_model
    
    if _model is None or _model_name != model_id:
        try:
            logger.info(f"Loading embedding model: {model_id}")
            _model = SentenceTransformer(model_id)
            _model_name = model_id
            logger.info(f"Embedding model loaded successfully")
        except Exception as e:
            logger.error(f"Failed to load embedding model: {e}")
            raise RuntimeError(f"Could not load embedding model {model_id}: {e}")
    
    return _model


def is_model_loaded() -> bool:
    """Check if the embedding model is loaded."""
    return _model is not None


class EmbeddingDetector:
    """Embedding-based duplicate detection using sentence-transformers."""
    
    def __init__(self):
        """Initialize embedding detector."""
        self.model = None
        logger.info("Embedding detector initialized (model will be loaded on first use)")
    
    def _ensure_model(self):
        """Ensure the model is loaded."""
        if self.model is None:
            self.model = get_embedding_model()
    
    def compute_embedding(self, text: str) -> Optional[np.ndarray]:
        """
        Compute embedding for text.
        
        Args:
            text: Text to embed
            
        Returns:
            Embedding vector or None if text is empty
        """
        if not text or not text.strip():
            return None
        
        self._ensure_model()
        
        try:
            # Truncate very long texts
            if len(text) > 10000:
                text = text[:10000]
            
            embedding = self.model.encode(text, convert_to_numpy=True)
            return embedding
        except Exception as e:
            logger.error(f"Failed to compute embedding: {e}")
            return None
    
    def compute_metadata_embedding(self, metadata: ContentMetadata) -> Optional[np.ndarray]:
        """
        Compute embedding from content metadata.
        
        Args:
            metadata: Content metadata
            
        Returns:
            Embedding vector or None if no content
        """
        text = metadata.get_searchable_text()
        return self.compute_embedding(text)
    
    def compute_similarity(self, emb1: np.ndarray, emb2: np.ndarray) -> float:
        """
        Compute cosine similarity between two embeddings.
        
        Args:
            emb1: First embedding
            emb2: Second embedding
            
        Returns:
            Similarity score (0-1)
        """
        if emb1 is None or emb2 is None:
            return 0.0
        
        return cosine_similarity(emb1, emb2)
    
    def batch_compute_embeddings(self, texts: List[str]) -> List[Optional[np.ndarray]]:
        """
        Compute embeddings for multiple texts.
        
        Args:
            texts: List of texts
            
        Returns:
            List of embeddings (None for empty texts)
        """
        self._ensure_model()
        
        # Filter out empty texts and track indices
        valid_texts = []
        valid_indices = []
        
        for i, text in enumerate(texts):
            if text and text.strip():
                # Truncate very long texts
                if len(text) > 10000:
                    text = text[:10000]
                valid_texts.append(text)
                valid_indices.append(i)
        
        if not valid_texts:
            return [None] * len(texts)
        
        try:
            # Batch encode all texts at once
            embeddings = self.model.encode(valid_texts, convert_to_numpy=True)
            
            # Build result list
            result = [None] * len(texts)
            for idx, emb in zip(valid_indices, embeddings):
                result[idx] = emb
            
            return result
        except Exception as e:
            logger.error(f"Failed to compute batch embeddings: {e}")
            return [None] * len(texts)
    
    def _is_valid_field(self, value) -> bool:
        """Check if a field value is valid (not empty or placeholder)."""
        if value is None:
            return False
        if isinstance(value, str):
            return value.strip().lower() not in {"string", ""} and len(value.strip()) > 0
        if isinstance(value, list):
            valid = [v for v in value if v and str(v).strip().lower() != "string"]
            return len(valid) > 0
        return False
    
    def find_duplicates(
        self,
        source_metadata: ContentMetadata,
        candidates: Dict[str, List[Dict[str, Any]]],
        threshold: float = None
    ) -> tuple[List[DuplicateCandidate], Dict[str, float]]:
        """
        Find duplicates among candidates using embeddings.
        Compares only the same fields that are present in source_metadata AND were searched.
        
        Args:
            source_metadata: Source content metadata
            candidates: Dict of search_field -> candidate nodes (keys indicate which fields were searched)
            threshold: Minimum similarity threshold
            
        Returns:
            Tuple of:
            - List of duplicate candidates above threshold
            - Dict of field -> highest similarity score
        """
        threshold = threshold or detection_config.default_embedding_threshold
        
        # Determine which fields were actually searched (from candidates keys)
        searched_fields = set(candidates.keys())
        
        # Determine which fields are available in source
        # Title and description are always used for scoring (if available)
        # Keywords only count if they were explicitly requested in search_fields
        has_title = self._is_valid_field(source_metadata.title)
        has_description = self._is_valid_field(source_metadata.description)
        has_keywords = self._is_valid_field(source_metadata.keywords) and "keywords" in searched_fields
        
        # Build source text from available fields only
        source_parts = []
        if has_title:
            source_parts.append(source_metadata.title)
        if has_description:
            source_parts.append(source_metadata.description)
        if has_keywords:
            valid_kw = [k for k in source_metadata.keywords if k and k.strip().lower() != "string"]
            source_parts.extend(valid_kw)
        
        source_text = " ".join(source_parts)
        logger.debug(f"Source data: {source_parts}")
        source_emb = self.compute_embedding(source_text)
        
        if source_emb is None:
            logger.warning("Could not compute embedding for source metadata")
            return [], {}
        
        logger.info(f"Source fields: title={has_title}, description={has_description}, keywords={has_keywords}")
        
        # Collect all candidates per field
        field_candidates_data: Dict[str, list] = {}
        seen_ids_global = set()
        
        for search_field, field_candidates in candidates.items():
            field_candidates_data[search_field] = []
            
            for candidate in field_candidates:
                node_id = candidate.get("ref", {}).get("id")
                if not node_id:
                    continue
                
                properties = candidate.get("properties", {})
                
                # Extract all fields for output
                title = None
                for key in ["cclom:title", "cm:name"]:
                    if key in properties:
                        val = properties[key]
                        title = val[0] if isinstance(val, list) else val
                        break
                
                description = None
                for key in ["cclom:general_description"]:
                    if key in properties:
                        val = properties[key]
                        description = val[0] if isinstance(val, list) else val
                        break
                
                keywords = None
                if "cclom:general_keyword" in properties:
                    kw = properties["cclom:general_keyword"]
                    keywords = kw if isinstance(kw, list) else [kw]
                
                url = None
                for key in ["ccm:wwwurl", "cclom:location"]:
                    if key in properties:
                        val = properties[key]
                        url = val[0] if isinstance(val, list) else val
                        break
                
                # Build candidate text from SAME fields as source
                candidate_parts = []
                if has_title and title:
                    candidate_parts.append(title)
                if has_description and description:
                    candidate_parts.append(description)
                if has_keywords and keywords:
                    candidate_parts.extend(keywords)
                
                logger.debug(f"Candidate data: {candidate_parts}")
                candidate_text = " ".join(candidate_parts)
                
                field_candidates_data[search_field].append((node_id, title, description, keywords, url, candidate_text))
        
        # Collect all unique texts for batch embedding
        all_texts = []
        text_to_idx = {}
        for field, items in field_candidates_data.items():
            for node_id, title, description, keywords, url, text in items:
                if text not in text_to_idx:
                    text_to_idx[text] = len(all_texts)
                    all_texts.append(text)
        
        if not all_texts:
            return [], {}
        
        # Batch compute embeddings
        logger.info(f"Computing embeddings for {len(all_texts)} unique candidates")
        all_embeddings = self.batch_compute_embeddings(all_texts)
        
        # Compute per-field max similarity and collect duplicates
        duplicates = []
        field_max_similarity: Dict[str, float] = {}
        
        # Get normalized source URL for matching (including redirect URL)
        source_norm_url = normalize_url(source_metadata.url)
        source_norm_redirect = normalize_url(source_metadata.redirect_url) if source_metadata.redirect_url else None
        
        for search_field, items in field_candidates_data.items():
            field_max = 0.0
            
            for node_id, title, description, keywords, url, text in items:
                # Check for URL match first (normalized URLs)
                # Compare both original URL and redirect URL from source
                candidate_norm_url = normalize_url(url)
                
                url_match = False
                if candidate_norm_url:
                    # Match if candidate URL equals original or redirect URL
                    if source_norm_url and source_norm_url == candidate_norm_url:
                        url_match = True
                    elif source_norm_redirect and source_norm_redirect == candidate_norm_url:
                        url_match = True
                
                if url_match:
                    # Exact URL match = definite duplicate
                    similarity = 1.0
                    match_type = "url_exact"
                else:
                    match_type = search_field
                    idx = text_to_idx.get(text)
                    if idx is None:
                        continue
                    emb = all_embeddings[idx]
                    if emb is None:
                        continue
                    
                    similarity = self.compute_similarity(source_emb, emb)
                
                # Track max for this field
                if similarity > field_max:
                    field_max = similarity
                
                # Skip if already processed
                if node_id in seen_ids_global:
                    continue
                seen_ids_global.add(node_id)
                
                # URL matches are ALWAYS duplicates (regardless of threshold)
                # Other matches must meet the similarity threshold
                if url_match or similarity >= threshold:
                    duplicates.append(DuplicateCandidate(
                        node_id=node_id,
                        title=title,
                        description=description,
                        keywords=keywords,
                        url=url,
                        similarity_score=round(similarity, 4),
                        match_source=match_type
                    ))
            
            # Store max similarity for this field
            if items:
                field_max_similarity[search_field] = round(field_max, 4)
        
        # Sort by similarity (highest first)
        duplicates.sort(key=lambda x: x.similarity_score, reverse=True)
        
        # Count URL exact matches vs similarity matches
        url_matches = sum(1 for d in duplicates if d.match_source == "url_exact")
        sim_matches = len(duplicates) - url_matches
        logger.info(f"Found {len(duplicates)} embedding-based duplicates: {url_matches} URL-exact, {sim_matches} above threshold {threshold}")
        return duplicates, field_max_similarity


# Global instance
embedding_detector = EmbeddingDetector()
