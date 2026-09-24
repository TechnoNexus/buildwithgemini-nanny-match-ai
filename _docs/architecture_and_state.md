# Architecture & System State — NannyMatch AI

## Overview
**NannyMatch AI** is a dual-mode conversational concierge designed for childcare placement, payroll calculation, candidate profile inspection, and local family support. It is built on the **Google Agent Development Kit (ADK)** and features:
1. **100% Free Local Mode**: Uses Google AI Studio (`GEMINI_API_KEY`), local SQLite database (`data/nannies.db`), free OpenStreetMap Nominatim for geocoding and places search, and an in-process FastAPI runner. Zero GCP costs or cloud credentials required.
2. **Cloud Mode**: Deployed on Google Cloud Agent Runtime / Vertex AI Reasoning Engines with Firestore and Cloud Storage.

---

## Architecture Diagram

```
+-------------------------------------------------------------+
|                      Client Layer                           |
|  - Web UI (frontend/static/index.html with A2UI Renderer)    |
|  - Official ADK Web UI (python -m google.adk.cli web)        |
+------------------------------+------------------------------+
                               |
                               v
+-------------------------------------------------------------+
|               FastAPI Server (frontend/main.py)              |
|  - /chat (POST) -> Dispatches to Local Runner or Remote A2A  |
|  - /health (GET) -> Health & Active Mode Check              |
|  - /static/generated/ -> Local Artifact & Image Hosting      |
+------------------------------+------------------------------+
                               |
                               v
+-------------------------------------------------------------+
|               ADK Agent Layer (app/agent.py)                 |
|  - Model: Gemini (gemini-2.5-flash via GEMINI_API_KEY)      |
|  - A2UI v0.8 Callback: Formats response into rich cards     |
|  - Session State: Watchlist, Family Profile, Preferences    |
+------------------------------+------------------------------+
                               |
      +------------------------+------------------------+
      |                                                 |
      v                                                 v
+-----------------------------+   +-----------------------------+
|   Data Storage & Persistence|   |  External Services & Tools  |
| - Local SQLite (app/db.py)  |   | - Payroll & Tax Calculation |
|   nannies.db: id, name,     |   | - OpenStreetMap Geocoding   |
|   location, hourly_rate,    |   | - OpenStreetMap Places      |
|   cpr_certified, etc.       |   | - Zippopotam.us ZIP API     |
| - Fallback: Cloud Firestore |   | - Imagen 3 / Gemini Media   |
+-----------------------------+   +-----------------------------+
```

---

## Data Models

### Nanny Candidate (`nannies` table in SQLite)
| Field | Type | Description |
| :--- | :--- | :--- |
| `id` | TEXT PRIMARY KEY | Candidate identifier (e.g. `nanny-01`) |
| `name` | TEXT | Candidate full name |
| `location` | TEXT | City / metropolitan area (e.g. `San Francisco`) |
| `hourly_rate` | REAL | Standard hourly rate in USD |
| `years_experience` | INTEGER | Total years of childcare experience |
| `cpr_certified` | INTEGER (0/1) | CPR certification status |
| `bio` | TEXT | Professional background summary |
| `specialties` | TEXT (JSON) | Array of special skills (e.g. `["Infant Care", "First Aid"]`) |
| `availability` | TEXT | Schedule availability (e.g. `Full-time (Mon-Fri 8am-5pm)`) |
| `rating` | REAL | Average family rating (out of 5.0) |
| `updated_at` | TEXT | ISO timestamp of last update |

### Session State (`tool_context.state`)
- `watchlist`: List of saved nanny IDs or job postings.
- `family_profile`: Dictionary containing children count/ages, location, max hourly budget, and special notes.

---

## Active Configuration & Fallbacks

| Feature | Local Free Mode (Default) | Cloud Deployed Mode |
| :--- | :--- | :--- |
| **LLM Provider** | Google AI Studio (`GEMINI_API_KEY`) | Vertex AI Reasoning Engine |
| **Model** | `gemini-2.5-flash` | `gemini-3.8-flash` / Vertex |
| **Database** | SQLite (`data/nannies.db`) | Google Cloud Firestore |
| **Geocoding** | OpenStreetMap Nominatim (Free) | Google Geocoding API (`GOOGLE_MAPS_API_KEY`) |
| **Places Search** | OpenStreetMap Nominatim (Free) | Google Places API (New) |
| **ZIP Code Lookup** | Zippopotam.us (Free) | Zippopotam.us (Free) |
| **Image Hosting** | Local `/static/generated/` folder | Google Cloud Storage (GCS) |
| **Frontend Proxy** | In-process `InMemoryRunner` | Remote A2A proxy (`a2a-sdk`) |
