"""WLO API client for fetching content metadata and searching."""

from typing import Dict, List, Optional, Any
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from loguru import logger

from app.config import Environment, wlo_config
from app.models import ContentMetadata, SearchField, normalize_title, normalize_url, generate_url_search_variants, resolve_url_redirect


class WLOClient:
    """Client for WLO edu-sharing API."""
    
    def __init__(self, environment: Environment = Environment.PRODUCTION):
        """Initialize client for specified environment."""
        self.environment = environment
        self.base_url = wlo_config.get_base_url(environment)
        self.repository = wlo_config.default_repository
        self.session = self._create_session()
        
        logger.info(f"WLO Client initialized for {environment.value}: {self.base_url}")
    
    def _create_session(self) -> requests.Session:
        """Create requests session with retry configuration."""
        session = requests.Session()
        
        retry_strategy = Retry(
            total=wlo_config.max_retries,
            backoff_factor=1.0,
            status_forcelist=[500, 502, 503, 504, 429],
            allowed_methods=["HEAD", "GET", "OPTIONS", "POST"]
        )
        
        adapter = HTTPAdapter(max_retries=retry_strategy)
        session.mount("http://", adapter)
        session.mount("https://", adapter)
        
        session.headers.update({
            "Accept": "application/json",
            "Content-Type": "application/json"
        })
        
        return session
    
    def get_node_metadata(self, node_id: str) -> Optional[Dict[str, Any]]:
        """
        Fetch full metadata for a node ID.
        
        Args:
            node_id: The node ID to fetch
            
        Returns:
            Node metadata dict or None if not found
        """
        endpoint = f"{self.base_url}/node/v1/nodes/{self.repository}/{node_id}/metadata"
        params = {"propertyFilter": "-all-"}
        
        try:
            response = self.session.get(endpoint, params=params, timeout=wlo_config.default_timeout)
            response.raise_for_status()
            data = response.json()
            
            # The node data is in the 'node' field
            return data.get("node", data)
            
        except requests.exceptions.RequestException as e:
            logger.error(f"Failed to fetch metadata for node {node_id}: {e}")
            return None
    
    def extract_content_metadata(self, node_data: Dict[str, Any], resolve_redirects: bool = True) -> ContentMetadata:
        """
        Extract relevant metadata fields from node data.
        
        Args:
            node_data: Raw node data from API
            resolve_redirects: Whether to resolve URL redirects
            
        Returns:
            ContentMetadata with extracted fields
        """
        properties = node_data.get("properties", {})
        
        # Extract title
        title = None
        for key in ["cclom:title", "cm:name", "cm:title"]:
            if key in properties:
                val = properties[key]
                title = val[0] if isinstance(val, list) else val
                break
        
        # Extract description
        description = None
        for key in ["cclom:general_description", "cm:description"]:
            if key in properties:
                val = properties[key]
                description = val[0] if isinstance(val, list) else val
                break
        
        # Extract keywords
        keywords = None
        if "cclom:general_keyword" in properties:
            kw = properties["cclom:general_keyword"]
            keywords = kw if isinstance(kw, list) else [kw]
        
        # Extract URL
        url = None
        for key in ["ccm:wwwurl", "cclom:location"]:
            if key in properties:
                val = properties[key]
                url = val[0] if isinstance(val, list) else val
                break
        
        # Resolve URL redirects
        redirect_url = None
        if url and resolve_redirects:
            final_url, was_redirected = resolve_url_redirect(url)
            if was_redirected and final_url:
                redirect_url = final_url
                logger.info(f"Resolved redirect: {url[:50]}... -> {redirect_url[:50]}...")
        
        return ContentMetadata(
            title=title,
            description=description,
            keywords=keywords,
            url=url,
            redirect_url=redirect_url
        )
    
    def search_by_ngsearch(
        self,
        search_property: str,
        search_value: str,
        max_items: int = 100
    ) -> List[Dict[str, Any]]:
        """
        Search using ngsearch endpoint with pagination support.
        
        Args:
            search_property: Property name (e.g., 'ngsearchword')
            search_value: Value to search for
            max_items: Maximum total results to return (will paginate if > 100)
            
        Returns:
            List of matching nodes
        """
        endpoint = f"{self.base_url}/search/v1/queries/{self.repository}/mds_oeh/ngsearch"
        
        json_data = {
            "criteria": [
                {
                    "property": search_property,
                    "values": [search_value]
                }
            ]
        }
        
        all_nodes = []
        page_size = 100  # Standard page size
        skip_count = 0
        
        while len(all_nodes) < max_items:
            # Calculate how many items to fetch in this page
            remaining = max_items - len(all_nodes)
            current_page_size = min(page_size, remaining)
            
            params = {
                "contentType": "FILES",
                "maxItems": current_page_size,
                "skipCount": skip_count,
                "propertyFilter": "-all-"
            }
            
            try:
                response = self.session.post(
                    endpoint, 
                    params=params, 
                    json=json_data, 
                    timeout=wlo_config.default_timeout
                )
                response.raise_for_status()
                data = response.json()
                nodes = data.get("nodes", [])
                
                if not nodes:
                    # No more results
                    break
                
                all_nodes.extend(nodes)
                
                # Check if we got fewer results than requested (end of results)
                if len(nodes) < current_page_size:
                    break
                
                skip_count += len(nodes)
                
                if max_items > 100:
                    logger.debug(f"Pagination: fetched {len(all_nodes)}/{max_items} for {search_property}")
                
            except requests.exceptions.RequestException as e:
                logger.error(f"ngsearch failed for {search_property}={search_value}: {e}")
                break
        
        logger.debug(f"Total fetched for {search_property}: {len(all_nodes)} items")
        return all_nodes
    
    def _is_valid_search_value(self, value: Optional[str]) -> bool:
        """Check if a search value is valid (not empty or placeholder)."""
        if not value:
            return False
        # Filter out common placeholder values from Swagger UI
        placeholders = {"string", ""}
        return value.strip().lower() not in placeholders and len(value.strip()) > 0
    
    def _is_valid_keywords(self, keywords: Optional[List[str]]) -> bool:
        """Check if keywords list is valid (not empty or just placeholders)."""
        if not keywords:
            return False
        # Filter out placeholder values
        valid_keywords = [k for k in keywords if k and k.strip().lower() != "string"]
        return len(valid_keywords) > 0
    
    def search_candidates(
        self,
        metadata: ContentMetadata,
        search_fields: List[SearchField],
        max_candidates: int = 100,
        exclude_node_id: Optional[str] = None
    ) -> tuple[Dict[str, List[Dict[str, Any]]], Dict[str, dict]]:
        """
        Search for duplicate candidates using specified metadata fields.
        
        Args:
            metadata: Content metadata to search with
            search_fields: Which fields to use for searching
            max_candidates: Max results per search
            exclude_node_id: Node ID to exclude from results (the source)
            
        Returns:
            Tuple of:
            - Dict mapping search field to list of candidate nodes
            - Dict mapping search field to search info (search_value, count)
        """
        candidates: Dict[str, List[Dict[str, Any]]] = {}
        search_info: Dict[str, dict] = {}
        
        for field in search_fields:
            field_candidates = []
            search_value = None
            
            if field == SearchField.TITLE and self._is_valid_search_value(metadata.title):
                # Search by original title using ngsearchword
                search_value = metadata.title
                results = self.search_by_ngsearch("ngsearchword", metadata.title, max_candidates)
                original_count = len(results)
                field_candidates.extend(results)
                normalized_count = 0
                
                # Also search by normalized title (removes suffixes like "- Wikipedia")
                normalized = normalize_title(metadata.title)
                if normalized and normalized != metadata.title:
                    logger.info(f"Also searching normalized title: '{normalized}'")
                    normalized_results = self.search_by_ngsearch("ngsearchword", normalized, max_candidates)
                    # Add only new candidates (avoid duplicates)
                    existing_ids = {c.get("ref", {}).get("id") for c in field_candidates}
                    for result in normalized_results:
                        if result.get("ref", {}).get("id") not in existing_ids:
                            field_candidates.append(result)
                            normalized_count += 1
                    search_value = f"{metadata.title} → {normalized}"
                
                # Filter out the source node
                if exclude_node_id:
                    field_candidates = [
                        c for c in field_candidates 
                        if c.get("ref", {}).get("id") != exclude_node_id
                    ]
                
                candidates[field.value] = field_candidates
                # Store detailed search info
                search_info[field.value] = {
                    "search_value": search_value,
                    "count": len(field_candidates),
                    "original_search": metadata.title,
                    "original_count": original_count,
                    "normalized_search": normalized if normalized else None,
                    "normalized_count": normalized_count
                }
                logger.info(f"Field 'title': original={original_count}, normalized=+{normalized_count}, total={len(field_candidates)}")
                continue  # Skip the default processing
                
            elif field == SearchField.DESCRIPTION and self._is_valid_search_value(metadata.description):
                # Search by description - use first 100 chars for efficiency
                search_value = metadata.description[:100] if len(metadata.description) > 100 else metadata.description
                results = self.search_by_ngsearch("ngsearchword", search_value, max_candidates)
                field_candidates.extend(results)
                   
            elif field == SearchField.URL and self._is_valid_search_value(metadata.url):
                # Get all URLs to search (original + redirect if available)
                all_urls = metadata.get_all_urls()
                
                # Generate all URL variants to search (from all URLs)
                url_variants = set()
                for u in all_urls:
                    url_variants.update(generate_url_search_variants(u))
                url_variants = list(url_variants)
                
                normalized = normalize_url(metadata.url)
                
                has_redirect = metadata.redirect_url is not None
                if has_redirect:
                    logger.info(f"Searching URL with redirect: {metadata.url[:40]}... -> {metadata.redirect_url[:40]}...")
                logger.info(f"Searching URL with {len(url_variants)} variants (redirect={has_redirect})")
                
                # Search with original URL first (exact match in ccm:wwwurl)
                results = self.search_by_ngsearch("ccm:wwwurl", metadata.url, max_candidates)
                original_count = len(results)
                field_candidates.extend(results)
                existing_ids = {c.get("ref", {}).get("id") for c in field_candidates}
                
                # Search with redirect URL in ccm:wwwurl if available
                redirect_count = 0
                if metadata.redirect_url:
                    redirect_results = self.search_by_ngsearch("ccm:wwwurl", metadata.redirect_url, max_candidates)
                    for result in redirect_results:
                        node_id = result.get("ref", {}).get("id")
                        if node_id and node_id not in existing_ids:
                            field_candidates.append(result)
                            existing_ids.add(node_id)
                            redirect_count += 1
                    if redirect_count > 0:
                        logger.info(f"Redirect URL added {redirect_count} new candidates")
                
                # Search with all variants in ngsearchword
                variant_count = 0
                searched_variants = []
                for variant in url_variants:
                    if variant == metadata.url or variant == metadata.redirect_url:
                        continue  # Skip URLs already searched
                    
                    variant_results = self.search_by_ngsearch("ngsearchword", variant, max_candidates // 2)
                    new_in_variant = 0
                    for result in variant_results:
                        node_id = result.get("ref", {}).get("id")
                        if node_id and node_id not in existing_ids:
                            field_candidates.append(result)
                            existing_ids.add(node_id)
                            variant_count += 1
                            new_in_variant += 1
                    
                    if new_in_variant > 0:
                        searched_variants.append(variant[:30])
                
                if variant_count > 0:
                    logger.info(f"URL variants added {variant_count} new candidates")
                
                search_value = f"{metadata.url} ({len(url_variants)} variants)"
                if metadata.redirect_url:
                    search_value = f"{metadata.url} -> {metadata.redirect_url} ({len(url_variants)} variants)"
                
                # Filter out the source node
                if exclude_node_id:
                    field_candidates = [
                        c for c in field_candidates 
                        if c.get("ref", {}).get("id") != exclude_node_id
                    ]
                
                candidates[field.value] = field_candidates
                # Store detailed search info
                search_info[field.value] = {
                    "search_value": search_value,
                    "count": len(field_candidates),
                    "original_search": metadata.url,
                    "original_count": original_count,
                    "redirect_url": metadata.redirect_url,
                    "redirect_count": redirect_count,
                    "normalized_search": normalized if normalized else None,
                    "normalized_count": variant_count,
                    "variants_searched": len(url_variants)
                }
                logger.info(f"Field 'url': original={original_count}, redirect=+{redirect_count}, variants=+{variant_count}, total={len(field_candidates)}")
                continue  # Skip the default processing
            
            # Filter out the source node
            if exclude_node_id:
                field_candidates = [
                    c for c in field_candidates 
                    if c.get("ref", {}).get("id") != exclude_node_id
                ]
            
            candidates[field.value] = field_candidates
            search_info[field.value] = {
                "search_value": search_value,
                "count": len(field_candidates)
            }
            logger.info(f"Field '{field.value}': searched with '{search_value[:50] if search_value else 'N/A'}...', found {len(field_candidates)} candidates")
        
        # Deduplicate candidates across all fields
        candidates, dedup_stats = self._deduplicate_candidates(candidates)
        if dedup_stats["duplicates_removed"] > 0:
            logger.info(f"Deduplicated candidates: {dedup_stats['before']} → {dedup_stats['after']} ({dedup_stats['duplicates_removed']} duplicates removed)")
        
        return candidates, search_info
    
    def _deduplicate_candidates(
        self, 
        candidates: Dict[str, List[Dict[str, Any]]]
    ) -> tuple[Dict[str, List[Dict[str, Any]]], dict]:
        """
        Deduplicate candidates across all fields.
        
        A node_id should only appear once across all fields.
        Priority: keep the first occurrence (based on field order).
        
        Returns:
            Tuple of (deduplicated candidates dict, stats dict)
        """
        seen_ids = set()
        total_before = 0
        total_after = 0
        
        deduplicated = {}
        
        for field, field_candidates in candidates.items():
            total_before += len(field_candidates)
            unique_candidates = []
            
            for candidate in field_candidates:
                node_id = candidate.get("ref", {}).get("id")
                if node_id and node_id not in seen_ids:
                    seen_ids.add(node_id)
                    unique_candidates.append(candidate)
            
            deduplicated[field] = unique_candidates
            total_after += len(unique_candidates)
        
        return deduplicated, {
            "before": total_before,
            "after": total_after,
            "duplicates_removed": total_before - total_after
        }
