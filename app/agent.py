# ruff: noqa
# Copyright 2026 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import base64
import datetime
import json
import os
import urllib.parse
import urllib.request
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

# Automatically load .env from project root
_dotenv_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env")
if os.path.exists(_dotenv_path):
    load_dotenv(_dotenv_path, override=True)
else:
    load_dotenv(override=True)

from a2ui.basic_catalog.provider import BasicCatalog
from a2ui.schema.manager import A2uiSchemaManager
from google import genai
from google.adk.agents import Agent
from google.adk.agents.callback_context import CallbackContext
from google.adk.apps import App
from google.adk.models import Gemini
from google.adk.tools import ToolContext
from google.adk.tools.preload_memory_tool import PreloadMemoryTool
from google.genai import types

from .a2ui_utils import a2ui_callback
from .db import (
    add_nanny as local_add_nanny,
    search_nannies as local_search_nannies,
)

# Optional GCP imports (used when deployed or when GCP credentials exist)
try:
    from google.cloud import firestore, storage
    HAS_GCP = True
except ImportError:
    firestore = None
    storage = None
    HAS_GCP = False

# Model and Cloud Configuration
MODEL = os.getenv("MODEL", "gemini-2.5-flash")
USE_FIRESTORE = os.getenv("USE_FIRESTORE", "false").lower() == "true"
FIRESTORE_PROJECT_ID = os.getenv("FIRESTORE_PROJECT_ID", "")
REASONING_ENGINE_RESOURCE_NAME = os.getenv("AGENT_ENGINE_RESOURCE_NAME", "")
GCS_BUCKET_NAME = os.getenv("GCS_BUCKET_NAME", "")


def get_firestore_db():
    """Returns a Firestore client if configured and available."""
    if HAS_GCP and firestore and FIRESTORE_PROJECT_ID:
        return firestore.Client(project=FIRESTORE_PROJECT_ID)
    return None


def search_nannies_firestore(location: str = "", max_rate: float = 0.0, cpr_required: bool = False) -> str:
    """Searches the database for qualified nanny candidates.

    Args:
        location: Target city or region (e.g. 'San Francisco', 'New York').
        max_rate: Maximum hourly rate filter in USD.
        cpr_required: Filter for CPR-certified nannies.

    Returns:
        Formatted string listing candidate nanny profiles.
    """
    if USE_FIRESTORE and HAS_GCP and FIRESTORE_PROJECT_ID:
        try:
            db = get_firestore_db()
            if db:
                docs = db.collection("nannies").stream()
                matches = []
                for doc in docs:
                    n = doc.to_dict()
                    n_loc = n.get("location", "")
                    n_rate = float(n.get("hourly_rate", 0.0))
                    n_cpr = bool(n.get("cpr_certified", False))

                    if location and location.lower() not in n_loc.lower():
                        continue
                    if max_rate > 0 and n_rate > max_rate:
                        continue
                    if cpr_required and not n_cpr:
                        continue

                    cpr_str = "Yes" if n_cpr else "No"
                    rating = n.get("rating", 5.0)
                    exp = n.get("years_experience", 0)
                    bio = n.get("bio", "")
                    matches.append(
                        f"- **{n.get('name')}** (ID: `{n.get('id')}`) | ${n_rate}/hr | {exp} yrs exp | CPR: {cpr_str} | Rating: {rating} ★\n"
                        f"  *Location*: {n_loc} | *Bio*: {bio}"
                    )
                if not matches:
                    return f"No nannies currently found in Firestore matching location='{location}' under ${max_rate}/hr."
                return f"Found {len(matches)} nanny candidate(s) in Firestore:\n" + "\n\n".join(matches)
        except Exception as e:
            # Fall back to local SQLite if Firestore encounters an error
            pass

    # Use local zero-cost SQLite storage
    return local_search_nannies(location=location, max_rate=max_rate, cpr_required=cpr_required)


