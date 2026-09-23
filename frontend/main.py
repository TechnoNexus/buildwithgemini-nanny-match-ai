"""Minimal FastAPI proxy for a deployed A2A agent (Agent Runtime, agents-cli 1.1.0+).

The browser talks ONLY to this proxy (same origin, no CORS, no GCP creds in the
browser). The proxy authenticates with Application Default Credentials and
forwards chat to the deployed agent over the A2A protocol, returning replies as
structured parts the chat UI knows how to show:

  * {"kind": "text", "text": ...}  -> a normal chat bubble
  * {"kind": "a2ui", "data": ...}  -> one A2UI message (beginRendering /
    surfaceUpdate); static/index.html renders these as a card.
"""

import os
import uuid

import google.auth
import google.auth.transport.requests
import httpx
from a2a.client import ClientConfig, ClientFactory
from a2a.types import (
    AgentCard,
    Message,
    Part,
    Role,
    SendMessageRequest,
    TaskArtifactUpdateEvent,
)
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from google.protobuf.json_format import MessageToDict

# The agent tags its A2UI data parts with this mime type.
_A2UI_MIME = "application/json+a2ui"

# Lazy-loaded ADC credentials
_creds = None


def _get_a2a_base() -> str:
    res = os.environ.get("AGENT_ENGINE_RESOURCE_NAME", "")
    if not res:
        raise ValueError("AGENT_ENGINE_RESOURCE_NAME environment variable is required")
    loc = res.split("/locations/")[1].split("/")[0] if "/locations/" in res else "us-east1"
    dir_name = os.environ.get("AGENT_DIRECTORY", "app")
    return (
        f"https://{loc}-aiplatform.googleapis.com/reasoningEngines/v1/"
        f"{res}/api/a2a/{dir_name}"
    )


def _auth_headers() -> dict[str, str]:
    global _creds
    if _creds is None:
        _creds, _ = google.auth.default(
            scopes=["https://www.googleapis.com/auth/cloud-platform"]
        )
    _creds.refresh(google.auth.transport.requests.Request())
    return {
        "Authorization": f"Bearer {_creds.token}",
        "Content-Type": "application/json",
    }


app = FastAPI()


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.exception_handler(Exception)
async def _json_errors(request: Request, exc: Exception):
    # Always return JSON so the browser never receives a plain-text 500 page
    return JSONResponse(
        status_code=200,
        content={
            "parts": [{"kind": "text", "text": f"Error: {type(exc).__name__}: {exc}"}]
        },
    )


# Reuse ONE A2A context per user so the agent remembers the conversation.
_contexts: dict[str, str] = {}


def _extract_parts(parts: list) -> list[dict]:
    """Turn A2A response parts into structured parts for the chat UI."""
    out: list[dict] = []
    for p in parts:
        p_dict = MessageToDict(p) if hasattr(p, "DESCRIPTOR") else (
            p.model_dump() if hasattr(p, "model_dump") else p
        )
        if not isinstance(p_dict, dict):
            continue

        if "text" in p_dict and p_dict["text"]:
            out.append({"kind": "text", "text": p_dict["text"]})

        data_obj = p_dict.get("data")
        if isinstance(data_obj, dict):
            mime = data_obj.get("metadata", {}).get("mimeType", "")
            data_content = data_obj.get("data")
            if (
                mime == _A2UI_MIME
                or "a2ui" in str(mime)
                or "surfaceUpdate" in str(data_content)
                or "beginRendering" in str(data_content)
            ):
                out.append({"kind": "a2ui", "data": data_content})
        elif data_obj:
            out.append({"kind": "a2ui", "data": data_obj})

        file_uri = p_dict.get("file", {}).get("uri") or p_dict.get("url")
        if file_uri:
            out.append({"kind": "text", "text": file_uri})
    return out


@app.post("/chat")
async def chat(req: Request):
    body = await req.json()
    message = body.get("message", "")
    user_id = body.get("user_id") or "web-user"
    parts: list[dict] = []

    a2a_base = _get_a2a_base()

    async with httpx.AsyncClient(headers=_auth_headers(), timeout=120) as client:
        try:
            factory = ClientFactory(ClientConfig(httpx_client=client))
            a2a_client = await factory.create_from_url(a2a_base)

            user_role = getattr(Role, "ROLE_USER", getattr(Role, "user", None))
            msg = Message(
                message_id=str(uuid.uuid4()),
                role=user_role,
                parts=[Part(text=message)],
                context_id=_contexts.get(user_id),
            )

            req_obj = SendMessageRequest(message=msg)
            async for event in a2a_client.send_message(req_obj):
                if isinstance(event, tuple):
                    task, update = event
                    if task is not None and getattr(task, "context_id", None):
                        _contexts[user_id] = task.context_id
                    if isinstance(update, TaskArtifactUpdateEvent):
                        parts.extend(_extract_parts(update.artifact.parts))
                elif hasattr(event, "HasField"):
                    if event.HasField("status_update"):
                        if getattr(event.status_update, "context_id", None):
                            _contexts[user_id] = event.status_update.context_id
                    if event.HasField("artifact_update"):
                        art = event.artifact_update.artifact
                        parts.extend(_extract_parts(art.parts))
                    elif event.HasField("message"):
                        parts.extend(_extract_parts(event.message.parts))
        except Exception as e:
            parts.append({"kind": "text", "text": f"Proxy Error: {str(e)}"})

    if not parts:
        parts = [{"kind": "text", "text": "(The agent didn't return a reply.)"}]
    return JSONResponse({"parts": parts})


STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")
# Serve the chat UI (keep this mount last so /chat wins).
app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))
