# WLO Duplicate Detection API

A FastAPI-based microservice for detecting duplicate (similar) content in the WLO repository using hash-based similarity matching (MinHash).

## Features

- **Hash-based Detection (MinHash)**: Fast similarity calculation based on text shingles
- **URL Normalization**: Detects identical URLs despite different formatting
- **Title Normalization**: Removes publisher suffixes for better candidate search
- **URL Exact Match**: URLs are always compared - exact match = duplicate
- **Flexible Input**: Per Node-ID or direct metadata input
- **Advanced Candidate Search**: Original + normalized searches for more hits
- **Pagination**: Automatic pagination for large candidate sets (>100)
- **Rate Limiting**: Protection against overload (100 requests/minute for detection endpoints)
- **Metadata Enrichment**: Automatically enriches sparse metadata from matching candidates

## Quick Start

### Prerequisites

- Python 3.11+
- pip or uv package manager
- Docker (optional, for containerized deployment)

### Local Development

```bash
# Clone the repository
git clone https://github.com/openeduhub/duplicate-detection.git
cd duplicate-detection

# Install dependencies
pip install -r requirements.txt

# Run the service
python -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

The API will be available at `http://localhost:8000`

- **Swagger UI**: http://localhost:8000/docs
- **ReDoc**: http://localhost:8000/redoc

### Docker Deployment

```bash
# Build the Docker image
docker build -t wlo-duplicate-detection:latest .

# Run the container
docker run -d \
  -p 8000:8000 \
  -e WLO_BASE_URL="https://repository.staging.openeduhub.net/edu-sharing/rest" \
  --name wlo-duplicate-detection \
  wlo-duplicate-detection:latest
```

### Docker Compose

```bash
# Start the service with docker-compose
docker-compose up -d

# View logs
docker-compose logs -f

# Stop the service
docker-compose down
```

## Configuration

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `WLO_BASE_URL` | `https://repository.staging.openeduhub.net/edu-sharing/rest` | Base URL of the WLO REST API |
| `LOG_LEVEL` | `INFO` | Logging level (DEBUG, INFO, WARNING, ERROR) |

### Example Configuration

```bash
# Production setup with custom WLO instance
export WLO_BASE_URL="https://redaktion.openeduhub.net/edu-sharing/rest"
export LOG_LEVEL="INFO"

python -m uvicorn app.main:app --host 0.0.0.0 --port 8000
```

## API Documentation

For detailed API documentation, see [API.md](API.md).

### Quick API Examples

#### Detect duplicates by Node ID

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

#### Detect duplicates by metadata

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

#### Health check

```bash
curl http://localhost:8000/health
```

## Project Structure

```
duplicate-detection/
├── app/
│   ├── __init__.py
│   ├── main.py              # FastAPI application and endpoints
│   ├── models.py            # Pydantic models for requests/responses
│   ├── config.py            # Configuration management
│   ├── wlo_client.py        # WLO API client
│   └── hash_detector.py     # Hash-based duplicate detection logic
├── Dockerfile               # Docker image definition
├── docker-compose.yml       # Docker Compose configuration
├── requirements.txt         # Python dependencies
├── README.md               # This file
├── API.md                  # Detailed API documentation
└── DEPLOYMENT.md           # Deployment and operations guide
```

## Development

### Running Tests

```bash
# Install test dependencies
pip install pytest pytest-asyncio

# Run tests
pytest
```

### Code Style

The project follows PEP 8 style guidelines. Use a linter to check code quality:

```bash
# Install linting tools
pip install flake8 black

# Check code style
flake8 app/

# Format code
black app/
```

## Performance Characteristics

| Scenario | Response Time | Throughput |
|----------|---------------|-----------|
| Health check | <10ms | >100 req/s |
| Duplicate detection (small metadata) | 500ms - 2s | ~0.5-2 req/s |
| Duplicate detection (large metadata) | 2s - 10s | ~0.1-0.5 req/s |

*Note: Performance depends on WLO repository size and network latency.*

## Rate Limiting

- **Detection endpoints** (`/detect/*`): 100 requests per minute per IP
- **Health endpoint** (`/health`): No limit

## Troubleshooting

### Service won't start

**Symptom:** Connection refused or port already in use

**Solution:**
```bash
# Check if port 8000 is in use
lsof -i :8000

# Use a different port
python -m uvicorn app.main:app --port 8001
```

### WLO connection errors

**Symptom:** "Node not found" or connection timeouts

**Solution:**
1. Verify `WLO_BASE_URL` is correct
2. Check network connectivity to WLO instance
3. Verify WLO instance is running and accessible

### High memory usage

**Symptom:** Process uses excessive memory

**Solution:**
- Reduce `max_candidates` parameter in requests
- Increase available system memory
- Check for memory leaks in logs

## License

MIT License - See LICENSE file for details

## Contributing

Contributions are welcome! Please follow the development guidelines and submit pull requests to the main repository.

## Support

For issues, questions, or suggestions, please open an issue on the GitHub repository:
https://github.com/openeduhub/duplicate-detection/issues