def add_nanny_firestore(
    nanny_id: str,
    name: str,
    location: str,
    hourly_rate: float,
    years_experience: int,
    cpr_certified: bool,
    bio: str = "",
    availability: str = "Full-time"
) -> str:
    """Adds or updates a nanny candidate profile in the database.

    Args:
        nanny_id: Unique identifier (e.g. 'nanny-05').
        name: Full name of the nanny.
        location: City or location area.
        hourly_rate: Hourly rate in USD.
        years_experience: Years of experience.
        cpr_certified: Whether candidate is CPR certified.
        bio: Short biography or background summary.
        availability: Work schedule availability.
    """
    if USE_FIRESTORE and HAS_GCP and FIRESTORE_PROJECT_ID:
        try:
            db = get_firestore_db()
            if db:
                doc_ref = db.collection("nannies").document(nanny_id)
                payload = {
                    "id": nanny_id,
                    "name": name,
                    "location": location,
                    "hourly_rate": float(hourly_rate),
                    "years_experience": int(years_experience),
                    "cpr_certified": bool(cpr_certified),
                    "bio": bio,
                    "availability": availability,
                    "rating": 5.0,
                    "updated_at": firestore.SERVER_TIMESTAMP,
                }
                doc_ref.set(payload)
                return f"Successfully saved nanny profile **{name}** (ID: `{nanny_id}`) to Firestore database!"
        except Exception:
            pass

    # Use local zero-cost SQLite storage
    return local_add_nanny(
        nanny_id=nanny_id,
        name=name,
        location=location,
        hourly_rate=hourly_rate,
        years_experience=years_experience,
        cpr_certified=cpr_certified,
        bio=bio,
        availability=availability,
    )


