"""Configuration for WLO Duplicate Detection API."""

import os
from pydantic import BaseModel, Field


class WLOConfig(BaseModel):
    """WLO API configuration."""
    
    base_url: str = Field(
        default=os.environ.get("WLO_BASE_URL", "https://repository.staging.openeduhub.net/edu-sharing/rest"),
        description="Base URL for WLO REST API (set via WLO_BASE_URL environment variable)"
    )
    default_repository: str = Field(default="-home-")
    default_timeout: int = Field(
        default=int(os.environ.get("WLO_TIMEOUT", "30")),
        description="Timeout for WLO API requests in seconds (set via WLO_TIMEOUT environment variable)"
    )
    max_retries: int = Field(
        default=int(os.environ.get("WLO_MAX_RETRIES", "3")),
        description="Maximum number of retries for WLO API requests (set via WLO_MAX_RETRIES environment variable)"
    )
    
    def get_base_url(self) -> str:
        """Get base URL for WLO API."""
        return self.base_url


class DetectionConfig(BaseModel):
    """Detection configuration defaults."""
    
    # Hash-based detection
    default_hash_threshold: float = Field(default=0.9, ge=0.0, le=1.0)
    num_hashes: int = Field(default=100)
    
    # Candidate search - maximum limit (cannot be exceeded by client)
    max_candidates_limit: int = Field(
        default=int(os.environ.get("MAX_CANDIDATES", "40")),
        ge=1,
        le=1000,
        description="Maximum candidates per search field (set via MAX_CANDIDATES environment variable)"
    )
    default_search_fields: list[str] = Field(
        default=["title", "description", "url"]
    )
    
    # Rate limiting
    rate_limit: str = Field(
        default=os.environ.get("RATE_LIMIT", "100/minute"),
        description="Rate limit for detection endpoints (set via RATE_LIMIT environment variable)"
    )


# Global config instances
wlo_config = WLOConfig()
detection_config = DetectionConfig()
