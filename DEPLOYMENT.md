# Technical Deployment Documentation: WLO Duplicate Detection

## Overview

**WLO Duplicate Detection** is a microservice for detecting duplicates (similar content) in the WLO repository. The service uses MinHash-based similarity calculation for efficient comparisons.

**Version:** 1.0.0  
**Language:** Python 3.11+  
**Framework:** FastAPI  
**Server:** Uvicorn

---

## Dependencies and Requirements

### External Dependencies

- **WLO REST API**: The service requires access to a WLO instance
  - Configurable via `WLO_BASE_URL` environment variable
  - Default: `https://repository.staging.openeduhub.net/edu-sharing/rest`
  - Network access required (HTTP/HTTPS)

### Internal Dependencies

- **No external services**: The service is completely self-contained
- All Python dependencies are defined in `requirements.txt`
- No database connections required
- No cache systems required

### Network Requirements

- **Inbound:** Port 8000 (HTTP)
- **Outbound:** HTTP/HTTPS to WLO instance (typically port 80/443)
- **No** database connections
- **No** message queue connections

---

## Configuration and Environment Variables

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `WLO_BASE_URL` | `https://repository.staging.openeduhub.net/edu-sharing/rest` | Base URL of the WLO REST API |
| `WLO_TIMEOUT` | `60` | Timeout for WLO API requests in seconds |
| `WLO_MAX_RETRIES` | `3` | Maximum number of retries for WLO API requests |
| `MAX_CANDIDATES` | `40` | Maximum candidates per search field (cannot be exceeded by client) |
| `RATE_LIMIT` | `100/minute` | Rate limit for detection endpoints |
| `LOG_LEVEL` | `INFO` | Log level (DEBUG, INFO, WARNING, ERROR) |
| `DETECTION_CACHE_TTL` | `3600` | Cache TTL for detection responses in seconds (60-86400) |
| `DETECTION_CACHE_MAX_SIZE` | `1000` | Maximum number of cached detection responses (10-10000) |
| `ADMIN_API_KEY` | (not set) | **Required for admin endpoints** - Secret key for cache management |

### Example for Kubernetes Deployment

```yaml
containers:
- name: duplicate-detection
  image: wlo-duplicate-detection:1.0.0
  env:
  - name: WLO_BASE_URL
    value: "https://redaktion.openeduhub.net/edu-sharing/rest"
  - name: LOG_LEVEL
    value: "INFO"
  ports:
  - containerPort: 8000
    name: http
```

### Docker Environment Variables

```bash
docker run -d \
  -p 8000:8000 \
  -e WLO_BASE_URL="https://redaktion.openeduhub.net/edu-sharing/rest" \
  -e LOG_LEVEL="INFO" \
  wlo-duplicate-detection:1.0.0
```

---

## Performance Characteristics

### Throughput Performance

| Scenario | Average Response Time | Throughput |
|----------|----------------------|-----------|
| Health Check (`/health`) | <10ms | >100 requests/second |
| Small metadata (title only) | 500ms - 1s | ~1-2 requests/second |
| Medium metadata (title + description) | 1s - 3s | ~0.3-1 request/second |
| Large metadata (all fields) | 3s - 10s | ~0.1-0.3 requests/second |

**Dependencies:**
- WLO repository size
- Network latency to WLO instance
- Number of candidates found
- `max_candidates` parameter

### Memory Consumption

| Scenario | Memory |
|----------|--------|
| Idle (no requests) | ~50-100 MB |
| Under load (10 concurrent requests) | ~200-400 MB |
| Peak (100 concurrent requests) | ~500-800 MB |

**Optimization Tips:**
- Reduce `max_candidates` parameter
- Use specific `search_fields`
- Increase `similarity_threshold`

### CPU Usage

- **Idle:** <5% CPU
- **Under load:** 20-50% CPU (depends on number of requests)
- **Peak:** Up to 100% CPU with many concurrent requests

---

## Security Aspects

