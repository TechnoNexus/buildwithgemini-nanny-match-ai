"""FastAPI server for NannyMatch AI.

Supports both:
1. Local Free Mode (Default): Runs the agent in-process using Google ADK's
   InMemoryRunner and free Google AI Studio GEMINI_API_KEY. No GCP credentials,
   no Reasoning Engines, and zero billing required.
2. Deployed Cloud Mode: Forwards chat to a deployed A2A agent runtime when
   AGENT_ENGINE_RESOURCE_NAME is configured.
"""

import json
import os
import re
import uuid
from typing import Any, Dict, List, Optional

from dotenv import load_dotenv

_env_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env")
if os.path.exists(_env_path):
    load_dotenv(_env_path, override=True)
else:
    load_dotenv(override=True)

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

# Setup directory paths
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATIC_DIR = os.path.join(BASE_DIR, "static")
GENERATED_DIR = os.path.join(STATIC_DIR, "generated")
os.makedirs(GENERATED_DIR, exist_ok=True)

# The agent tags its A2UI data parts with this mime type.
_A2UI_MIME = "application/json+a2ui"
_TAG_RE = re.compile(r"</?a2a_datapart_json>")

app = FastAPI(title="NannyMatch AI")

# Allow CORS for mobile app and Vite dev server
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Check if we are running with a remote Reasoning Engine or local in-process agent
AGENT_ENGINE_RESOURCE_NAME = os.environ.get("AGENT_ENGINE_RESOURCE_NAME", "").strip()
IS_REMOTE_MODE = bool(AGENT_ENGINE_RESOURCE_NAME)

# In-memory runner and sessions for local mode
_local_runner = None
_user_sessions: Dict[str, str] = {}


def get_local_runner():
    """Initializes and returns an InMemoryRunner for local execution."""
    global _local_runner
    if _local_runner is None:
        from google.adk.runners import InMemoryRunner
        from app.agent import root_agent
        _local_runner = InMemoryRunner(agent=root_agent)
    return _local_runner


def _extract_a2ui_from_blob(blob_bytes: bytes) -> Optional[Dict[str, Any]]:
    """Extracts A2UI dictionary payload from an a2a_datapart_json blob."""
    try:
        text = blob_bytes.decode("utf-8")
        clean = _TAG_RE.sub("", text).strip()
        data = json.loads(clean)
        if isinstance(data, dict):
            if "data" in data:
                return data["data"]
            return data
    except Exception:
        pass
    return None


@app.get("/health")
async def health():
    mode = "remote_reasoning_engine" if IS_REMOTE_MODE else "local_free_mode"
    return {"status": "ok", "mode": mode}


@app.exception_handler(Exception)
async def _json_errors(request: Request, exc: Exception):
    # Always return JSON so the browser never receives a plain-text 500 page
    return JSONResponse(
        status_code=200,
        content={
            "parts": [{"kind": "text", "text": f"Error: {type(exc).__name__}: {exc}"}]
        },
    )


# -----------------------------------------------------------------------------
# Local In-Process Agent Execution (Zero GCP Dependencies)
# -----------------------------------------------------------------------------
async def chat_local(message: str, user_id: str) -> List[Dict[str, Any]]:
    """Runs the agent locally using ADK InMemoryRunner."""
    from google.genai import types

    runner = get_local_runner()
    
    # Retrieve or create session for user
    session_id = _user_sessions.get(user_id)
    if not session_id:
        session = await runner.session_service.create_session(app_name=runner.app_name, user_id=user_id)
        session_id = session.id
        _user_sessions[user_id] = session_id

    content = types.Content(
        role="user",
        parts=[types.Part(text=message)],
    )

    parts: List[Dict[str, Any]] = []

    async for event in runner.run_async(
        user_id=user_id,
        session_id=session_id,
        new_message=content,
    ):
        if not event.content or not event.content.parts:
            continue

        for p in event.content.parts:
            # Check for text part
            if p.text:
                parts.append({"kind": "text", "text": p.text})

            # Check for A2UI blob wrapped by a2ui_callback
            if p.inline_data and p.inline_data.data:
                a2ui_data = _extract_a2ui_from_blob(p.inline_data.data)
                if a2ui_data:
                    parts.append({"kind": "a2ui", "data": a2ui_data})

    return parts


