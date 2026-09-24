# AI Integration Pipeline — NannyMatch AI

## Agent Architecture
- **Framework**: Google Agent Development Kit (ADK)
- **Model**: `gemini-2.5-flash` (or configurable via `MODEL` environment variable)
- **Execution Engine**: `google.adk.runners.InMemoryRunner` (Local) / Vertex AI Reasoning Engines (Cloud)
- **UI Protocol**: A2UI v0.8 Basic Catalog (Cards, Rows, Columns, Text, Images)

---

## Tool Execution Pipeline

```
User Query
   │
   ▼
A2UI System Prompt + Schema Manager
   │
   ▼
Gemini Model (gemini-2.5-flash)
   │
   ├── Tool Calling:
   │    ├── search_nannies_firestore    -> SQLite (data/nannies.db) or Cloud Firestore
   │    ├── add_nanny_firestore         -> SQLite (data/nannies.db) or Cloud Firestore
   │    ├── calculate_payroll_and_taxes -> Local Python function (FICA/FUTA math)
   │    ├── lookup_zip_code_location    -> Zippopotam.us REST API (Free)
   │    ├── geocode_address             -> Google Geocoding or OpenStreetMap Nominatim
   │    ├── find_nearby_places          -> Google Places or OpenStreetMap Nominatim
   │    ├── generate_nanny_illustration -> Imagen 3 / Gemini + Local File Storage
   │    ├── generate_nanny_video        -> Gemini Omni (Vertex) / Local storyboard
   │    ├── add_to_watchlist            -> Session State (`tool_context.state`)
   │    ├── view_watchlist              -> Session State (`tool_context.state`)
   │    ├── save_family_profile         -> Session State (`tool_context.state`)
   │    ├── get_my_profile              -> Session State (`tool_context.state`)
   │    └── schedule_interview          -> In-memory booking confirmation
   │
   ▼
after_model_callback (`a2ui_callback`)
   │
   ▼
Output Packaging:
   ├── Text Part (`{"kind": "text", "text": "..."}`)
   └── A2UI Data Part (`{"kind": "a2ui", "data": {...}}`)
   │
   ▼
Rendered in Browser (frontend/static/index.html)
```

---

## Reusing This Agent Across Other Apps

### 1. Reusing via Local HTTP / REST Microservice
`frontend/main.py` exposes a clean JSON endpoint:
- **URL**: `http://localhost:8080/chat`
- **Method**: `POST`
- **Payload**:
  ```json
  {
    "message": "Find CPR certified nannies in San Francisco under $30/hr",
    "user_id": "client_app_123"
  }
  ```
- **Response**:
  ```json
  {
    "parts": [
      {
        "kind": "text",
        "text": "..."
      },
      {
        "kind": "a2ui",
        "data": { ... }
      }
    ]
  }
  ```
Any application (React, Next.js, mobile app, desktop tool, or automation script) can call this endpoint locally without needing any cloud credentials.

### 2. Direct Python Import
In another Python project:
```python
from app.agent import root_agent
from google.adk.runners import InMemoryRunner

runner = InMemoryRunner(agent=root_agent)
```

### 3. Multi-Agent Systems
The `root_agent` can be nested under a parent supervisor agent in Google ADK:
```python
from app.agent import root_agent as nanny_agent
from google.adk.agents import Agent

concierge_agent = Agent(
    name="concierge",
    sub_agents=[nanny_agent],
)
```