### Input Validation

- **URL validation:** All URLs are validated
- **Timeout protection:** Requests have implicit timeouts (55 seconds)
- **Rate limiting:** 100 requests per minute per IP address
- **Size limits:** Metadata fields have maximum lengths

### Network Security

- **No authentication:** The service has no built-in authentication
  - Use an API Gateway or Reverse Proxy for authentication
  - Example: Nginx with Basic Auth or OAuth2
- **HTTPS:** Not provided by the service itself
  - Use a Reverse Proxy (Nginx, HAProxy) for HTTPS
  - Or use an Ingress Controller in Kubernetes

### Data Protection

- **No data storage:** The service stores no requests or results
- **Pass-through traffic:** All data is processed in-memory
- **Logs:** Contain no sensitive data (only request metadata)
- **WLO access:** The service accesses WLO data - ensure this is allowed in your environment

### Recommended Security Measures

1. **Reverse Proxy with HTTPS:**
   ```nginx
   server {
       listen 443 ssl;
       server_name duplicate-detection.example.com;
       
       ssl_certificate /etc/ssl/certs/cert.pem;
       ssl_certificate_key /etc/ssl/private/key.pem;
       
       location / {
           proxy_pass http://localhost:8000;
       }
   }
   ```

2. **API Gateway with Rate Limiting:**
   - Use Kong, Tyk or similar tools
   - Implement additional rate limits
   - Authentication at gateway level

3. **Network Policies in Kubernetes:**
   ```yaml
   apiVersion: networking.k8s.io/v1
   kind: NetworkPolicy
   metadata:
     name: duplicate-detection
   spec:
     podSelector:
       matchLabels:
         app: duplicate-detection
     policyTypes:
     - Ingress
     - Egress
     ingress:
     - from:
       - podSelector: {}
       ports:
       - protocol: TCP
         port: 8000
     egress:
     - to:
       - namespaceSelector: {}
       ports:
       - protocol: TCP
         port: 80
       - protocol: TCP
         port: 443
   ```

---

## Kubernetes Deployment

### Prerequisites

- Kubernetes Cluster (1.20+)
- Docker Registry with duplicate-detection image
- kubectl configured
- Access to WLO instance

### Basic Deployment

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: duplicate-detection
  namespace: default
spec:
  replicas: 2
  selector:
    matchLabels:
      app: duplicate-detection
  template:
    metadata:
      labels:
        app: duplicate-detection
    spec:
      containers:
      - name: duplicate-detection
        image: your-registry/wlo-duplicate-detection:1.0.0
        imagePullPolicy: IfNotPresent
        ports:
        - containerPort: 8000
          name: http
        env:
        - name: WLO_BASE_URL
          value: "https://redaktion.openeduhub.net/edu-sharing/rest"
        - name: LOG_LEVEL
          value: "INFO"
        resources:
          requests:
            memory: "256Mi"
            cpu: "250m"
          limits:
            memory: "1Gi"
            cpu: "1000m"
        livenessProbe:
          httpGet:
            path: /health
            port: 8000
          initialDelaySeconds: 10
          periodSeconds: 30
          timeoutSeconds: 5
          failureThreshold: 3
        readinessProbe:
          httpGet:
            path: /health
            port: 8000
          initialDelaySeconds: 5
          periodSeconds: 10
          timeoutSeconds: 5
          failureThreshold: 2
        securityContext:
          runAsNonRoot: true
          runAsUser: 1000
          readOnlyRootFilesystem: true
          allowPrivilegeEscalation: false
          capabilities:
            drop:
              - ALL
        volumeMounts:
        - name: tmp
          mountPath: /tmp
      volumes:
      - name: tmp
        emptyDir: {}
```

### Service

```yaml
apiVersion: v1
kind: Service
metadata:
  name: duplicate-detection
  namespace: default
spec:
  type: ClusterIP
  ports:
  - port: 80
    targetPort: 8000
    protocol: TCP
    name: http
  selector:
    app: duplicate-detection
