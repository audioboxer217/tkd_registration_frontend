#!/usr/bin/env python

import argparse
import os

from PIL import Image, ImageDraw, ImageFont, ImageOps

try:
    from scripts._bootstrap import add_repo_root_to_path
except ModuleNotFoundError:  # Allows `python scripts/generate_badges.py`
    from _bootstrap import add_repo_root_to_path

add_repo_root_to_path()

from app import app  # noqa: E402
from models import Competitor  # noqa: E402


def get_entries():
    """Query all competitors from the database."""
    return Competitor.query.all()


def generate_badge(competitor, output_dir):
    """Generate an ID Badge using competitor DB data."""
    badge = Image.new("RGBA", (400, 600), color="white")

    # Opening and resizing the profile image
    img_filename = competitor.img_filename or os.getenv("BADGE_IMG_FILENAME")
    if img_filename:
        profile_img = Image.open(f"img/{img_filename}")
        profile_img = profile_img.resize((400, 250))
        profile_img = ImageOps.exif_transpose(profile_img)
        badge.paste(profile_img, (10, 20))

    # Add text items
    font_name = ImageFont.truetype("img/OpenSans-Regular.ttf", size=30)
    font = ImageFont.truetype("img/OpenSans-Regular.ttf", size=24)
    badge_draw = ImageDraw.Draw(badge)

    # Name
    badge_draw.text((200, 275), competitor.full_name, font=font_name, fill="black", anchor="mt")
    # School
    school_name = competitor.school.name if competitor.school else "Unknown School"
    badge_draw.text((200, 310), school_name, font=font, fill="black", anchor="ma")
    # Gender
    badge_draw.text((50, 350), f"Sex: {competitor.gender}", font=font, fill="black")
    # Age
    badge_draw.text((50, 380), f"Age: {competitor.age}", font=font, fill="black")
    # Belt
    belt_rank = competitor.belt_rank or ""
    if "black" in belt_rank.lower():
        belt_rank = "black"
    badge_draw.text((235, 350), f"Belt: {belt_rank}", font=font, fill="black")
    # Weight
    weight = float(competitor.weight) if competitor.weight is not None else 0
    badge_draw.text((200, 380), f"Weight: {weight:.1f} lbs", font=font, fill="black")
    # Divider
    badge_draw.line([(0, 420), (600, 420)], fill="black")
    # Events
    badge_draw.text((200, 430), "Events", font=font, fill="black", anchor="mt")
    events = competitor.events.split(",") if competitor.events else []
    left_y = 450
    left_x = 25
    right_y = 450
    right_x = 175
    for event in events:
        event = event.strip()
        if event in [
            "sparring",
            "sparring-gr",
            "sparring-wc",
            "breaking",
            "poomsae",
            "freestyle poomsae",
            "little_dragon",
            "little_tiger",
        ]:
            x = left_x
            y = left_y
            left_y += 30
        elif event in ["world-class poomsae", "pair poomsae", "team poomsae", "family poomsae"]:
            x = right_x
            y = right_y
            right_y += 30
        else:
            x = left_x
            y = left_y
            left_y += 30

        badge_draw.text((x, y), f"• {event}", font=font, fill="black")

    try:
        # Resize and convert to final size/type
        badge = badge.resize((250, 400), resample=Image.Resampling.LANCZOS)
        badge = badge.convert("RGB")
        badge_filename = f"{competitor.id}_badge.jpg"

        # Save the image
        badge_path = os.path.join(output_dir, badge_filename)
        badge.save(badge_path)

        ret_msg = f"Badge '{badge_filename}' generated"
    except Exception as e:
        ret_msg = f"{e = }"

    print(ret_msg)
    return ret_msg


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate badges for competitors.")
    parser.add_argument(
        "--output-dir",
        default="output/badges",
        help="Directory for generated badge files. Defaults to output/badges/.",
    )
    return parser.parse_args()


def main():
    args = parse_args()

    os.makedirs(args.output_dir, exist_ok=True)

    with app.app_context():
        entries = get_entries()
        for competitor in entries:
            print(f"Generating badge for {competitor.full_name}")
            generate_badge(competitor, args.output_dir)


if __name__ == "__main__":
    main()
