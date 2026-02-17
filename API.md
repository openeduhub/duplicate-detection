# WLO Duplicate Detection API - Detailed Documentation

## Overview

The WLO Duplicate Detection API provides endpoints for detecting duplicate (similar) content in the WLO repository. The service uses hash-based similarity matching (MinHash) to efficiently compare content.

**Base URL:** `http://localhost:8000` (or your deployment URL)

**API Version:** 1.0.0

---

## Endpoints

### 1. Health Check

Check the health status of the API.

**Endpoint:** `GET /health`

**Description:** Returns the current health status of the service.

**Response:**
```json
{
  "status": "healthy",
  "hash_detection_available": true,
  "version": "1.0.0"
}
```

**Status Codes:**
- `200 OK` - Service is healthy

---

### 2. Detect Duplicates by Node ID

Detect duplicates for existing WLO content by Node ID.

**Endpoint:** `POST /detect/hash/by-node`

**Description:** 
Fetches metadata for a WLO node and searches for duplicate content. The service automatically enriches sparse metadata from matching candidates and performs advanced candidate search with normalization.

**Request Body:**
```json
{
  "node_id": "string (required)",
  "similarity_threshold": 0.9,
  "search_fields": ["title", "description", "url"],
  "max_candidates": 100
}
```

**Request Parameters:**

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `node_id` | string | required | Node ID of the content to check |
| `similarity_threshold` | float | 0.9 | Minimum similarity score (0-1) |
| `search_fields` | array | `["title", "description", "url"]` | Metadata fields to use for candidate search |
| `max_candidates` | integer | optional | Maximum candidates per search field (uses config default if not specified, cannot exceed config limit) |

**Example Request:**
```bash
curl -X POST "http://localhost:8000/detect/hash/by-node" \
  -H "Content-Type: application/json" \
  -d '{
    "node_id": "12345678-1234-1234-1234-123456789abc",
    "similarity_threshold": 0.9,
    "search_fields": ["title", "description", "keywords", "url"],
    "max_candidates": 100
  }'
```

**Response:**
```json
{
  "source_metadata": {
    "title": "Islam - Wikipedia",
    "description": "Islam is an Abrahamic monotheistic religion...",
    "keywords": ["religion", "islam", "faith"],
    "url": "https://en.wikipedia.org/wiki/Islam",
    "redirect_url": null
  },
  "threshold": 0.9,
  "enrichment": {
    "enrichment_source_node_id": null,
    "enrichment_source_field": null,
    "fields_added": []
  },
  "candidate_search_results": [
    {
      "field": "title",
      "search_value": "Islam - Wikipedia → Islam",
      "candidates_found": 45,
      "highest_similarity": 0.95,
      "original_count": 15,
      "normalized_search": "Islam",
      "normalized_count": 30
    },
    {
      "field": "url",
      "search_value": "https://en.wikipedia.org/wiki/Islam",
      "candidates_found": 12,
      "highest_similarity": 1.0,
      "original_count": 2,
      "normalized_search": "en.wikipedia.org/wiki/islam",
      "normalized_count": 10
    }
  ],
  "total_candidates_checked": 57,
  "duplicates": [
    {
      "node_id": "abc123-...",
      "title": "Islam",
      "description": null,
      "keywords": null,
      "url": "https://en.wikipedia.org/wiki/Islam",
      "similarity_score": 1.0,
      "match_source": "url_exact"
    },
    {
      "node_id": "def456-...",
      "title": "Islamic Religion",
      "description": null,
      "keywords": null,
      "url": "https://...",
      "similarity_score": 0.92,
      "match_source": "title"
    }
  ]
}
```

**Status Codes:**
- `200 OK` - Duplicates found (or none found)
- `400 Bad Request` - Invalid node ID or node not found
- `429 Too Many Requests` - Rate limit exceeded
- `500 Internal Server Error` - Server error

---

### 3. Detect Duplicates by Metadata

Detect duplicates for new content by providing metadata directly.

**Endpoint:** `POST /detect/hash/by-metadata`

**Description:**
Searches for duplicate content based on directly provided metadata. Ideal for checking new, not-yet-published content before import.

**Request Body:**
```json
{
  "metadata": {
    "title": "string (optional)",
    "description": "string (optional)",
    "keywords": ["string (optional)"],
    "url": "string (optional)"
  },
  "similarity_threshold": 0.9,
  "search_fields": ["title", "description", "url"],
  "max_candidates": 100
}
```