```

### Ingress (with HTTPS)

```yaml
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: duplicate-detection
  namespace: default
  annotations:
    cert-manager.io/cluster-issuer: "letsencrypt-prod"
spec:
  ingressClassName: nginx
  tls:
  - hosts:
    - duplicate-detection.example.com
    secretName: duplicate-detection-tls
  rules:
  - host: duplicate-detection.example.com
    http:
      paths:
      - path: /
        pathType: Prefix
        backend:
          service:
            name: duplicate-detection
            port:
              number: 80
```

### Horizontal Pod Autoscaler

```yaml
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: duplicate-detection
  namespace: default
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: duplicate-detection
  minReplicas: 2
  maxReplicas: 10
  metrics:
  - type: Resource
    resource:
      name: cpu
      target:
        type: Utilization
        averageUtilization: 70
  - type: Resource
    resource:
      name: memory
      target:
        type: Utilization
        averageUtilization: 80
```

---

## Docker Deployment

### Building Docker Image

```bash
# Standard image
docker build -t wlo-duplicate-detection:1.0.0 .

# With registry tag
docker build -t your-registry/wlo-duplicate-detection:1.0.0 .
docker push your-registry/wlo-duplicate-detection:1.0.0
```

### Running Docker Container

```bash
# Simple start
docker run -d \
  -p 8000:8000 \
  -e WLO_BASE_URL="https://redaktion.openeduhub.net/edu-sharing/rest" \
  --name duplicate-detection \
  wlo-duplicate-detection:1.0.0

# With volume for logs
docker run -d \
  -p 8000:8000 \
  -v /var/log/duplicate-detection:/var/log \
  -e WLO_BASE_URL="https://redaktion.openeduhub.net/edu-sharing/rest" \
  --name duplicate-detection \
  wlo-duplicate-detection:1.0.0
```

### Docker Compose

```yaml
version: '3.8'

services:
  duplicate-detection:
    image: wlo-duplicate-detection:1.0.0
    ports:
      - "8000:8000"
    environment:
      WLO_BASE_URL: "https://redaktion.openeduhub.net/edu-sharing/rest"
      LOG_LEVEL: "INFO"
    restart: unless-stopped
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8000/health"]
      interval: 30s
      timeout: 10s
      retries: 3
      start_period: 10s
```

---

## Monitoring and Logging

### Health Check Endpoint

The service provides a health check endpoint:

```
GET /health
```

**Response:**
```json
{
  "status": "healthy",
  "hash_detection_available": true,
  "version": "1.0.0"
}
```

### Logging

The service uses `loguru` for structured logging. Logs are output to `stdout`.

**Log Format:**
```
2026-02-17 14:30:45 | INFO     | POST /detect/hash/by-node - 200 - 1.23s
2026-02-17 14:30:46 | DEBUG    | Hash detection for node abc123...
2026-02-17 14:30:47 | INFO     | Found 5 duplicates
```

**Recommended Logging Configuration:**
- Use a log aggregator (ELK Stack, Loki, Splunk, etc.)
- Set log level to `INFO` for production
- Monitor for errors and timeouts
- Archive logs for compliance

### Metrics

The service does not expose Prometheus metrics natively. For monitoring, we recommend:

**Request Latency:**
- Via Ingress/Load Balancer logs
- Via Application Performance Monitoring (APM) tools

**Error Rate:**
- Via application logs
- Via log aggregation

**Resource Usage:**
- Via Kubernetes Metrics Server
- Via container runtime metrics

**Example Prometheus Configuration (with Reverse Proxy):**
```yaml
global:
  scrape_interval: 15s

scrape_configs:
- job_name: 'duplicate-detection'
  static_configs:
  - targets: ['localhost:8000']
  metrics_path: '/metrics'
