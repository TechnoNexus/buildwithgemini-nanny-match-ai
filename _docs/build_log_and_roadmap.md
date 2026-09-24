# Build Log & Roadmap — NannyMatch AI

## Roadmap & Status

- [x] **Phase 1: Project Migration to Local Environment**
  - [x] Create dedicated development branch `feat/local-free-mode` to preserve upstream code.
  - [x] Verify local Python environment and install core requirements (`google-adk`, `a2ui-agent-sdk`, `a2a-sdk`).
- [x] **Phase 2: 100% Free Local Mode Implementation**
  - [x] Implement local SQLite database manager (`app/db.py`) with automatic schema initialization and seeding.
  - [x] Create standalone seeding script (`seed_local.py`).
  - [x] Update candidate management tools (`search_nannies_firestore`, `add_nanny_firestore`) to seamlessly query local SQLite when cloud Firestore is not configured.
  - [x] Implement free OpenStreetMap Nominatim fallbacks for `geocode_address` and `find_nearby_places` when `GOOGLE_MAPS_API_KEY` is omitted.
  - [x] Decouple Vertex AI Reasoning Engine sandbox executor from payroll calculations (which run natively in Python).
  - [x] Gracefully handle Vertex AI Memory Bank in local mode without runtime crashes.
  - [x] Add local image storage in `frontend/static/generated/` for domain illustrations.
  - [x] Update `frontend/main.py` to support dual-mode execution (local in-process ADK `InMemoryRunner` vs. deployed A2A proxy).
  - [x] Update frontend UI regex in `frontend/static/index.html` to render local static images in A2UI cards.
  - [x] Update `.env.example` and `README.md` with complete local free setup instructions.
- [ ] **Phase 3: Extended Local Enhancements**
  - [ ] Add CSV export for nanny candidate search results.
  - [ ] Add RAG corpus retrieval with local ChromaDB or SQLite-vec.
  - [ ] Add conversation history export to JSON.

---

## Build Log

### 2026-09-24 — Local Free Mode Architecture Refactoring
- **Branch**: `feat/local-free-mode`
- **Motivation**: Project originally depended on paid GCP Cloud APIs (Vertex AI Reasoning Engines, Firestore on expired Qwiklabs tenant, GCS, Google Maps API). Needed to run 100% free locally using only a standard `GEMINI_API_KEY`.
- **Changes**:
  1. Created `app/db.py` for persistent, local SQLite candidate storage.
  2. Refactored `app/agent.py` to make GCP packages optional, route Firestore calls to SQLite by default, and use OpenStreetMap for geocoding and places lookups.
  3. Refactored `frontend/main.py` to run `InMemoryRunner` directly in-process when `AGENT_ENGINE_RESOURCE_NAME` is absent.
  4. Updated `frontend/static/index.html` to support local `/static/generated/` URLs in A2UI Image components.
  5. Created `seed_local.py` for reproducible local database seeding.
  6. Updated `.gitignore`, `.env.example`, and `README.md`.
  7. Verified end-to-end chat turn with Gemini 3.5 Flash (`gemini-3.5-flash`), local SQLite database querying, and A2UI card generation.
  8. Verified FastAPI local server running on port 8080 with active mode `local_free_mode`.