**Request Parameters:**

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `metadata` | object | required | Content metadata to check |
| `metadata.title` | string | optional | Title of the content |
| `metadata.description` | string | optional | Description text |
| `metadata.keywords` | array | optional | List of keywords |
| `metadata.url` | string | optional | Content URL |
| `similarity_threshold` | float | 0.9 | Minimum similarity score (0-1) |
| `search_fields` | array | `["title", "description", "url"]` | Metadata fields to use for search |
| `max_candidates` | integer | 100 | Maximum candidates per search field (1-1000) |

**Example Request:**
```bash
curl -X POST "http://localhost:8000/detect/hash/by-metadata" \
  -H "Content-Type: application/json" \
  -d '{
    "metadata": {
      "title": "Mathematik für Grundschüler",
      "description": "Lernen Sie die Grundlagen der Mathematik",
      "keywords": ["Mathematik", "Grundschule", "Rechnen"],
      "url": "https://example.com/math"
    },
    "similarity_threshold": 0.9
  }'
```

**Response:** Same format as `/detect/hash/by-node`

**Status Codes:**
- `200 OK` - Duplicates found (or none found)
- `400 Bad Request` - No searchable content provided
- `429 Too Many Requests` - Rate limit exceeded
- `500 Internal Server Error` - Server error

---

## Response Format

### DetectionResponse

The response from both detection endpoints follows this structure:

```json
{
  "source_metadata": {
    "title": "string or null",
    "description": "string or null",
    "keywords": ["string"] or null,
    "url": "string or null",
    "redirect_url": "string or null"
  },
  "threshold": 0.9,
  "enrichment": {
    "enrichment_source_node_id": "string or null",
    "enrichment_source_field": "string or null",
    "fields_added": ["string"]
  },
  "candidate_search_results": [
    {
      "field": "string",
      "search_value": "string or null",
      "candidates_found": 0,
      "highest_similarity": 0.95,
      "original_count": 0,
      "normalized_search": "string or null",
      "normalized_count": 0
    }
  ],
  "total_candidates_checked": 0,
  "duplicates": [
    {
      "node_id": "string",
      "title": "string or null",
      "description": "string or null",
      "keywords": ["string"] or null,
      "url": "string or null",
      "similarity_score": 0.95,
      "match_source": "string"
    }
  ]
}
```

### Field Descriptions

**source_metadata:**
- The metadata used for duplicate detection (may be enriched from candidates)

**threshold:**
- The similarity threshold used for matching

**enrichment:**
- Information about metadata enrichment from candidates
- `enrichment_source_node_id`: Node ID used for enrichment (if any)
- `enrichment_source_field`: Field that triggered enrichment (url or title)
- `fields_added`: List of fields that were added from enrichment

**candidate_search_results:**
- Statistics about candidate search per field
- `field`: Search field name
- `search_value`: Value used for search (truncated)
- `candidates_found`: Total number of candidates found
- `highest_similarity`: Highest similarity score among candidates
- `original_count`: Candidates from original search
- `normalized_search`: Normalized search value (if different)
- `normalized_count`: Additional candidates from normalized search

**total_candidates_checked:**
- Total number of unique candidates checked

**duplicates:**
- List of potential duplicates found
- `node_id`: Node ID of the candidate
- `title`, `description`, `keywords`, `url`: Metadata of the candidate
- `similarity_score`: Similarity score (0-1)
- `match_source`: Which search field found this candidate

---

## Normalization

### URL Normalization

URLs are normalized for better matching:

| Original | Normalized |
|----------|------------|
| `https://www.example.com/page/` | `example.com/page` |
| `http://example.com/page?utm=x` | `example.com/page` |
| `HTTPS://WWW.EXAMPLE.COM/Page` | `example.com/page` |
| `https://youtu.be/dQw4w9WgXcQ` | `youtube.com/watch?v=dQw4w9WgXcQ` |

### Title Normalization

Publisher suffixes are removed for candidate search:

| Original | Normalized |
|----------|------------|
| `Islam - Wikipedia` | `Islam` |
| `Mathematik \| Klexikon` | `Mathematik` |
| `Geschichte (planet-schule.de)` | `Geschichte` |

Supported suffixes: Wikipedia, Klexikon, Wikibooks, planet-schule, Lehrer-Online, sofatutor, serlo, and others.