```

---

## Sizing and Resources

Resource requirements depend heavily on usage. The following values are starting points and should be adjusted based on actual measurements:

### Recommended Base Configuration

```yaml
resources:
  requests:
    memory: "256Mi"
    cpu: "250m"
  limits:
    memory: "1Gi"
    cpu: "1000m"
replicas: 1-2
```

### Memory Sizing

- **Base:** ~50-100 MB (Idle)
- **Per concurrent request:** Depends on `max_candidates` parameter
- **Recommendation:** With `max_candidates: 100` at least 256 MB

### CPU Sizing

- **Base:** <5% CPU (Idle)
- **Per request:** Depends on WLO repository size and network latency
- **Recommendation:** At least 250m, preferably 500m+

### Scaling

- Start with 1-2 replicas
- Use Horizontal Pod Autoscaler (HPA) based on CPU/memory metrics
- Monitor actual resource usage and adjust
- Reduce `max_candidates` parameter if memory issues occur

---

## Troubleshooting

### Service won't start

**Symptom:** Pod stays in `CrashLoopBackOff`

**Solution:**
```bash
# Check logs
kubectl logs <pod-name>

# Common causes:
# 1. Invalid WLO_BASE_URL
# 2. Network error to WLO
# 3. Missing dependencies
```

### WLO connection errors

**Symptom:** "Node not found" or connection timeouts

**Solution:**
1. Verify `WLO_BASE_URL`:
   ```bash
   curl https://redaktion.openeduhub.net/edu-sharing/rest/node/v1/nodes/-home-/test/metadata
   ```
2. Check network connectivity:
   ```bash
   kubectl exec <pod-name> -- curl -v https://redaktion.openeduhub.net/
   ```
3. Check firewall rules

### High memory usage

**Symptom:** Pod is killed due to OOMKilled

**Solution:**
- Increase memory limits
- Reduce `max_candidates` parameter
- Implement request queuing

### Rate limiting errors

**Symptom:** HTTP 429 "Rate limit exceeded"

**Solution:**
- Implement retry logic with exponential backoff
- Use an API Gateway for better rate limiting
- Increase replicas for higher throughput

### Slow requests

**Symptom:** Requests take longer than expected

**Solution:**
1. Check WLO performance:
   ```bash
   time curl https://redaktion.openeduhub.net/edu-sharing/rest/node/v1/nodes/-home-/test/metadata
   ```
2. Reduce `max_candidates`
3. Use more specific `search_fields`
4. Increase `similarity_threshold`

---

## Integration with contentjudge

The service is designed for integration with the contentjudge Java application.

### Configuration in contentjudge

In `application.properties` or `application.yml`:

```properties
repository.communication.duplicate.url=http://duplicate-detection:8000/detect/hash/by-metadata
repository.communication.duplicate.threshold=0.9
```

### Request Format

contentjudge sends the following request:

```json
{
  "text": "Extracted text from the website",
  "threshold": 0.9
}
```

### Response Format

The service responds with:

```json
[
  ["node-id-1"],
  ["node-id-2"],
  ["node-id-3"]
]
```

---

## Backup and Disaster Recovery

**Note:** The service stores no data and therefore requires no backup.

**Recovery Strategy:**
1. Restart the service
2. All requests are reprocessed
3. No data loss possible

---

## Upgrade and Versioning

### Versioning

- Use Semantic Versioning (MAJOR.MINOR.PATCH)
- Tag Docker images with version numbers
- Keep old images for rollback

### Upgrade Process

```bash
# 1. Build new image
docker build -t wlo-duplicate-detection:1.1.0 .

# 2. Push to registry
docker push your-registry/wlo-duplicate-detection:1.1.0

# 3. Update deployment
kubectl set image deployment/duplicate-detection \
  duplicate-detection=your-registry/wlo-duplicate-detection:1.1.0

# 4. Monitor rollout
kubectl rollout status deployment/duplicate-detection

