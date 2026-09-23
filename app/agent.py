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

from a2ui.basic_catalog.provider import BasicCatalog
from a2ui.schema.manager import A2uiSchemaManager
from google import genai
from google.adk.agents import Agent
from google.adk.agents.callback_context import CallbackContext
from google.adk.apps import App
from google.adk.code_executors import AgentEngineSandboxCodeExecutor
from google.adk.models import Gemini
from google.adk.tools import ToolContext
from google.adk.tools.preload_memory_tool import PreloadMemoryTool
from google.cloud import firestore, storage
from google.genai import types

from .a2ui_utils import a2ui_callback

MODEL = "gemini-3.8-flash"
FIRESTORE_PROJECT_ID = "qwiklabs-gcp-02-0b1ea291c4ae"
REASONING_ENGINE_RESOURCE_NAME = "projects/qwiklabs-gcp-02-0b1ea291c4ae/locations/us-east1/reasoningEngines/5204536091054440448"


def get_firestore_db() -> firestore.Client:
    """Returns a Firestore client initialized with hardcoded project ID."""
    return firestore.Client(project=FIRESTORE_PROJECT_ID)


def search_nannies_firestore(location: str = "", max_rate: float = 0.0, cpr_required: bool = False) -> str:
    """Searches the Firestore database for qualified nanny candidates.

    Args:
        location: Target city or region (e.g. 'San Francisco', 'New York').
        max_rate: Maximum hourly rate filter in USD.
        cpr_required: Filter for CPR-certified nannies.

    Returns:
        Formatted string listing candidate nanny profiles retrieved from Firestore.
    """
    db = get_firestore_db()
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
    """Adds or updates a nanny candidate profile in the Firestore database.

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
    db = get_firestore_db()
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
    """Converts a street address or location name into geographic coordinates (lat/lng) using Google Geocoding API.

    Args:
        address: Full street address or location (e.g. '1600 Amphitheatre Pkwy, Mountain View, CA').
    """
    api_key = os.getenv("GOOGLE_MAPS_API_KEY")
    if not api_key:
        return "Error: GOOGLE_MAPS_API_KEY environment variable is not set."

    encoded_address = urllib.parse.quote(address.strip())
    url = f"https://maps.googleapis.com/maps/api/geocode/json?address={encoded_address}&key={api_key}"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "NannyMatchAI/1.0"})
        with urllib.request.urlopen(req, timeout=5) as response:
            data = json.loads(response.read().decode("utf-8"))
            results = data.get("results", [])
            if not results:
                return f"No geocoding results found for address: '{address}'."
            first = results[0]
            fmt_addr = first.get("formatted_address", address)
            location = first.get("geometry", {}).get("location", {})
            lat, lng = location.get("lat"), location.get("lng")
            return f"🗺️ **Geocoded Location**: {fmt_addr} | Latitude: {lat}, Longitude: {lng}"
    except Exception as e:
        return f"Geocoding API request failed: {str(e)}"


def find_nearby_places(query: str, location: str = "") -> str:
    """Finds nearby places (e.g., playgrounds, daycare centers, pediatricians, schools) using Places API (New).

    Args:
        query: Place type or search phrase (e.g. 'playground', 'daycare center', 'pediatric clinic').
        location: Optional location context or city (e.g. 'San Francisco, CA').
    """
    api_key = os.getenv("GOOGLE_MAPS_API_KEY")
    if not api_key:
        return "Error: GOOGLE_MAPS_API_KEY environment variable is not set."

    full_query = f"{query} in {location}" if location else query
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
            if not places:
                return f"No places found matching query: '{full_query}'."
            
            lines = [f"📍 **Nearby Places for '{full_query}'**:"]
            for idx, p in enumerate(places, 1):
                name = p.get("displayName", {}).get("text", "Unknown Place")
                addr = p.get("formattedAddress", "N/A")
                loc = p.get("location", {})
                lat, lng = loc.get("latitude"), loc.get("longitude")
                lines.append(f"{idx}. **{name}** — {addr} (Coordinates: {lat}, {lng})")
            return "\n".join(lines)
    except Exception as e:
        return f"Places API (New) request failed: {str(e)}"


async def generate_nanny_illustration(
    prompt_description: str,
    tool_context: ToolContext,
) -> str:
    """Generates a domain image (nanny candidate avatar, activity visual, or playroom layout) using gemini-3.1-flash-lite-image in the global region.
    Saves the image to Playground Artifacts and uploads it to public Cloud Storage.

    Args:
        prompt_description: Visual prompt describing the image (e.g., 'A warm nanny reading a fairytale book to two kids').
        tool_context: Framework ToolContext injected automatically.
    """
    try:
        client = genai.Client(
            vertexai=True,
            project="qwiklabs-gcp-02-0b1ea291c4ae",
            location="global",
        )
        response = client.models.generate_content(
            model="gemini-3.1-flash-lite-image",
            contents=[prompt_description],
            config=types.GenerateContentConfig(
                response_modalities=["IMAGE"],
            ),
        )

        image_bytes = None
        mime_type = "image/jpeg"
        for part in response.parts:
            if part.inline_data:
                image_bytes = part.inline_data.data
                mime_type = part.inline_data.mime_type or "image/jpeg"
                break

        if not image_bytes:
            return "Error: No image generated from model response."

        timestamp = int(datetime.datetime.now().timestamp())
        ext = "jpg" if "jpeg" in mime_type else "png"
        filename = f"nanny_image_{timestamp}.{ext}"

        # 1. Save artifact so it shows up in Playground Artifacts panel
        artifact_part = types.Part.from_bytes(data=image_bytes, mime_type=mime_type)
        await tool_context.save_artifact(filename=filename, artifact=artifact_part)

        # 2. Upload in-memory image bytes to public Cloud Storage bucket
        bucket_name = "nanny-match-ai-assets-qwiklabs-gcp-02-0b1ea291c4ae"
        storage_client = storage.Client(project="qwiklabs-gcp-02-0b1ea291c4ae")
        bucket = storage_client.bucket(bucket_name)
        blob = bucket.blob(filename)
        blob.upload_from_string(image_bytes, content_type=mime_type)

        public_url = f"https://storage.googleapis.com/{bucket_name}/{filename}"
        return (
            f"🎨 **Generated Domain Image**:\n"
            f"- Saved to Playground Artifacts panel as `{filename}`\n"
            f"- Uploaded to Public Cloud Storage: {public_url}"
        )
    except Exception as e:
        return f"Error generating image: {str(e)}"


async def generate_nanny_video(
    prompt_description: str,
    tool_context: ToolContext,
) -> str:
    """Generates a short domain video (e.g. nanny introduction video, CPR safety demonstration, or family activity routine) using Google's Omni model (gemini-omni-flash-preview) in the global region.
    Saves the video to Playground Artifacts and uploads it to public Cloud Storage.

    Args:
        prompt_description: Description of the video to generate (e.g., 'A cheerful nanny demonstrating CPR techniques on a toddler dummy').
        tool_context: Framework ToolContext injected automatically.
    """
    try:
        client = genai.Client(
            vertexai=True,
            project="qwiklabs-gcp-02-0b1ea291c4ae",
            location="global",
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

        if not video_bytes:
            return "Error: No video bytes returned from gemini-omni-flash-preview model."

        timestamp = int(datetime.datetime.now().timestamp())
        filename = f"nanny_video_{timestamp}.mp4"

        # 1. Save artifact so it shows up in Playground Artifacts panel
        artifact_part = types.Part.from_bytes(data=video_bytes, mime_type="video/mp4")
        await tool_context.save_artifact(filename=filename, artifact=artifact_part)

        # 2. Upload in-memory video bytes to public Cloud Storage bucket
        bucket_name = "nanny-match-ai-assets-qwiklabs-gcp-02-0b1ea291c4ae"
        storage_client = storage.Client(project="qwiklabs-gcp-02-0b1ea291c4ae")
        bucket = storage_client.bucket(bucket_name)
        blob = bucket.blob(filename)
        blob.upload_from_string(video_bytes, content_type="video/mp4")

        public_url = f"https://storage.googleapis.com/{bucket_name}/{filename}"
        return (
            f"🎬 **Generated Domain Video**:\n"
            f"- Saved to Playground Artifacts panel as `{filename}`\n"
            f"- Uploaded to Public Cloud Storage: {public_url}"
        )
    except Exception as e:
        return f"Error generating video: {str(e)}"


# WRITE: after each turn, send the session to Memory Bank for extraction.
async def generate_memories_callback(callback_context: CallbackContext):
    await callback_context.add_session_to_memory()
    return None


schema_manager = A2uiSchemaManager(
    version="0.8",
    catalogs=[BasicCatalog.get_config("0.8")],
)

instruction = schema_manager.generate_system_prompt(
    role_description=(
        "You are NannyMatch AI, a premium conversational concierge for family nanny hiring, placement, and childcare management.\n\n"
        "Your capabilities include:\n"
        "1. **Firestore Database**: Search candidate nannies in Google Cloud Firestore (`search_nannies_firestore`) "
        "and add new nanny candidate profiles (`add_nanny_firestore`).\n"
        "2. **Memory & Personalization**: Remember user preferences, family details (kids' ages, special needs), "
        "and nanny requirements across sessions via Memory Bank.\n"
        "3. **Payroll & Cost Calculation**: Calculate weekly/monthly gross pay, overtime, and estimated employer taxes using `calculate_payroll_and_taxes`.\n"
        "4. **Geocoding & Maps**: Geocode address into lat/long coordinates using `geocode_address` (requires GOOGLE_MAPS_API_KEY).\n"
        "5. **Places API (New)**: Find nearby playgrounds, daycares, pediatric clinics using `find_nearby_places` (requires GOOGLE_MAPS_API_KEY).\n"
        "6. **Image Generation**: Generate candidate avatar illustrations or playroom activity visuals using `generate_nanny_illustration` "
        "(uses `gemini-3.1-flash-lite-image` in `global` region, saves artifact, and uploads to GCS).\n"
        "7. **Video Generation**: Generate domain intro/demo videos using `generate_nanny_video` "
        "(uses `gemini-omni-flash-preview` in `global` region, saves artifact, and uploads to GCS).\n"
        "8. **ZIP Code Location Lookup**: Validate and lookup city/state/coordinates for US zip codes using `lookup_zip_code_location`.\n"
        "9. **Watchlist Management**: Allow users to save favorite candidates or job postings "
        "to their watchlist using `add_to_watchlist` and view them using `view_watchlist`.\n"
        "10. **Profiles & Preferences**: Save and view family requirements using `save_family_profile` and `get_my_profile`.\n"
        "11. **Interview Booking**: Schedule interview slots using `schedule_interview`.\n\n"
        "Always respond warmly, professionally, and use your Firestore database tools when asked about nanny candidates!"
    ),
    workflow_description="Analyze the request and return structured UI when appropriate.",
    ui_description=(
        "Keep every surface tiny and flat: ONE Card > ONE Column > a few Text rows. "
        "Never nest a Card inside a Card. "
        "Use ONLY these components: Card, Column, Row, Text, and Image. Do not use "
        "Table or Heading (unsupported), or Buttons, actions, or forms (they do "
        "nothing in adk web). "
        "You may include one Image component, but only when you have a public https "
        "URL for the image (for example the URL an image tool returns after uploading "
        "to a public bucket). Set the Image url to that exact https link, for example "
        "{\"Image\": {\"url\": {\"literalString\": \"https://...\"}}}. Never point an "
        "Image at a bare filename, an artifact name, or a non-http(s) path. If you do "
        "not have a public URL, add a short Text line noting the image instead. "
        "No markdown in text; use the usageHint property ('h1', 'h2', 'body') for "
        "headings and emphasis. "
        "Output ONLY the raw A2UI JSON array — no prose, and never wrap it in "
        "<a2a_datapart_json> tags or 'kind'/'data'/'metadata' objects."
    ),
    include_schema=True,
    include_examples=True,
)


root_agent = Agent(
    name="nanny_match_ai",
    model=Gemini(
        model=MODEL,
        retry_options=types.HttpRetryOptions(attempts=3),
    ),
    code_executor=AgentEngineSandboxCodeExecutor(
        agent_engine_resource_name=REASONING_ENGINE_RESOURCE_NAME
    ),
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
