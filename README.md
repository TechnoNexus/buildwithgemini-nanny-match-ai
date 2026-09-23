# 🧸 NannyMatch AI — Childcare Concierge & Placement Assistant

A conversational AI agent built on the **Google Agent Development Kit (ADK)** and deployed on **Google Cloud Agent Runtime**. NannyMatch AI helps families find qualified nannies, calculate payroll and employer tax estimates, inspect candidate profiles in Cloud Firestore, discover nearby kid-friendly spots, and generate custom candidate visual avatars and videos.

![NannyMatch AI Demo](./nanny_match_ai_demo.gif)

---

## 🚀 Key Features & Implemented Tools

The following capabilities are directly implemented in source code ([`app/agent.py`](file:///config/Desktop/Session1/nanny-match-ai/app/agent.py)):

### 1. 🗄️ Candidate Management (Google Cloud Firestore)
- **`search_nannies_firestore`**: Queries candidate nanny profiles in Google Cloud Firestore by location, maximum hourly rate, and CPR certification.
- **`add_nanny_firestore`**: Adds or updates candidate profiles with experience, rates, certifications, and bio details.

### 2. 🧠 Cross-Session Memory (Vertex AI Memory Bank)
- **`PreloadMemoryTool` & `add_session_to_memory`**: Automatically extracts and remembers family preferences, child ages, special needs, and hiring budgets across sessions.

### 3. 🧮 Payroll & Tax Calculation (Agent Engine Code Sandbox)
- **`calculate_payroll_and_taxes`**: Executed securely inside the `AgentEngineSandboxCodeExecutor` sandbox to compute regular pay, overtime rates, estimated employer taxes (~10% FICA/FUTA), and total monthly budget projections.

### 4. 🎨 Image & Video Generation (Vertex AI & Cloud Storage)
- **`generate_nanny_illustration`**: Generates candidate profile artwork or playroom visuals using `gemini-3.1-flash-lite-image` (in the `global` region). Saves the file to Playground Artifacts and uploads it to Google Cloud Storage.
- **`generate_nanny_video`**: Generates short demonstration videos using `gemini-omni-flash-preview` (Interactions API, `global` region). Saves the video to Playground Artifacts and uploads it to Google Cloud Storage.

### 5. 🗺️ Location & Nearby Services (Google Maps & Public APIs)
- **`geocode_address`**: Converts street addresses or landmark names into latitude/longitude coordinates via Google Geocoding API.
- **`find_nearby_places`**: Discovers nearby playgrounds, daycare centers, and pediatric clinics using Google Places API (New).
- **`lookup_zip_code_location`**: Fetches city, state, and coordinates for US ZIP codes using Zippopotam.us REST API.

### 6. 📱 Rich UI (A2UI v0.8 Basic Catalog)
- **`A2uiSchemaManager` & `a2ui_callback`**: Formats responses into structured A2UI card surfaces (Cards, Rows, Columns, Text, Images) for seamless display in compatible frontends.

### 7. 📋 Watchlist & Family Profiles (Session State)
- **`save_family_profile` & `get_my_profile`**: Manages family requirements and schedule preferences.
- **`add_to_watchlist` & `view_watchlist`**: Allows families to bookmark top candidate profiles.
- **`schedule_interview`**: Generates interview bookings for family-nanny meetings.

---

## 🔮 Status of Additional Features

- **RAG Engine Corpus Retrieval**: *Planned, not yet implemented.*

---

## 🛠️ Project Structure

```
.
├── app/
│   ├── agent.py            # Primary ADK agent definition & registered tools
│   └── a2ui_utils.py       # A2UI after_model_callback transformer
├── frontend/
│   ├── main.py             # FastAPI proxy connecting web browser to A2A Agent Runtime
│   ├── Dockerfile          # Container configuration for Cloud Run deployment
│   ├── requirements.txt    # Frontend dependencies (fastapi, uvicorn, a2a-sdk)
│   └── static/
│       └── index.html      # Rebranded frontend UI with embedded A2UI card renderer
├── agents-cli-manifest.yaml # Agent deployment manifest for Agent Runtime
├── nanny_match_ai_demo.gif # Animated demonstration recording
├── record_demo.js          # Playwright script for automated UI recording
└── requirements.txt        # Python backend dependencies
```

---

## ⚙️ Local Setup & Run Instructions

### Prerequisites
- Python 3.11+
- `google-agents-cli` installed
- Authenticated GCP credentials (`gcloud auth application-default login`)

### 1. Install Dependencies
```bash
uv venv
source .venv/bin/activate
uv pip install -r requirements.txt
```

### 2. Run Agent Locally with ADK Web UI
```bash
export GOOGLE_MAPS_API_KEY="<YOUR_GOOGLE_MAPS_API_KEY>"
adk web --port 8000 app
```

### 3. Run FastAPI Proxy Frontend Locally
```bash
cd frontend
export AGENT_ENGINE_RESOURCE_NAME="projects/<PROJECT_ID>/locations/<REGION>/reasoningEngines/<REASONING_ENGINE_ID>"
export AGENT_DIRECTORY="app"
uvicorn main:app --host 0.0.0.0 --port 8080
```

---

## ☁️ Deployment Instructions

### Deploy Agent to Vertex AI Agent Runtime
```bash
agents-cli deploy --project <PROJECT_ID> --region us-east1
```

### Deploy Web Frontend to Cloud Run
```bash
gcloud run deploy nanny-match-ai-frontend \
  --source ./frontend \
  --region us-east1 \
  --allow-unauthenticated \
  --set-env-vars AGENT_ENGINE_RESOURCE_NAME="projects/<PROJECT_ID>/locations/us-east1/reasoningEngines/<REASONING_ENGINE_ID>",AGENT_DIRECTORY="app" \
  --project <PROJECT_ID>
```
