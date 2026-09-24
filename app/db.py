"""Local SQLite database manager for NannyMatch AI.

Provides persistent, local, zero-cost storage for nanny candidate profiles,
replacing Google Cloud Firestore when running in local / free mode.
"""

import datetime
import json
import os
import sqlite3
from typing import Any, Dict, List, Optional

# Path to local SQLite database
DB_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")
DB_PATH = os.path.join(DB_DIR, "nannies.db")

# Default seed data with realistic nanny profiles
DEFAULT_NANNIES = [
    {
        "id": "nanny-01",
        "name": "Elena Rostova",
        "location": "San Francisco",
        "hourly_rate": 28.0,
        "years_experience": 6,
        "cpr_certified": 1,
        "bio": "Experienced infant & toddler specialist with a passion for creative early childhood activities.",
        "specialties": json.dumps(["Infant Care", "Toddler Care", "First Aid", "Multilingual"]),
        "availability": "Full-time (Mon-Fri 8am-5pm)",
        "rating": 4.9,
    },
    {
        "id": "nanny-02",
        "name": "Marcus Vance",
        "location": "San Francisco",
        "hourly_rate": 35.0,
        "years_experience": 8,
        "cpr_certified": 1,
        "bio": "Specialized in active outdoor play, STEM enrichment, and homework support for ages 3-10.",
        "specialties": json.dumps(["STEM Activities", "Outdoor Play", "CPR/AED", "Driving"]),
        "availability": "Part-time (Mon-Thu 1pm-6pm)",
        "rating": 5.0,
    },
    {
        "id": "nanny-03",
        "name": "Sophia Chen",
        "location": "New York",
        "hourly_rate": 22.0,
        "years_experience": 3,
        "cpr_certified": 0,
        "bio": "Gentle, attentive caregiver with background in music and arts for toddlers and preschoolers.",
        "specialties": json.dumps(["Arts & Crafts", "Music Lessons", "Meal Prep"]),
        "availability": "Flexible (Weekdays & Weekends)",
        "rating": 4.7,
    },
    {
        "id": "nanny-04",
        "name": "Hannah Miller",
        "location": "New York",
        "hourly_rate": 30.0,
        "years_experience": 5,
        "cpr_certified": 1,
        "bio": "Certified pediatric first-responder nanny focusing on structured routines and newborn care.",
        "specialties": json.dumps(["Newborn Care", "Pediatric First Aid", "Sleep Training"]),
        "availability": "Full-time (Mon-Fri 9am-6pm)",
        "rating": 4.8,
    },
]


def get_db_connection() -> sqlite3.Connection:
    """Creates directory if needed and returns a SQLite connection."""
    os.makedirs(DB_DIR, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db(force_reseed: bool = False) -> None:
    """Initializes the SQLite schema and seeds initial data if table is empty."""
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS nannies (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            location TEXT NOT NULL,
            hourly_rate REAL NOT NULL,
            years_experience INTEGER DEFAULT 0,
            cpr_certified INTEGER DEFAULT 0,
            bio TEXT DEFAULT '',
            specialties TEXT DEFAULT '[]',
            availability TEXT DEFAULT 'Full-time',
            rating REAL DEFAULT 5.0,
            updated_at TEXT
        )
    """)

    cursor.execute("SELECT COUNT(*) FROM nannies")
    count = cursor.fetchone()[0]

    if count == 0 or force_reseed:
        if force_reseed:
            cursor.execute("DELETE FROM nannies")
        now_str = datetime.datetime.now().isoformat()
        for n in DEFAULT_NANNIES:
            cursor.execute(
                """
                INSERT OR REPLACE INTO nannies 
                (id, name, location, hourly_rate, years_experience, cpr_certified, bio, specialties, availability, rating, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    n["id"],
                    n["name"],
                    n["location"],
                    n["hourly_rate"],
                    n["years_experience"],
                    n["cpr_certified"],
                    n["bio"],
                    n["specialties"],
                    n["availability"],
                    n["rating"],
                    now_str,
                ),
            )
        conn.commit()

    conn.close()


def search_nannies(location: str = "", max_rate: float = 0.0, cpr_required: bool = False) -> str:
    """Searches the database for qualified nanny candidates.
    
    Args:
        location: Target city or region (e.g. 'San Francisco', 'New York').
        max_rate: Maximum hourly rate filter in USD.
        cpr_required: Filter for CPR-certified nannies.

    Returns:
        Formatted string listing candidate nanny profiles retrieved from local storage.
    """
    init_db()
    conn = get_db_connection()
    cursor = conn.cursor()

    query = "SELECT * FROM nannies WHERE 1=1"
    params: List[Any] = []

    if location:
        query += " AND LOWER(location) LIKE ?"
        params.append(f"%{location.strip().lower()}%")

    if max_rate > 0:
        query += " AND hourly_rate <= ?"
        params.append(float(max_rate))

    if cpr_required:
        query += " AND cpr_certified = 1"

    query += " ORDER BY rating DESC, hourly_rate ASC"

    cursor.execute(query, params)
    rows = cursor.fetchall()
    conn.close()

    if not rows:
        return f"No nannies currently found matching location='{location}' under ${max_rate}/hr."

    matches = []
    for r in rows:
        cpr_str = "Yes" if r["cpr_certified"] else "No"
        matches.append(
            f"- **{r['name']}** (ID: `{r['id']}`) | ${r['hourly_rate']}/hr | {r['years_experience']} yrs exp | CPR: {cpr_str} | Rating: {r['rating']}/5.0\n"
            f"  *Location*: {r['location']} | *Bio*: {r['bio']} | *Availability*: {r['availability']}"
        )

    return f"Found {len(matches)} nanny candidate(s):\n" + "\n\n".join(matches)


def add_nanny(
    nanny_id: str,
    name: str,
    location: str,
    hourly_rate: float,
    years_experience: int,
    cpr_certified: bool,
    bio: str = "",
    availability: str = "Full-time"
) -> str:
    """Adds or updates a nanny candidate profile in the local database.

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
    init_db()
    conn = get_db_connection()
    cursor = conn.cursor()

    now_str = datetime.datetime.now().isoformat()
    cursor.execute(
        """
        INSERT OR REPLACE INTO nannies 
        (id, name, location, hourly_rate, years_experience, cpr_certified, bio, availability, rating, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, 5.0, ?)
        """,
        (
            nanny_id,
            name,
            location,
            float(hourly_rate),
            int(years_experience),
            1 if cpr_certified else 0,
            bio,
            availability,
            now_str,
        ),
    )
    conn.commit()
    conn.close()

    return f"Successfully saved nanny profile **{name}** (ID: `{nanny_id}`) to database!"


def get_all_nannies() -> List[Dict[str, Any]]:
    """Returns all nannies as a list of dictionaries."""
    init_db()
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM nannies")
    rows = [dict(r) for r in cursor.fetchall()]
    conn.close()
    return rows