---

## Match Types

| `match_source` | Meaning | Threshold |
|----------------|---------|-----------|
| `url_exact` | Normalized URLs identical | **Always duplicate** |
| `title` | Title-based match | Must be ≥ threshold |
| `description` | Description match | Must be ≥ threshold |
| `keywords` | Keyword match | Must be ≥ threshold |
| `url` | URL search (not exact) | Must be ≥ threshold |

---

## Detection Process

1. **Metadata Loading**: For Node-ID requests, complete metadata is fetched from WLO
2. **Metadata Enrichment** (automatic):
   - If metadata is incomplete, missing fields are filled from matching candidates
   - Prefers URL exact matches, falls back to title matches
   - After enrichment, a new search is performed with all available fields
3. **Candidate Search** (with normalization):
   - `title`: Original + normalized (without publisher suffix)
   - `description`: Search in first 100 characters
   - `keywords`: Search with combined keywords
   - `url`: Original + normalized (without protocol, www, query parameters)
4. **URL Check** (has priority!):
   - All candidates are checked for URL match
   - Normalized URLs are compared
   - **Exact URL match = duplicate** (regardless of threshold!)
5. **Similarity Calculation** (for non-URL matches):
   - MinHash signatures + cosine similarity
6. **Result**: URL matches + matches above threshold

---

## Error Handling

### Error Response Format

```json
{
  "detail": "Error message describing what went wrong"
}
```

### Common Errors

**400 Bad Request - Node not found**
```json
{
  "detail": "Node 12345678-1234-1234-1234-123456789abc not found"
}
```

**400 Bad Request - No searchable content**
```json
{
  "detail": "No searchable content provided (need at least title, description, keywords, or URL)"
}
```

**429 Too Many Requests - Rate limit exceeded**
```json
{
  "detail": "Rate limit exceeded: 100 per 1 minute"
}
```

**500 Internal Server Error**
```json
{
  "detail": "Internal server error"
}
```

---

## Rate Limiting

- **Detection endpoints** (`/detect/*`): 100 requests per minute per IP
- **Health endpoint** (`/health`): No limit

When rate limit is exceeded, the API returns HTTP 429 with the error message above.

---

## Performance Considerations

### Response Times

| Scenario | Typical Time |
|----------|------------|
| Health check | <10ms |
| Small metadata (title only) | 500ms - 1s |
| Medium metadata (title + description) | 1s - 3s |
| Large metadata (all fields) | 3s - 10s |

*Times depend on WLO repository size and network latency.*

### Optimization Tips

1. **Reduce max_candidates**: Lower values = faster responses
2. **Use specific search_fields**: Only search fields with content
3. **Increase similarity_threshold**: Fewer matches = faster processing
4. **Batch requests**: Use multiple requests instead of one large request

---

## Integration Examples

### Python

```python
import requests

url = "http://localhost:8000/detect/hash/by-metadata"
payload = {
    "metadata": {
        "title": "Example Title",
        "description": "Example description",
        "url": "https://example.com"
    },
    "similarity_threshold": 0.9
}

response = requests.post(url, json=payload)
result = response.json()

for duplicate in result["duplicates"]:
    print(f"Found duplicate: {duplicate['node_id']} (score: {duplicate['similarity_score']})")
```

### JavaScript/Node.js

```javascript
const url = "http://localhost:8000/detect/hash/by-metadata";
const payload = {
  metadata: {
    title: "Example Title",
    description: "Example description",
    url: "https://example.com"
  },
  similarity_threshold: 0.9
};

fetch(url, {
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify(payload)
})
  .then(response => response.json())
  .then(result => {
    result.duplicates.forEach(dup => {
      console.log(`Found duplicate: ${dup.node_id} (score: ${dup.similarity_score})`);
    });
  });
```

### cURL

```bash
curl -X POST "http://localhost:8000/detect/hash/by-metadata" \
  -H "Content-Type: application/json" \
  -d '{
    "metadata": {
      "title": "Example Title",
      "description": "Example description",
      "url": "https://example.com"
    },
    "similarity_threshold": 0.9
  }'
```

---

## Changelog

### Version 1.0.0 (2026-02-17)

- Initial release
- Hash-based duplicate detection (MinHash)
- URL and title normalization
- Metadata enrichment
- Rate limiting
- Comprehensive API documentation
