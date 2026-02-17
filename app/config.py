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
    default_timeout: int = Field(default=60)
    max_retries: int = Field(default=3)
    
    def get_base_url(self) -> str:
        """Get base URL for WLO API."""
        return self.base_url


class DetectionConfig(BaseModel):
    """Detection configuration defaults."""
    
    # Hash-based detection
    default_hash_threshold: float = Field(default=0.9, ge=0.0, le=1.0)
    num_hashes: int = Field(default=100)
    
    # Candidate search
    max_candidates_per_search: int = Field(default=100)
    default_search_fields: list[str] = Field(
        default=["title", "description", "url"]
    )


# Global config instances
wlo_config = WLOConfig()
detection_config = DetectionConfig()