# -----------------------------------------------------------------------------
# Remote Agent Engine A2A Proxy (Cloud Deployed Mode)
# -----------------------------------------------------------------------------
_creds = None
_remote_contexts: Dict[str, str] = {}


def _get_a2a_base() -> str:
    res = AGENT_ENGINE_RESOURCE_NAME
    loc = res.split("/locations/")[1].split("/")[0] if "/locations/" in res else "us-east1"
    dir_name = os.environ.get("AGENT_DIRECTORY", "app")
    return (
        f"https://{loc}-aiplatform.googleapis.com/reasoningEngines/v1/"
        f"{res}/api/a2a/{dir_name}"
    )


def _auth_headers() -> Dict[str, str]:
    global _creds
    import google.auth
    import google.auth.transport.requests
    if _creds is None:
        _creds, _ = google.auth.default(
            scopes=["https://www.googleapis.com/auth/cloud-platform"]
        )
    _creds.refresh(google.auth.transport.requests.Request())
    return {
        "Authorization": f"Bearer {_creds.token}",
        "Content-Type": "application/json",
    }


async def chat_remote(message: str, user_id: str) -> List[Dict[str, Any]]:
    """Proxies request to deployed Vertex AI Reasoning Engine over A2A."""
    import httpx
    from a2a.client import ClientConfig, ClientFactory
    from a2a.types import Message, Part, Role, SendMessageRequest, TaskArtifactUpdateEvent
    from google.protobuf.json_format import MessageToDict

    parts: List[Dict[str, Any]] = []
    a2a_base = _get_a2a_base()

    async with httpx.AsyncClient(headers=_auth_headers(), timeout=120) as client:
        factory = ClientFactory(ClientConfig(httpx_client=client))
        a2a_client = await factory.create_from_url(a2a_base)

        user_role = getattr(Role, "ROLE_USER", getattr(Role, "user", None))
        msg = Message(
            message_id=str(uuid.uuid4()),
            role=user_role,
            parts=[Part(text=message)],
            context_id=_remote_contexts.get(user_id),
        )

        req_obj = SendMessageRequest(message=msg)
        async for event in a2a_client.send_message(req_obj):
            if isinstance(event, tuple):
                task, update = event
                if task is not None and getattr(task, "context_id", None):
                    _remote_contexts[user_id] = task.context_id
                if isinstance(update, TaskArtifactUpdateEvent):
                    for p in update.artifact.parts:
                        p_dict = MessageToDict(p) if hasattr(p, "DESCRIPTOR") else p
                        if isinstance(p_dict, dict) and p_dict.get("text"):
                            parts.append({"kind": "text", "text": p_dict["text"]})
            elif hasattr(event, "HasField"):
                if event.HasField("status_update") and getattr(event.status_update, "context_id", None):
                    _remote_contexts[user_id] = event.status_update.context_id
                if event.HasField("message"):
                    for p in event.message.parts:
                        p_dict = MessageToDict(p) if hasattr(p, "DESCRIPTOR") else p
                        if isinstance(p_dict, dict) and p_dict.get("text"):
                            parts.append({"kind": "text", "text": p_dict["text"]})

    return parts


# -----------------------------------------------------------------------------
# Main Chat Endpoint
# -----------------------------------------------------------------------------
@app.post("/chat")
async def chat(req: Request):
    body = await req.json()
    message = body.get("message", "").strip()
    user_id = body.get("user_id") or "web-user"

    if not message:
        return JSONResponse({"parts": [{"kind": "text", "text": "Please provide a message."}]})

    try:
        if IS_REMOTE_MODE:
            parts = await chat_remote(message=message, user_id=user_id)
        else:
            parts = await chat_local(message=message, user_id=user_id)
    except Exception as e:
        parts = [{"kind": "text", "text": f"Agent Error: {str(e)}"}]

    if not parts:
        parts = [{"kind": "text", "text": "(The agent didn't return a reply.)"}]

    return JSONResponse({"parts": parts})


# Mount static files
app.mount("/static/generated", StaticFiles(directory=GENERATED_DIR), name="generated")
app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))
