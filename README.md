# WLO Duplicate Detection API

FastAPI-basierter Dienst zur Erkennung von Dubletten (ähnlichen Inhalten) im WLO-Repository.

## Features

- **Hash-basierte Erkennung (MinHash)**: Schnelle Ähnlichkeitsberechnung basierend auf Textshingles
- **Embedding-basierte Erkennung**: Semantische Ähnlichkeit mit Sentence-Transformers (GPU-Unterstützung)
- **URL-Normalisierung**: Erkennt identische URLs trotz unterschiedlicher Schreibweise (inkl. YouTube)
- **Titel-Varianten**: Automatische Generierung von Suchvarianten (Umlaute, Adjektiv-Endungen, ohne Sonderzeichen)
- **Parallele Suche**: Alle Suchanfragen (inkl. Varianten) werden mit 10 Workern parallel ausgeführt
- **URL-Exact-Match**: URLs werden immer verglichen - exakte Übereinstimmung = Dublette
- **Timing-Informationen**: Detaillierte Zeitmessung pro Verarbeitungsschritt in der Response
- **Embedding/Hash-API**: Separate Endpunkte für Embedding- und Hash-Generierung (ohne Rate Limit)
- **Flexible Eingabe**: Per Node-ID oder direkte Metadateneingabe
- **Erweiterte Kandidatensuche**: Original + normalisierte + Varianten-Suchen für mehr Treffer
- **Paginierung**: Automatische Paginierung für große Kandidatenmengen (>100)
- **Rate Limiting**: Schutz vor Überlastung (200 Requests/Minute für Detection-Endpoints)
- **Google Colab kompatibel**: Nutzt GPU wenn verfügbar

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

**Mit GPU-Unterstützung:**
```bash
# GPU-Image bauen
docker build -f Dockerfile.gpu -t wlo-duplicate-detection:gpu .

# Mit NVIDIA Runtime starten
docker run -d --gpus all -p 8000:8000 --name wlo-duplicate-detection wlo-duplicate-detection:gpu
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
    "environment": "production",
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
    "environment": "production",
    "similarity_threshold": 0.9
  }'
```

### Embedding-basierte Erkennung

#### `POST /detect/embedding/by-node`
Semantische Dublettenerkennung per Node-ID.

**Beispiel:** Dublette finden für einen bestehenden Inhalt auf Production:

```bash
curl -X POST "http://localhost:8000/detect/embedding/by-node" \
  -H "Content-Type: application/json" \
  -d '{
    "node_id": "948f53c2-3e3e-4247-8af9-e39cb256aa20",
    "environment": "production",
    "similarity_threshold": 0.95
  }'
```

#### `POST /detect/embedding/by-metadata`
Semantische Dublettenerkennung per direkter Metadateneingabe.

```bash
curl -X POST "http://localhost:8000/detect/embedding/by-metadata" \
  -H "Content-Type: application/json" \
  -d '{
    "metadata": {
      "title": "Mathematik für Grundschüler",
      "description": "Lernen Sie die Grundlagen der Mathematik"
    },
    "environment": "production",
    "similarity_threshold": 0.95
  }'
```

### Embedding-Generierung (ohne Rate Limit)

#### `POST /embed`
Erzeugt einen 384-dimensionalen Embedding-Vektor für einen Text.

```bash
curl -X POST "http://localhost:8000/embed" \
  -H "Content-Type: application/json" \
  -d '{"text": "Dies ist ein Beispieltext"}'
```

**Response:**
```json
{
  "success": true,
  "text": "Dies ist ein Beispieltext",
  "embedding": [0.0234, -0.0567, ...],
  "dimensions": 384,
  "model": "paraphrase-multilingual-MiniLM-L12-v2"
}
```

### Hash-Signatur-Generierung (ohne Rate Limit)

#### `POST /hash`
Erzeugt eine MinHash-Signatur (100 Hash-Werte) für einen Text.

```bash
curl -X POST "http://localhost:8000/hash" \
  -H "Content-Type: application/json" \
  -d '{"text": "Dies ist ein Beispieltext"}'
```

