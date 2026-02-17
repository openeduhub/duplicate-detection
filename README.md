# WLO Duplicate Detection API

FastAPI-basierter Dienst zur Erkennung von Dubletten (ähnlichen Inhalten) im WLO-Repository.

## Features

- **Hash-basierte Erkennung (MinHash)**: Schnelle Ähnlichkeitsberechnung basierend auf Textshingles
- **URL-Normalisierung**: Erkennt identische URLs trotz unterschiedlicher Schreibweise
- **Titel-Normalisierung**: Entfernt Publisher-Suffixe für bessere Kandidatensuche
- **URL-Exact-Match**: URLs werden immer verglichen - exakte Übereinstimmung = Dublette
- **Flexible Eingabe**: Per Node-ID oder direkte Metadateneingabe
- **Erweiterte Kandidatensuche**: Original + normalisierte Suchen für mehr Treffer
- **Paginierung**: Automatische Paginierung für große Kandidatenmengen (>100)
- **Rate Limiting**: Schutz vor Überlastung (100 Requests/Minute für Detection-Endpoints)

## Installation

### Option 1: Docker (empfohlen)

```bash
cd duplicate-detection

# Mit Docker Compose (einfachste Variante)
docker-compose up -d

# Oder manuell bauen und starten
docker build -t wlo-duplicate-detection .
docker run -d -p 8000:8000 --name wlo-duplicate-detection wlo-duplicate-detection
```

### Option 2: Lokale Installation

```bash
cd duplicate-detection
pip install -r requirements.txt
```

## Starten

```bash
# Docker
docker-compose up -d

# Direkt mit Python
python -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

# Oder mit dem Run-Script
python run.py
```

Die API ist dann unter `http://localhost:8000` erreichbar.

- **Swagger UI**: http://localhost:8000/docs
- **ReDoc**: http://localhost:8000/redoc

## Endpunkte

### Hash-basierte Erkennung

#### `POST /detect/hash/by-node`
Dublettenerkennung für einen bestehenden WLO-Inhalt per Node-ID.

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

#### `POST /detect/hash/by-metadata`
Dublettenerkennung für neue Inhalte per direkter Metadateneingabe.

```bash
curl -X POST "http://localhost:8000/detect/hash/by-metadata" \
  -H "Content-Type: application/json" \
  -d '{
    "metadata": {
      "title": "Mathematik für Grundschüler",
      "description": "Lernen Sie die Grundlagen der Mathematik",
      "keywords": ["Mathematik", "Grundschule", "Rechnen"]
    },
    "similarity_threshold": 0.9
  }'
```


## Request-Parameter

### Gemeinsame Parameter

| Parameter | Typ | Default | Beschreibung |
|-----------|-----|---------|--------------|
| `search_fields` | array | `["title", "description", "keywords", "url"]` | Felder für Kandidatensuche |
| `max_candidates` | int | `100` | Max. Kandidaten pro Suchfeld (1-1000, Paginierung ab >100) |

### Hash-spezifisch

| Parameter | Typ | Default | Beschreibung |
|-----------|-----|---------|--------------|
| `similarity_threshold` | float | `0.9` | Mindestähnlichkeit (0-1) |

### Konfiguration

Die WLO REST API Base-URL wird über die Umgebungsvariable `WLO_BASE_URL` konfiguriert:

| Variable | Default | Beschreibung |
|----------|---------|--------------|
| `WLO_BASE_URL` | `https://repository.staging.openeduhub.net/edu-sharing/rest` | Base-URL der WLO REST API |


### Metadata-Objekt

| Feld | Typ | Beschreibung |
|------|-----|--------------|
| `title` | string | Titel des Inhalts |
| `description` | string | Beschreibungstext |
| `keywords` | array[string] | Liste von Schlagwörtern |
| `url` | string | URL des Inhalts |

## Response-Format

```json
{
  "source_metadata": {
    "title": "Islam - Wikipedia",
    "description": "...",
    "keywords": ["..."],
    "url": "https://de.wikipedia.org/wiki/Islam",
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
      "original_count": 15,
      "normalized_search": "Islam",
      "normalized_count": 30,
      "highest_similarity": 0.95
    },
    {
      "field": "url",
      "search_value": "https://de.wikipedia.org/wiki/Islam → de.wikipedia.org/wiki/islam",
      "candidates_found": 12,
      "original_count": 2,
      "normalized_search": "de.wikipedia.org/wiki/islam",
      "normalized_count": 10,
      "highest_similarity": 1.0
    }
  ],
  "total_candidates_checked": 57,
  "duplicates": [
    {
      "node_id": "abc123-...",
      "title": "Islam",
      "description": null,
      "keywords": null,
      "url": "https://de.wikipedia.org/wiki/Islam",
      "similarity_score": 1.0,
      "match_source": "url_exact"
    },
    {
      "node_id": "def456-...",
      "title": "Ähnlicher Inhalt",
      "description": null,
      "keywords": null,
      "url": "https://...",
      "similarity_score": 0.92,
      "match_source": "title"
    }
  ]
}
```

