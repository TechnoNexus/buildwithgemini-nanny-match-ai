"""Seed script for local SQLite database (zero-cost local development).

Populates data/nannies.db with candidate nannies for local testing.
"""

from app.db import get_all_nannies, init_db


def main():
    print("Populating local SQLite database (data/nannies.db)...")
    init_db(force_reseed=True)
    nannies = get_all_nannies()
    print(f"Successfully seeded {len(nannies)} candidate nannies:")
    for n in nannies:
        cpr = "CPR Certified" if n["cpr_certified"] else "No CPR"
        print(f"  - [{n['id']}] {n['name']} | ${n['hourly_rate']}/hr | {n['location']} | {cpr} | Rating: {n['rating']}/5.0")
    print("\nLocal database is ready to use!")


if __name__ == "__main__":
    main()