**Response:**
```json
{
  "success": true,
  "text": "Dies ist ein Beispieltext",
  "signature": [2847291034, 183746529, 947261834, ...],
  "num_hashes": 100
}
```

**Vergleich von Hash-Signaturen:**
```python
def jaccard_similarity(sig_a, sig_b):
    return sum(a == b for a, b in zip(sig_a, sig_b)) / len(sig_a)

similarity = jaccard_similarity(hash_a, hash_b)
if similarity >= 0.9:
    print("Wahrscheinlich Duplikat!")
```

## Request-Parameter

### Gemeinsame Parameter

| Parameter | Typ | Default | Beschreibung |
|-----------|-----|---------|--------------|
| `environment` | string | `production` | WLO-Umgebung: `production` oder `staging` |
| `search_fields` | array | `["title", "description", "url"]` | Felder für Kandidatensuche (keywords optional) |
| `max_candidates` | int | `100` | Max. Kandidaten pro Suchfeld (1-1000, Paginierung ab >100) |

### Hash-spezifisch

| Parameter | Typ | Default | Beschreibung |
|-----------|-----|---------|--------------|
| `similarity_threshold` | float | `0.9` | Mindestähnlichkeit (0-1) |

### Embedding-spezifisch

| Parameter | Typ | Default | Beschreibung |
|-----------|-----|---------|--------------|
| `similarity_threshold` | float | `0.95` | Mindest-Kosinus-Ähnlichkeit (0-1) |

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
  "success": true,
  "source_node_id": "12345678-...",
  "source_metadata": {
    "title": "Islam - Wikipedia",
    "description": "...",
    "keywords": ["..."],
    "url": "https://de.wikipedia.org/wiki/Islam"
  },
  "method": "hash",
  "threshold": 0.9,
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
      "similarity_score": 1.0,
      "match_source": "url_exact",
      "url": "https://de.wikipedia.org/wiki/Islam"
    },
    {
      "node_id": "def456-...",
      "title": "Ähnlicher Inhalt",
      "similarity_score": 0.92,
      "match_source": "title",
      "url": "https://..."
    }
  ],
  "error": null
}
```

## Ablauf der Erkennung

1. **Metadaten laden**: Bei Node-ID-Anfragen werden die vollständigen Metadaten von WLO geladen

2. **Kandidatensuche** (erweitert mit Normalisierung):
   - `title`: Original + normalisiert (ohne Publisher-Suffix wie "- Wikipedia")
   - `description`: Suche in den ersten 100 Zeichen
   - `keywords`: Suche mit kombinierten Keywords
   - `url`: Original + normalisiert (ohne Protokoll, www, Query-Parameter)

3. **URL-Prüfung** (hat Priorität!):
   - Alle Kandidaten werden auf URL-Übereinstimmung geprüft
   - Normalisierte URLs werden verglichen (http://www.example.com/ = example.com)
   - **Exakte URL-Übereinstimmung = Dublette** (unabhängig vom Schwellenwert!)

4. **Ähnlichkeitsberechnung** (für nicht-URL-Treffer):
   - **Hash**: MinHash-Signaturen + Kosinus-Ähnlichkeit
   - **Embedding**: Sentence-Transformer + Kosinus-Ähnlichkeit

5. **Ergebnis**: URL-Matches + Treffer über Schwellenwert

## Unterschied Hash vs. Embedding

| Aspekt | Hash (MinHash) | Embedding |
|--------|----------------|-----------|
| **Geschwindigkeit** | Sehr schnell | Langsamer (GPU empfohlen) |
| **Erkennung** | Wörtliche Ähnlichkeit | Semantische Ähnlichkeit |
| **Modell** | Shingle-basiert | Multilingual MiniLM |
| **Ideal für** | Exakte/nahe Duplikate | Umformulierte Texte |

## Normalisierung

### URL-Normalisierung

URLs werden normalisiert für besseres Matching:

| Original | Normalisiert |
|----------|--------------|
| `https://www.example.com/page/` | `example.com/page` |
| `http://example.com/page?utm=x` | `example.com/page` |
| `HTTPS://WWW.EXAMPLE.COM/Page` | `example.com/page` |