# 5. On error: Rollback
kubectl rollout undo deployment/duplicate-detection
```

---

## Cache Management

### Overview

The service includes automatic response caching for the `/detect/hash/by-metadata` endpoint to improve performance for repeated requests.

**Cache Behavior:**
- Responses are cached in memory based on metadata and similarity threshold
- Cache entries expire after `DETECTION_CACHE_TTL` seconds (default: 1 hour)
- When cache reaches `DETECTION_CACHE_MAX_SIZE` entries, oldest entries are removed (FIFO)
- Cache is cleared on service restart

### Configuration

Set these environment variables to control caching:

```bash
# Cache TTL (time-to-live) in seconds
export DETECTION_CACHE_TTL=3600        # 1 hour (default)
export DETECTION_CACHE_TTL=7200        # 2 hours (longer caching)
export DETECTION_CACHE_TTL=1800        # 30 minutes (shorter caching)

# Maximum number of cached responses
export DETECTION_CACHE_MAX_SIZE=1000   # 1000 entries (default)
export DETECTION_CACHE_MAX_SIZE=500    # 500 entries (smaller deployments)
export DETECTION_CACHE_MAX_SIZE=5000   # 5000 entries (larger deployments)
```

### Memory Impact

- **Per cached response:** ~20-30 KB (average), up to 100 KB (worst case)
- **Total cache memory:** `DETECTION_CACHE_MAX_SIZE` × average response size
- **Example:** 1000 entries × 25 KB = ~25 MB RAM

### Recommended Settings by Deployment Size

| Deployment Size | Cache Size | TTL | Expected RAM |
|-----------------|-----------|-----|--------------|
| Small (< 2 GB) | 500 | 1800s | 10-15 MB |
| Medium (2-8 GB) | 1000 | 3600s | 20-30 MB |
| Large (> 8 GB) | 5000 | 7200s | 100-150 MB |

### Clearing the Cache

The service provides an admin endpoint to clear the cache:

```
POST /admin/cache/clear
X-Admin-Key: <your-admin-key>
```

**When to clear the cache:**
- After updates to the WLO database
- After bugfixes in the detection logic
- When experiencing memory issues
- During maintenance windows

**Setup:**

1. **Set the admin API key:**
   ```bash
   export ADMIN_API_KEY="your-secret-admin-key"
   ```

2. **Clear the cache:**
   ```bash
   curl -X POST "http://localhost:8000/admin/cache/clear" \
     -H "X-Admin-Key: your-secret-admin-key"
   ```

3. **Response:**
   ```json
   {
     "status": "success",
     "cleared_entries": 42,
     "timestamp": 1708345235.123,
     "message": "Successfully cleared 42 cache entries"
   }
   ```

**Security:**
- The `ADMIN_API_KEY` environment variable **must be set** for the endpoint to work
- Without it, the endpoint returns HTTP 500
- Invalid keys return HTTP 403
- All access attempts are logged
- **Recommendation:** Use a strong, randomly generated key

**Kubernetes Example:**

```yaml
env:
- name: ADMIN_API_KEY
  valueFrom:
    secretKeyRef:
      name: duplicate-detection-secrets
      key: admin-api-key
```

Create the secret:
```bash
kubectl create secret generic duplicate-detection-secrets \
  --from-literal=admin-api-key=$(openssl rand -base64 32)
```

---

## Production Deployment Checklist

- [ ] WLO_BASE_URL configured and tested
- [ ] HTTPS/TLS configured (via Reverse Proxy)
- [ ] Authentication implemented (via API Gateway)
- [ ] Rate limiting configured
- [ ] Logging and monitoring set up
- [ ] Health checks configured
- [ ] Resource limits set
- [ ] Network policies configured
- [ ] Backup strategy defined
- [ ] Disaster recovery plan created
- [ ] Load testing performed
- [ ] Security audit performed
- [ ] Documentation updated
- [ ] Team training completed
- [ ] **ADMIN_API_KEY configured for cache management**
- [ ] Cache settings tuned for deployment size
- [ ] Cache clearing procedure documented