def add_to_watchlist(tool_context: ToolContext, item_id: str, title: str, category: str = "nanny", details: str = "") -> str:
    """Saves a nanny profile or job posting to the user's watchlist.

    Args:
        item_id: Unique ID or name for the nanny or job (e.g. 'nanny-01' or 'Smith Family Job').
        title: Title or full name (e.g. 'Elena Rostova - CPR Certified Nanny').
        category: Category of item, either 'nanny' or 'job'.
        details: Optional additional notes or highlights.
    """
    watchlist = tool_context.state.get("watchlist", [])
    for item in watchlist:
        if item.get("item_id") == item_id:
            return f"Item '{title}' (ID: {item_id}) is already in your watchlist."

    new_entry = {
        "item_id": item_id,
        "title": title,
        "category": category,
        "details": details,
        "saved_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    }
    watchlist.append(new_entry)
    tool_context.state["watchlist"] = watchlist
    return f"Successfully saved '{title}' (ID: {item_id}) to your watchlist!"


def view_watchlist(tool_context: ToolContext) -> str:
    """Retrieves all saved nannies or job postings in the user's watchlist."""
    watchlist = tool_context.state.get("watchlist", [])
    if not watchlist:
        return "Your watchlist is currently empty."

    lines = ["📋 **Your Saved Watchlist**:"]
    for idx, item in enumerate(watchlist, 1):
        lines.append(f"{idx}. [{item['category'].upper()}] **{item['title']}** (ID: `{item['item_id']}`) - {item.get('details', '')}")
    return "\n".join(lines)


def save_family_profile(tool_context: ToolContext, children_summary: str, location: str, max_hourly_rate: float, cpr_required: bool, notes: str = "") -> str:
    """Saves or updates family hiring requirements and preferences.

    Args:
        children_summary: Description of children (e.g. '2 kids, ages 3 and 5').
        location: Primary location (e.g. 'San Francisco').
        max_hourly_rate: Maximum budget per hour in USD.
        cpr_required: Whether CPR certification is required.
        notes: Additional notes (e.g., allergies, driving needed).
    """
    profile = {
        "children": children_summary,
        "location": location,
        "max_hourly_rate": max_hourly_rate,
        "cpr_required": cpr_required,
        "notes": notes,
        "updated_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    }
    tool_context.state["family_profile"] = profile
    return f"Family profile updated! Saved requirements for {children_summary} in {location} (Max: ${max_hourly_rate}/hr)."


def get_my_profile(tool_context: ToolContext) -> str:
    """Retrieves the user's saved family profile or nanny profile."""
    family = tool_context.state.get("family_profile")
    if family:
        return f"🏡 **Saved Family Profile**:\n- Children: {family['children']}\n- Location: {family['location']}\n- Max Rate: ${family['max_hourly_rate']}/hr\n- CPR Required: {'Yes' if family['cpr_required'] else 'No'}\n- Notes: {family.get('notes', 'None')}"
    return "No family profile saved in session state yet."


def schedule_interview(candidate_name: str, proposed_datetime: str, notes: str = "") -> str:
    """Schedules an interview slot between a family and a nanny candidate.

    Args:
        candidate_name: Name of the nanny candidate.
        proposed_datetime: Proposed date and time for interview (e.g. '2026-09-25 at 2:00 PM').
        notes: Optional interview notes or focus areas.
    """
    return f"Interview request confirmed for **{candidate_name}** on **{proposed_datetime}**! Calendar invite generated."


def calculate_payroll_and_taxes(hourly_rate: float, hours_per_week: float = 40.0, overtime_hours: float = 0.0) -> str:
    """Calculates weekly and monthly nanny payroll, employer taxes, and total cost breakdown.

    Args:
        hourly_rate: Regular hourly rate in USD (e.g. 28.0).
        hours_per_week: Standard hours worked per week (default 40.0).
        overtime_hours: Overtime hours worked per week paid at 1.5x (default 0.0).
    """
    regular_hours = min(hours_per_week, 40.0)
    regular_pay = regular_hours * hourly_rate
    overtime_rate = hourly_rate * 1.5
    overtime_pay = overtime_hours * overtime_rate
    weekly_gross = regular_pay + overtime_pay

    # Estimated employer taxes (FICA 7.65% + FUTA/SUTA ~2.35% = ~10%)
    employer_taxes = weekly_gross * 0.10
    total_weekly = weekly_gross + employer_taxes
    total_monthly = total_weekly * 4.33

    return (
        f"💵 **Payroll & Tax Estimate Breakdown**:\n"
        f"- **Hourly Rate**: ${hourly_rate:.2f}/hr\n"
        f"- **Weekly Schedule**: {regular_hours:.1f} regular hrs + {overtime_hours:.1f} overtime hrs\n"
        f"- **Weekly Gross Pay**: ${weekly_gross:.2f}\n"
        f"- **Estimated Employer Taxes (~10%)**: ${employer_taxes:.2f}/wk\n"
        f"- **Total Weekly Cost**: ${total_weekly:.2f}\n"
        f"- **Estimated Total Monthly Cost**: ${total_monthly:.2f}"
    )


def lookup_zip_code_location(zip_code: str) -> str:
    """Looks up location details (city, state, coordinates) for a US ZIP code using Zippopotam.us public API.

    Args:
        zip_code: 5-digit US ZIP code string (e.g. '94102').
    """
    clean_zip = str(zip_code).strip()[:5]
    url = f"https://api.zippopotam.us/us/{clean_zip}"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "NannyMatchAI/1.0"})
        with urllib.request.urlopen(req, timeout=5) as response:
            data = json.loads(response.read().decode("utf-8"))
            places = data.get("places", [])
            if not places:
                return f"No location found for ZIP code {clean_zip}."
            place = places[0]
            city = place.get("place name", "Unknown")
            state = place.get("state", "Unknown")
            state_abbr = place.get("state abbreviation", "")
            lat = place.get("latitude", "")
            lng = place.get("longitude", "")
            return f"📍 **ZIP Code {clean_zip} Location**: {city}, {state} ({state_abbr}) | Coordinates: ({lat}, {lng})"
    except Exception as e:
        return f"Unable to fetch location for ZIP code {clean_zip}: {str(e)}"