**Hinweis:** Bei Fehlern wird eine HTTP-Exception mit entsprechendem Status-Code zurückgegeben (z.B. 400 Bad Request).

## Ablauf der Erkennung

1. **Metadaten laden**: Bei Node-ID-Anfragen werden die vollständigen Metadaten von WLO geladen

2. **Metadaten-Anreicherung** (automatisch):
   - Falls Metadaten unvollständig sind, wird versucht, fehlende Felder aus gefundenen Kandidaten zu ergänzen
   - Bevorzugt URL-Exact-Matches, fallback auf Titel-Matches
   - Nach Anreicherung wird eine neue Suche mit allen verfügbaren Feldern durchgeführt

3. **Kandidatensuche** (erweitert mit Normalisierung):
   - `title`: Original + normalisiert (ohne Publisher-Suffix wie "- Wikipedia")
   - `description`: Suche in den ersten 100 Zeichen
   - `keywords`: Suche mit kombinierten Keywords
   - `url`: Original + normalisiert (ohne Protokoll, www, Query-Parameter)

4. **URL-Prüfung** (hat Priorität!):
   - Alle Kandidaten werden auf URL-Übereinstimmung geprüft
   - Normalisierte URLs werden verglichen (http://www.example.com/ = example.com)
   - **Exakte URL-Übereinstimmung = Dublette** (unabhängig vom Schwellenwert!)

5. **Ähnlichkeitsberechnung** (für nicht-URL-Treffer):
   - **Hash**: MinHash-Signaturen + Kosinus-Ähnlichkeit

6. **Ergebnis**: URL-Matches + Treffer über Schwellenwert


## Normalisierung

### URL-Normalisierung

URLs werden normalisiert für besseres Matching:

| Original | Normalisiert |
|----------|--------------|
| `https://www.example.com/page/` | `example.com/page` |
| `http://example.com/page?utm=x` | `example.com/page` |
| `HTTPS://WWW.EXAMPLE.COM/Page` | `example.com/page` |

### Titel-Normalisierung

Publisher-Suffixe werden für die Kandidatensuche entfernt:

| Original | Normalisiert |
|----------|--------------|
| `Islam - Wikipedia` | `Islam` |
| `Mathematik \| Klexikon` | `Mathematik` |
| `Geschichte (planet-schule.de)` | `Geschichte` |

Unterstützte Suffixe: Wikipedia, Klexikon, Wikibooks, planet-schule, Lehrer-Online, sofatutor, serlo, u.a.

## Match-Typen

| `match_source` | Bedeutung | Schwellenwert |
|----------------|-----------|---------------|
| `url_exact` | Normalisierte URLs identisch | **Immer Dublette** |
| `title` | Titel-basierter Treffer | Muss ≥ threshold sein |
| `description` | Beschreibungs-Treffer | Muss ≥ threshold sein |
| `keywords` | Keyword-Treffer | Muss ≥ threshold sein |
| `url` | URL-Suche (nicht exakt) | Muss ≥ threshold sein |


## Entwicklung

```bash
# Mit Auto-Reload
uvicorn app.main:app --reload --port 8000
```

## Docker

### Container starten

```bash
# Mit Docker Compose (empfohlen)
docker-compose up -d

# Logs anzeigen
docker-compose logs -f

# Stoppen
docker-compose down
```

### Manuell bauen

```bash
docker build -t wlo-duplicate-detection .
docker run -d -p 8000:8000 --name wlo-duplicate-detection wlo-duplicate-detection
```

### Konfiguration

Umgebungsvariablen in `docker-compose.yml` oder via `-e`:

| Variable | Default | Beschreibung |
|----------|---------|--------------|
| `LOG_LEVEL` | `INFO` | Log-Level |

### Dateien

| Datei | Beschreibung |
|-------|--------------|
| `Dockerfile` | CPU-Image (python:3.11-slim, ~1.5GB) |
| `docker-compose.yml` | Orchestrierung |
| `.dockerignore` | Optimiert Build-Größe |

### Features

- **Health Check**: Automatische Überwachung (`/health` Endpoint)
- **Non-root User**: Sicherheit durch unprivilegierten Benutzer
- **Restart Policy**: Automatischer Neustart bei Fehler


## Rate Limits

| Endpunkt | Rate Limit |
|----------|------------|
| `/detect/*` | 100/Minute |
| `/health` | Kein Limit |

## Credits

Die Hash-basierte Dublettenerkennung (MinHash) basiert auf dem Code von:
- **Original-Projekt:** https://github.com/yovisto/wlo-duplicate-detection
- **Autor:** Yovisto GmbH

## Technologien

- **FastAPI**: Web-Framework
- **NumPy**: Ähnlichkeitsberechnung
- **Pydantic**: Datenvalidierung
- **Loguru**: Logging
- **SlowAPI**: Rate Limiting
