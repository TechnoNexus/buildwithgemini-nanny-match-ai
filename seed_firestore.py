import subprocess
import google.auth
from google.auth.credentials import AnonymousCredentials
from google.cloud import firestore
import google.oauth2.credentials

PROJECT_ID = "qwiklabs-gcp-02-0b1ea291c4ae"


def get_credentials():
    # Retrieve gcloud access token directly
    token = subprocess.check_output(
        ["gcloud", "auth", "print-access-token"], text=True
    ).strip()
    return google.oauth2.credentials.Credentials(token)


def seed():
    print(f"Initializing Firestore client for project: {PROJECT_ID}...")
    creds = get_credentials()
    db = firestore.Client(project=PROJECT_ID, credentials=creds)
    nannies_ref = db.collection("nannies")

    seeded_nannies = [
        {
            "id": "nanny-01",
            "name": "Elena Rostova",
            "location": "San Francisco",
            "hourly_rate": 28.0,
            "years_experience": 6,
            "cpr_certified": True,
            "bio": "Experienced infant & toddler specialist with a passion for creative early childhood activities.",
            "specialties": ["Infant Care", "Toddler Care", "First Aid", "Multilingual"],
            "availability": "Full-time (Mon-Fri 8am-5pm)",
            "rating": 4.9,
            "updated_at": firestore.SERVER_TIMESTAMP,
        },
        {
            "id": "nanny-02",
            "name": "Marcus Vance",
            "location": "San Francisco",
            "hourly_rate": 35.0,
            "years_experience": 8,
            "cpr_certified": True,
            "bio": "Specialized in active outdoor play, STEM enrichment, and homework support for ages 3-10.",
            "specialties": ["STEM Activities", "Outdoor Play", "CPR/AED", "Driving"],
            "availability": "Part-time (Mon-Thu 1pm-6pm)",
            "rating": 5.0,
            "updated_at": firestore.SERVER_TIMESTAMP,
        },
        {
            "id": "nanny-03",
            "name": "Sophia Chen",
            "location": "New York",
            "hourly_rate": 22.0,
            "years_experience": 3,
            "cpr_certified": False,
            "bio": "Gentle, attentive caregiver with background in music and arts for toddlers and preschoolers.",
            "specialties": ["Arts & Crafts", "Music Lessons", "Meal Prep"],
            "availability": "Flexible (Weekdays & Weekends)",
            "rating": 4.7,
            "updated_at": firestore.SERVER_TIMESTAMP,
        },
        {
            "id": "nanny-04",
            "name": "Hannah Miller",
            "location": "New York",
            "hourly_rate": 30.0,
            "years_experience": 5,
            "cpr_certified": True,
            "bio": "Certified pediatric first-responder nanny focusing on structured routines and newborn care.",
            "specialties": ["Newborn Care", "Pediatric First Aid", "Sleep Training"],
            "availability": "Full-time (Mon-Fri 9am-6pm)",
            "rating": 4.8,
            "updated_at": firestore.SERVER_TIMESTAMP,
        },
    ]

    for nanny in seeded_nannies:
        nannies_ref.document(nanny["id"]).set(nanny)
        print(f"✅ Seeded nanny: {nanny['name']} ({nanny['id']})")


if __name__ == "__main__":
    seed()