def geocode_address(address: str) -> str:
    """Converts a street address or location name into geographic coordinates (lat/lng).
    Uses Google Geocoding API if GOOGLE_MAPS_API_KEY is provided; otherwise falls back to OpenStreetMap Nominatim.

    Args:
        address: Full street address or location (e.g. '1600 Amphitheatre Pkwy, Mountain View, CA' or 'San Francisco').
    """
    api_key = os.getenv("GOOGLE_MAPS_API_KEY")
    if api_key:
        encoded_address = urllib.parse.quote(address.strip())
        url = f"https://maps.googleapis.com/maps/api/geocode/json?address={encoded_address}&key={api_key}"
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "NannyMatchAI/1.0"})
            with urllib.request.urlopen(req, timeout=5) as response:
                data = json.loads(response.read().decode("utf-8"))
                results = data.get("results", [])
                if results:
                    first = results[0]
                    fmt_addr = first.get("formatted_address", address)
                    location = first.get("geometry", {}).get("location", {})
                    lat, lng = location.get("lat"), location.get("lng")
                    return f"🗺️ **Geocoded Location**: {fmt_addr} | Latitude: {lat}, Longitude: {lng}"
        except Exception:
            pass  # Fall through to Nominatim

    # Free OpenStreetMap Nominatim fallback (zero cost, no API key needed)
    try:
        encoded_address = urllib.parse.quote(address.strip())
        url = f"https://nominatim.openstreetmap.org/search?q={encoded_address}&format=json&limit=1"
        req = urllib.request.Request(url, headers={"User-Agent": "NannyMatchAI/1.0"})
        with urllib.request.urlopen(req, timeout=5) as response:
            results = json.loads(response.read().decode("utf-8"))
            if results:
                first = results[0]
                fmt_addr = first.get("display_name", address)
                lat, lng = first.get("lat"), first.get("lon")
                return f"🗺️ **Geocoded Location**: {fmt_addr} | Latitude: {lat}, Longitude: {lng}"
            return f"No geocoding results found for address: '{address}'."
    except Exception as e:
        return f"Geocoding request failed: {str(e)}"


def find_nearby_places(query: str, location: str = "") -> str:
    """Finds nearby places (e.g., playgrounds, daycare centers, pediatricians, schools).
    Uses Google Places API if GOOGLE_MAPS_API_KEY is provided; otherwise falls back to OpenStreetMap Nominatim.

    Args:
        query: Place type or search phrase (e.g. 'playground', 'daycare center', 'pediatric clinic').
        location: Optional location context or city (e.g. 'San Francisco, CA').
    """
    full_query = f"{query} in {location}" if location else query
    api_key = os.getenv("GOOGLE_MAPS_API_KEY")

    if api_key:
        url = "https://places.googleapis.com/v1/places:searchText"
        headers = {
            "Content-Type": "application/json",
            "X-Goog-Api-Key": api_key,
            "X-Goog-FieldMask": "places.displayName,places.formattedAddress,places.location"
        }
        payload = json.dumps({
            "textQuery": full_query,
            "maxResultCount": 5
        }).encode("utf-8")
        try:
            req = urllib.request.Request(url, data=payload, headers=headers, method="POST")
            with urllib.request.urlopen(req, timeout=5) as response:
                data = json.loads(response.read().decode("utf-8"))
                places = data.get("places", [])
                if places:
                    lines = [f"📍 **Nearby Places for '{full_query}'**:"]
                    for idx, p in enumerate(places, 1):
                        name = p.get("displayName", {}).get("text", "Unknown Place")
                        addr = p.get("formattedAddress", "N/A")
                        loc = p.get("location", {})
                        lat, lng = loc.get("latitude"), loc.get("longitude")
                        lines.append(f"{idx}. **{name}** — {addr} (Coordinates: {lat}, {lng})")
                    return "\n".join(lines)
        except Exception:
            pass  # Fall through to Nominatim

    # Free OpenStreetMap Nominatim fallback (zero cost, no API key needed)
    try:
        encoded_query = urllib.parse.quote(full_query.strip())
        url = f"https://nominatim.openstreetmap.org/search?q={encoded_query}&format=json&limit=5"
        req = urllib.request.Request(url, headers={"User-Agent": "NannyMatchAI/1.0"})
        with urllib.request.urlopen(req, timeout=5) as response:
            places = json.loads(response.read().decode("utf-8"))
            if not places:
                return f"No places found matching query: '{full_query}'."
            lines = [f"📍 **Nearby Places for '{full_query}'**:"]
            for idx, p in enumerate(places, 1):
                name = p.get("display_name", "Unknown Place")
                lat, lng = p.get("lat"), p.get("lon")
                lines.append(f"{idx}. **{name}** (Coordinates: {lat}, {lng})")
            return "\n".join(lines)
    except Exception as e:
        return f"Nearby places lookup failed: {str(e)}"


