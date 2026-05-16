#!/usr/bin/env python

import argparse
import io
import os

import boto3
from PIL import Image, ImageDraw, ImageFont, ImageOps

try:
    from scripts._bootstrap import add_repo_root_to_path
except ModuleNotFoundError:  # Allows `python scripts/generate_badges.py`
    from _bootstrap import add_repo_root_to_path

add_repo_root_to_path()

from api import get_eligible_competitors  # noqa: E402
from app import app  # noqa: E402


def get_entries():
    """Query all paid (complete) competitors from the database."""
    return get_eligible_competitors(status="complete")


def get_s3_profile_image(img_filename: str) -> Image.Image | None:
    """Fetch a competitor profile image from the S3 profile-pic bucket.

    Returns a PIL Image (EXIF-corrected) on success, or None when the bucket
    env var is missing or the download fails.
    """
    bucket = os.getenv("PROFILE_PIC_BUCKET")
    if not bucket:
        return None
    try:
        s3 = boto3.client("s3", region_name=os.getenv("AWS_REGION", "us-east-1"))
        buf = io.BytesIO()
        s3.download_fileobj(bucket, img_filename, buf)
        buf.seek(0)
        img = Image.open(buf)
        return ImageOps.exif_transpose(img)
    except Exception as e:
        print(f"Warning: could not download profile image '{img_filename}' from S3: {e}")
        return None


def generate_badge(competitor, output_dir):
    """Generate an ID Badge using competitor DB data."""
    badge = Image.new("RGBA", (400, 600), color="white")

    # Profile image: prefer the competitor's S3-hosted photo; fall back to the
    # local default image in the img/ folder (controlled by BADGE_IMG_FILENAME).
    profile_img = None
    if competitor.img_filename:
        profile_img = get_s3_profile_image(competitor.img_filename)
    if profile_img is None:
        fallback = os.getenv("BADGE_IMG_FILENAME")
        if fallback:
            try:
                profile_img = ImageOps.exif_transpose(Image.open(f"img/{fallback}"))
            except Exception as e:
                print(f"Warning: could not open fallback image 'img/{fallback}': {e}")
    if profile_img is not None:
        profile_img = profile_img.resize((400, 250))
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
