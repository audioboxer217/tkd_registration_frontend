#!/usr/bin/env python3
"""
Fuzzy match competitor coach names to coach IDs using difflib.

This script finds competitors whose coach_id is NULL and attempts to match
their original coach name (stored in registrations table) to a coach in the
coaches table using fuzzy string matching.
"""

import difflib
import os

import psycopg
from psycopg.rows import dict_row


def get_db_connection():
    """Create a database connection."""
    db_url = os.getenv("DATABASE_URL")
    if not db_url:
        raise ValueError("DATABASE_URL environment variable not set")
    return psycopg.connect(db_url, row_factory=dict_row)


def fuzzy_match_coaches():
    """Match competitor coaches to coach table entries using fuzzy matching."""
    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        # Get all competitors with NULL coach_id and their original coach names from registrations
        query = """
        SELECT
            c.id as competitor_id,
            c.school_id,
            r.coach as original_coach_name
        FROM competitors c
        JOIN registrations r ON
            r.full_name = c.full_name AND
            r.email = c.email AND
            r.reg_type = 'competitor'
        WHERE c.coach_id IS NULL AND r.coach IS NOT NULL AND r.coach != ''
        ORDER BY c.school_id, c.id;
        """
        cursor.execute(query)
        competitors_to_match = cursor.fetchall()

        print(f"Found {len(competitors_to_match)} competitors needing coach matching")

        matched_count = 0
        unmatched_count = 0
        unmatched_details = []

        for comp in competitors_to_match:
            competitor_id = comp["competitor_id"]
            school_id = comp["school_id"]
            coach_name = comp["original_coach_name"].strip()

            # Get all coaches in this school
            coach_query = "SELECT id, full_name FROM coaches WHERE school_id = %s ORDER BY full_name;"
            cursor.execute(coach_query, (school_id,))
            coaches = cursor.fetchall()

            if not coaches:
                unmatched_count += 1
                unmatched_details.append(f"  Competitor {competitor_id}: No coaches in school {school_id}")
                continue

            # Find best match using difflib
            coach_names = [c["full_name"] for c in coaches]
            matches = difflib.get_close_matches(
                coach_name, coach_names, n=1, cutoff=0.85
            )

            if matches:
                matched_name = matches[0]
                matched_coach = next(c for c in coaches if c["full_name"] == matched_name)
                coach_id = matched_coach["id"]

                # Update competitor with matched coach_id
                update_query = "UPDATE competitors SET coach_id = %s WHERE id = %s;"
                cursor.execute(update_query, (coach_id, competitor_id))
                matched_count += 1
                print(f"  ✓ Competitor {competitor_id}: '{coach_name}' → Coach {coach_id} ('{matched_name}')")
            else:
                unmatched_count += 1
                unmatched_details.append(
                    f"  Competitor {competitor_id}: '{coach_name}' - No close match found in school {school_id}"
                )

        conn.commit()

        # Print summary
        print(f"\n{'='*60}")
        print("FUZZY MATCHING RESULTS")
        print(f"{'='*60}")
        print(f"Matched: {matched_count}")
        print(f"Unmatched: {unmatched_count}")

        if unmatched_details:
            print("\nUNMATCHED COACHES (confidence < 85%):")
            for detail in unmatched_details:
                print(detail)

        print(f"{'='*60}\n")

    finally:
        cursor.close()
        conn.close()


if __name__ == "__main__":
    fuzzy_match_coaches()
    print("Fuzzy matching complete!")