**YouTube-URLs** werden auf kanonische Form normalisiert:

| Original | Normalisiert |
|----------|--------------|
| `https://youtu.be/dQw4w9WgXcQ` | `youtube.com/watch?v=dQw4w9WgXcQ` |
| `https://www.youtube.com/embed/dQw4w9WgXcQ` | `youtube.com/watch?v=dQw4w9WgXcQ` |
| `https://www.youtube.com/shorts/dQw4w9WgXcQ` | `youtube.com/watch?v=dQw4w9WgXcQ` |

### Titel-Normalisierung

Publisher-Suffixe werden für die Kandidatensuche entfernt:

| Original | Normalisiert |
|----------|--------------|
| `Islam - Wikipedia` | `Islam` |
| `Mathematik \| Klexikon` | `Mathematik` |
| `Geschichte (planet-schule.de)` | `Geschichte` |

Unterstützte Suffixe: Wikipedia, Klexikon, Wikibooks, planet-schule, Lehrer-Online, sofatutor, serlo, u.a.

**Zusätzliche Normalisierungen:**
- `&` wird durch Leerzeichen ersetzt
- Mehrfache Leerzeichen werden zu einem Leerzeichen zusammengefasst

### Titel-Varianten-Suche (WLO-Suchprobleme)

Die WLO Elastic Search hat bekannte Probleme:
- **Keine Lemmatisierung**: "energieeffiziente" ≠ "energieeffizienter" ≠ "energieeffizient"
- **Case-Sensitive**: "Mathematik" ≠ "mathematik"
- **Umlaut-Handling**: "Übung" könnte als "Uebung" gespeichert sein

Um diese Probleme zu umgehen, werden automatisch **Titel-Varianten** generiert:

**Beispiel:** `Übungen für Grundschüler - Wikipedia`

| Variante | Beschreibung |
|----------|-------------|
| `übungen für grundschüler` | Lowercase, ohne Suffix |
| `uebungen fuer grundschueler` | Umlaute normalisiert (ä→ae, ö→oe, ü→ue, ß→ss) |
| `übung für grundschüler` | Basisform (Endung entfernt) |
| `energie effizient` | Bindestriche entfernt/ersetzt |

**Varianten-Typen:**
- **Lowercase**: Groß-/Kleinschreibung
- **Umlaute**: ä→ae, ö→oe, ü→ue, ß→ss
- **Bindestriche**: Entfernt oder durch Leerzeichen ersetzt
- **Ohne Sonderzeichen**: Nur alphanumerische Zeichen behalten
- **Adjektiv-Endungen**: `-e`, `-er`, `-es`, `-en`, `-em`

**Alle Suchen (inkl. Varianten) werden mit 10 parallelen Workern ausgeführt** für optimale Performance.

### Timing-Informationen

Jede Response enthält detaillierte Zeitmessungen:

```json
"timing": {
  "metadata_fetch_ms": 1702.9,
  "candidate_search_ms": 2333.2,
  "enrichment_ms": 0,
  "similarity_calculation_ms": 497.8,
  "total_ms": 4653.3
}
```

| Feld | Beschreibung |
|------|--------------|
| `metadata_fetch_ms` | Zeit für WLO-Metadaten-Abruf (nur by-node) |
| `candidate_search_ms` | Zeit für parallele Kandidatensuche |
| `enrichment_ms` | Zeit für Metadaten-Anreicherung |
| `similarity_calculation_ms` | Zeit für Hash/Embedding-Berechnung |
| `total_ms` | Gesamte Verarbeitungszeit |

### Keywords als Suchfeld

**Keywords sind optional** und nicht im Standard-Suchfeld enthalten, da sie oft zu False Positives führen.

Um Keywords explizit zu nutzen:
```json
{
  "search_fields": ["title", "description", "keywords", "url"]
}
```

**Wichtig:** Keywords beeinflussen das Similarity-Scoring nur, wenn sie explizit in `search_fields` angegeben sind.