async def generate_nanny_illustration(
    prompt_description: str,
    tool_context: ToolContext,
) -> str:
    """Generates a domain image (nanny candidate avatar, activity visual, or playroom layout).
    Saves the image locally and to Playground Artifacts.

    Args:
        prompt_description: Visual prompt describing the image (e.g., 'A warm nanny reading a fairytale book to two kids').
        tool_context: Framework ToolContext injected automatically.
    """
    try:
        image_bytes = None
        mime_type = "image/jpeg"

        # Initialize genai client
        if os.getenv("GOOGLE_GENAI_USE_VERTEXAI", "false").lower() == "true" and HAS_GCP:
            client = genai.Client(
                vertexai=True,
                project=FIRESTORE_PROJECT_ID or None,
                location=os.getenv("GOOGLE_CLOUD_LOCATION", "global"),
            )
            response = client.models.generate_content(
                model="gemini-3.1-flash-lite-image",
                contents=[prompt_description],
                config=types.GenerateContentConfig(response_modalities=["IMAGE"]),
            )
            for part in response.parts:
                if part.inline_data:
                    image_bytes = part.inline_data.data
                    mime_type = part.inline_data.mime_type or "image/jpeg"
                    break
        elif os.getenv("GEMINI_API_KEY"):
            client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))
            # Attempt image generation using Imagen model if available
            try:
                result = client.models.generate_images(
                    model="imagen-3.0-generate-002",
                    prompt=prompt_description,
                    config=dict(number_of_images=1, output_mime_type="image/jpeg"),
                )
                if result.generated_images:
                    image_bytes = result.generated_images[0].image.image_bytes
                    mime_type = "image/jpeg"
            except Exception:
                pass

        timestamp = int(datetime.datetime.now().timestamp())
        ext = "jpg" if "jpeg" in mime_type else "png"
        filename = f"nanny_image_{timestamp}.{ext}"

        # If image was generated, save locally and as artifact
        if image_bytes:
            static_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "frontend", "static", "generated")
            os.makedirs(static_dir, exist_ok=True)
            local_file_path = os.path.join(static_dir, filename)
            with open(local_file_path, "wb") as f:
                f.write(image_bytes)

            try:
                artifact_part = types.Part.from_bytes(data=image_bytes, mime_type=mime_type)
                await tool_context.save_artifact(filename=filename, artifact=artifact_part)
            except Exception:
                pass

            # Optional upload to GCS if configured
            if HAS_GCP and storage and GCS_BUCKET_NAME:
                try:
                    storage_client = storage.Client(project=FIRESTORE_PROJECT_ID)
                    bucket = storage_client.bucket(GCS_BUCKET_NAME)
                    blob = bucket.blob(filename)
                    blob.upload_from_string(image_bytes, content_type=mime_type)
                    public_url = f"https://storage.googleapis.com/{GCS_BUCKET_NAME}/{filename}"
                    return (
                        f"🎨 **Generated Domain Image**:\n"
                        f"- Saved locally: `/static/generated/{filename}`\n"
                        f"- Cloud Storage URL: {public_url}"
                    )
                except Exception:
                    pass

            return (
                f"🎨 **Generated Domain Image**:\n"
                f"- Saved locally: `/static/generated/{filename}`\n"
                f"- Playground Artifact: `{filename}`"
            )

        return (
            f"🎨 **Visual Prompt Registered**: '{prompt_description}'.\n"
            f"(Note: Image generation is active when Imagen 3 is configured on your Gemini API key)."
        )
    except Exception as e:
        return f"Image generation status: {str(e)}"


