"""Hash-based (MinHash) duplicate detection."""

import binascii
import random
from typing import List, Set, Tuple, Optional, Dict, Any
import numpy as np
from loguru import logger

from app.config import detection_config
from app.models import ContentMetadata, DuplicateCandidate, normalize_url


class MinHashDetector:
    """MinHash-based near duplicate detection."""
    
    def __init__(self, num_hashes: int = None, seed: int = 42):
        """
        Initialize MinHash detector.
        
        Args:
            num_hashes: Number of hash functions to use
            seed: Random seed for reproducibility
        """
        self.num_hashes = num_hashes or detection_config.num_hashes
        self.next_prime = 4294967311  # First prime > 2^32
        
        # Generate consistent random coefficients
        random.seed(seed)
        self.coeff_a = self._pick_random_coeffs(self.num_hashes)
        self.coeff_b = self._pick_random_coeffs(self.num_hashes)
        
        logger.info(f"MinHash detector initialized with {self.num_hashes} hash functions")
    
    def _pick_random_coeffs(self, k: int) -> List[int]:
        """Generate k unique random coefficients."""
        max_val = 2**32 - 1
        coeffs = set()
        while len(coeffs) < k:
            coeffs.add(random.randint(0, max_val))
        return list(coeffs)
    
    def _tokenize(self, text: str) -> List[str]:
        """Tokenize text into words."""
        if not text:
            return []
        # Simple tokenization - lowercase and split on whitespace
        text = text.lower().strip()
        words = text.split()
        # Remove empty and very short tokens
        return [w.strip() for w in words if w.strip() and len(w.strip()) > 1]
    
    def _create_shingles(self, words: List[str], shingle_size: int = 3) -> Set[int]:
        """
        Create shingles (n-grams) from words and hash them.
        
        Args:
            words: List of words
            shingle_size: Number of words per shingle
            
        Returns:
            Set of shingle hashes
        """
        if not words:
            return set()
        
        shingles = set()
        
        if len(words) < shingle_size:
            # For very short texts, use the entire text as one shingle
            shingle = " ".join(words)
            crc = binascii.crc32(shingle.encode()) & 0xffffffff
            shingles.add(crc)
        else:
            for i in range(len(words) - shingle_size + 1):
                shingle = " ".join(words[i:i + shingle_size])
                crc = binascii.crc32(shingle.encode()) & 0xffffffff
                shingles.add(crc)
        
        return shingles
    
    def _compute_signature(self, shingles: Set[int]) -> np.ndarray:
        """
        Compute MinHash signature for a set of shingles.
        
        Args:
            shingles: Set of shingle hashes
            
        Returns:
            MinHash signature as numpy array
        """
        signature = []
        
        for i in range(self.num_hashes):
            min_hash = self.next_prime + 1
            
            for shingle in shingles:
                hash_code = (self.coeff_a[i] * shingle + self.coeff_b[i]) % self.next_prime
                if hash_code < min_hash:
                    min_hash = hash_code
            
            signature.append(min_hash)
        
        return np.array(signature, dtype=np.float64)
    
    def compute_text_signature(self, text: str) -> Optional[np.ndarray]:
        """
        Compute MinHash signature for text.
        
        Args:
            text: Text to compute signature for
            
        Returns:
            MinHash signature or None if text is empty
        """
        words = self._tokenize(text)
        if not words:
            return None
        
        shingles = self._create_shingles(words)
        if not shingles:
            return None
        
        return self._compute_signature(shingles)
    
    def compute_metadata_signature(self, metadata: ContentMetadata) -> Optional[np.ndarray]:
        """
        Compute MinHash signature from content metadata.
        
        Args:
            metadata: Content metadata
            
        Returns:
            MinHash signature or None if no content
        """
        text = metadata.get_searchable_text()
        return self.compute_text_signature(text)
    
    def compute_similarity(self, sig1: np.ndarray, sig2: np.ndarray) -> float:
        """
        Compute similarity between two signatures using cosine similarity.
        
        Args:
            sig1: First signature
            sig2: Second signature
            
        Returns:
            Similarity score (0-1)
        """
        if sig1 is None or sig2 is None:
            return 0.0
        
        # Cosine similarity using numpy
        similarity = np.dot(sig1, sig2) / (np.linalg.norm(sig1) * np.linalg.norm(sig2))
        return float(similarity)
    
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
        Find duplicates among candidates using MinHash.
        Compares only the same fields that are present in source_metadata.
        
        Args:
            source_metadata: Source content metadata
            candidates: Dict of search_field -> candidate nodes
            threshold: Minimum similarity threshold
            
        Returns:
            Tuple of:
            - List of duplicate candidates above threshold
            - Dict of field -> highest similarity score
        """
        threshold = threshold or detection_config.default_hash_threshold
        
        # Determine which fields are available in source
        has_title = self._is_valid_field(source_metadata.title)
        has_description = self._is_valid_field(source_metadata.description)
        has_keywords = self._is_valid_field(source_metadata.keywords)
        
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
        source_sig = self.compute_text_signature(source_text)
        
        if source_sig is None:
            logger.warning("Could not compute signature for source metadata")
            return [], {}
        
        logger.info(f"Source fields: title={has_title}, description={has_description}, keywords={has_keywords}")
        
        # Track seen node IDs to avoid duplicates
        seen_ids = set()
        duplicates = []
        field_max_similarity: Dict[str, float] = {}
        
        for search_field, field_candidates in candidates.items():
            field_max = 0.0
            
            for candidate in field_candidates:
                node_id = candidate.get("ref", {}).get("id")
                if not node_id:
                    continue
                
                # Extract candidate metadata
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
                
                # Check for URL match first (normalized URLs)
                source_norm_url = normalize_url(source_metadata.url)
                candidate_norm_url = normalize_url(url)
                url_match = (source_norm_url and candidate_norm_url and 
                            source_norm_url == candidate_norm_url)
                
                if url_match:
                    # Exact URL match = definite duplicate
                    similarity = 1.0
                    match_type = "url_exact"
                else:
                    # Build candidate text from SAME fields as source
                    match_type = search_field
                    candidate_parts = []
                    if has_title and title:
                        candidate_parts.append(title)
                    if has_description and description:
                        candidate_parts.append(description)
                    if has_keywords and keywords:
                        candidate_parts.extend(keywords)
                    
                    candidate_text = " ".join(candidate_parts)
                    candidate_sig = self.compute_text_signature(candidate_text)
                    
                    if candidate_sig is None:
                        continue
                    
                    # Compute similarity
                    similarity = self.compute_similarity(source_sig, candidate_sig)
                
                # Track max similarity for this field
                if similarity > field_max:
                    field_max = similarity
                
                # Skip if already processed (for duplicates list)
                if node_id in seen_ids:
                    continue
                seen_ids.add(node_id)
                
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
            
            # Store max similarity for this field (only if candidates were found)
            if field_candidates:
                field_max_similarity[search_field] = round(field_max, 4)
        
        # Sort by similarity (highest first)
        duplicates.sort(key=lambda x: x.similarity_score, reverse=True)
        
        # Count URL exact matches vs similarity matches
        url_matches = sum(1 for d in duplicates if d.match_source == "url_exact")
        sim_matches = len(duplicates) - url_matches
        logger.info(f"Found {len(duplicates)} hash-based duplicates: {url_matches} URL-exact, {sim_matches} above threshold {threshold}")
        return duplicates, field_max_similarity


# Global instance
hash_detector = MinHashDetector()