## Match-Typen

| `match_source` | Bedeutung | Schwellenwert |
|----------------|-----------|---------------|
| `url_exact` | Normalisierte URLs identisch | **Immer Dublette** |
| `title` | Titel-basierter Treffer | Muss ≥ threshold sein |
| `description` | Beschreibungs-Treffer | Muss ≥ threshold sein |
| `keywords` | Keyword-Treffer | Muss ≥ threshold sein |
| `url` | URL-Suche (nicht exakt) | Muss ≥ threshold sein |

## Embedding-Modell

**Standard-Modell:** `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2`
- 50+ Sprachen unterstützt
- 384-dimensionale Embeddings
- GPU-Beschleunigung wenn verfügbar

### Modell wechseln

**Umgebungsvariable:**
```bash
# Linux/Mac
export EMBEDDING_MODEL="sentence-transformers/all-MiniLM-L6-v2"

# Windows PowerShell
$env:EMBEDDING_MODEL="sentence-transformers/all-MiniLM-L6-v2"
```

**Oder `.env` Datei:**
```
EMBEDDING_MODEL=sentence-transformers/all-MiniLM-L6-v2
```

Mehr Infos: https://huggingface.co/sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2

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
# CPU-Version
docker build -t wlo-duplicate-detection .
docker run -d -p 8000:8000 --name wlo-duplicate-detection wlo-duplicate-detection

# GPU-Version (NVIDIA)
docker build -f Dockerfile.gpu -t wlo-duplicate-detection:gpu .
docker run -d --gpus all -p 8000:8000 --name wlo-duplicate-detection wlo-duplicate-detection:gpu
```

### Konfiguration

Umgebungsvariablen in `docker-compose.yml` oder via `-e`:

| Variable | Default | Beschreibung |
|----------|---------|--------------|
| `EMBEDDING_MODEL` | `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2` | Embedding-Modell |
| `LOG_LEVEL` | `INFO` | Log-Level (`DEBUG`, `INFO`, `WARNING`, `ERROR`) |

**Debug-Modus aktivieren:**
```bash
# Für detaillierte Logs (Source/Candidate-Daten, Titel-Normalisierung)
LOG_LEVEL=DEBUG python run.py

# Oder in docker-compose.yml:
# LOG_LEVEL: DEBUG
```

### Dateien

| Datei | Beschreibung |
|-------|--------------|
| `Dockerfile` | CPU-Image (python:3.11-slim, ~1.5GB) |
| `Dockerfile.gpu` | GPU-Image (pytorch/cuda12.1, ~8GB) |
| `docker-compose.yml` | Orchestrierung mit Volume für Model-Cache |
| `.dockerignore` | Optimiert Build-Größe |

### Features

- **Health Check**: Automatische Überwachung (`/health` Endpoint)
- **Model Cache Volume**: Embedding-Modell wird persistent gespeichert
- **Non-root User**: Sicherheit durch unprivilegierten Benutzer
- **Restart Policy**: Automatischer Neustart bei Fehler

## Google Colab

Die API kann in Google Colab mit GPU-Unterstützung betrieben werden:

```python
# In Colab ausführen
!pip install -q sentence-transformers fastapi uvicorn

# GPU wird automatisch erkannt und genutzt
```

## Rate Limits

| Endpunkt | Rate Limit |
|----------|------------|
| `/detect/*` | 200/Minute |
| `/embed` | Kein Limit |
| `/hash` | Kein Limit |
| `/health` | Kein Limit |

## Credits

Die Hash-basierte Dublettenerkennung (MinHash) basiert auf dem Code von:
- **Original-Projekt:** https://github.com/yovisto/wlo-duplicate-detection
- **Autor:** Yovisto GmbH

## Technologien

- **FastAPI**: Web-Framework
- **Sentence-Transformers**: Embedding-Modell (GPU-Unterstützung)
- **NumPy**: Ähnlichkeitsberechnung
- **Pydantic**: Datenvalidierung
- **Loguru**: Logging
- **SlowAPI**: Rate Limiting