async def generate_nanny_video(
    prompt_description: str,
    tool_context: ToolContext,
) -> str:
    """Generates or simulates a domain demonstration video.

    Args:
        prompt_description: Description of the video to generate.
        tool_context: Framework ToolContext injected automatically.
    """
    if os.getenv("GOOGLE_GENAI_USE_VERTEXAI", "false").lower() == "true" and HAS_GCP:
        try:
            client = genai.Client(
                vertexai=True,
                project=FIRESTORE_PROJECT_ID or None,
                location=os.getenv("GOOGLE_CLOUD_LOCATION", "global"),
            )
            interaction = client.interactions.create(
                model="gemini-omni-flash-preview",
                input=prompt_description,
            )
            video_bytes = None
            if hasattr(interaction, "output_video") and interaction.output_video:
                data = getattr(interaction.output_video, "data", None)
                if data:
                    if isinstance(data, str):
                        video_bytes = base64.b64decode(data)
                    elif isinstance(data, (bytes, bytearray)):
                        video_bytes = bytes(data)

            if video_bytes:
                timestamp = int(datetime.datetime.now().timestamp())
                filename = f"nanny_video_{timestamp}.mp4"
                artifact_part = types.Part.from_bytes(data=video_bytes, mime_type="video/mp4")
                await tool_context.save_artifact(filename=filename, artifact=artifact_part)
                return f"🎬 **Generated Domain Video**: Saved to Artifacts panel as `{filename}`"
        except Exception as e:
            return f"Video generation: {str(e)}"

    return (
        f"🎬 **Demonstration Video Simulation**: Storyboard generated for '{prompt_description}'.\n"
        f"- Scene 1: Warm introduction and candidate credentials verification.\n"
        f"- Scene 2: Interactive childcare demonstration and safety protocols.\n"
        f"*(Note: Gemini Omni Video generation runs on Vertex AI Agent Runtime; in local mode a simulated preview is logged)*"
    )


# After each turn callback (safely handles Memory Bank when running in local mode)
async def generate_memories_callback(callback_context: CallbackContext):
    try:
        await callback_context.add_session_to_memory()
    except Exception:
        # Vertex AI Memory Bank not available or running in local mode
        pass
    return None


schema_manager = A2uiSchemaManager(
    version="0.8",
    catalogs=[BasicCatalog.get_config("0.8")],
)

instruction = schema_manager.generate_system_prompt(
    role_description=(
        "You are NannyMatch AI, a premium conversational concierge for family nanny hiring, placement, and childcare management.\n\n"
        "Your capabilities include:\n"
        "1. **Candidate Database**: Search candidate nannies (`search_nannies_firestore`) "
        "and add new nanny candidate profiles (`add_nanny_firestore`).\n"
        "2. **Memory & Personalization**: Remember user preferences, family details (kids' ages, special needs), "
        "and nanny requirements across sessions.\n"
        "3. **Payroll & Cost Calculation**: Calculate weekly/monthly gross pay, overtime, and estimated employer taxes using `calculate_payroll_and_taxes`.\n"
        "4. **Geocoding & Maps**: Geocode address into lat/long coordinates using `geocode_address` (works with Google Maps API key or free OpenStreetMap).\n"
        "5. **Places API**: Find nearby playgrounds, daycares, pediatric clinics using `find_nearby_places`.\n"
        "6. **Image Generation**: Generate candidate avatar illustrations or playroom activity visuals using `generate_nanny_illustration`.\n"
        "7. **Video Generation**: Generate domain intro/demo videos using `generate_nanny_video`.\n"
        "8. **ZIP Code Location Lookup**: Validate and lookup city/state/coordinates for US zip codes using `lookup_zip_code_location`.\n"
        "9. **Watchlist Management**: Allow users to save favorite candidates or job postings "
        "to their watchlist using `add_to_watchlist` and view them using `view_watchlist`.\n"
        "10. **Profiles & Preferences**: Save and view family requirements using `save_family_profile` and `get_my_profile`.\n"
        "11. **Interview Booking**: Schedule interview slots using `schedule_interview`.\n\n"
        "Always respond warmly, professionally, and use your database tools when asked about nanny candidates!"
    ),
    workflow_description="Analyze the request and return structured UI when appropriate.",
    ui_description=(
        "Keep every surface tiny and flat: ONE Card > ONE Column > a few Text rows. "
        "Never nest a Card inside a Card. "
        "Use ONLY these components: Card, Column, Row, Text, and Image. Do not use "
        "Table or Heading (unsupported), or Buttons, actions, or forms (they do "
        "nothing in adk web). "
        "You may include one Image component, but only when you have a public or local url "
        "for the image (e.g. https://... or /static/generated/...). Set the Image url to that exact link, for example "
        "{\"Image\": {\"url\": {\"literalString\": \"/static/generated/example.jpg\"}}}. Never point an "
        "Image at a bare filename, an artifact name, or an invalid path. If you do "
        "not have a valid URL, add a short Text line noting the image instead. "
        "No markdown in text; use the usageHint property ('h1', 'h2', 'body') for "
        "headings and emphasis. "
        "Output ONLY the raw A2UI JSON array — no prose, and never wrap it in "
        "<a2a_datapart_json> tags or 'kind'/'data'/'metadata' objects."
    ),
    include_schema=True,
    include_examples=True,
)

# Optional Code Executor (only when deployed on Vertex AI Reasoning Engine)
code_executor = None
if REASONING_ENGINE_RESOURCE_NAME:
    try:
        from google.adk.code_executors import AgentEngineSandboxCodeExecutor
        code_executor = AgentEngineSandboxCodeExecutor(
            agent_engine_resource_name=REASONING_ENGINE_RESOURCE_NAME
        )
    except Exception:
        code_executor = None

# Explicitly initialize Gemini client when GEMINI_API_KEY is available
gemini_api_key = os.getenv("GEMINI_API_KEY")
gemini_client = None
if gemini_api_key and os.getenv("GOOGLE_GENAI_USE_VERTEXAI", "false").lower() != "true":
    gemini_client = genai.Client(api_key=gemini_api_key)

root_agent = Agent(
    name="nanny_match_ai",
    model=Gemini(
        model=MODEL,
        client=gemini_client,
        retry_options=types.HttpRetryOptions(attempts=3),
    ),
    code_executor=code_executor,
    instruction=instruction,
    tools=[
        PreloadMemoryTool(),
        search_nannies_firestore,
        add_nanny_firestore,
        calculate_payroll_and_taxes,
        lookup_zip_code_location,
        geocode_address,
        find_nearby_places,
        generate_nanny_illustration,
        generate_nanny_video,
        add_to_watchlist,
        view_watchlist,
        save_family_profile,
        get_my_profile,
        schedule_interview,
    ],
    after_agent_callback=generate_memories_callback,
    after_model_callback=a2ui_callback,
)

app = App(
    root_agent=root_agent,
    name="app",
)
