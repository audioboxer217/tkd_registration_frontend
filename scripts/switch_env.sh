#!/usr/bin/env bash
# This script is used to switch between different environments (e.g., dev or prod).
# Usage: ./switch_env.sh [okgp|okcc] [dev|prod] [--force]
set -e

# Determine repository root (one level up from this script's directory)
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

ENV=""
CLIENT=""
FORCE=0

# Basic argument parsing: client and environment are required, optional --force
if [[ $# -lt 2 || $# -gt 3 ]]; then
  echo "Usage: $0 [okgp|okcc] [dev|prod] [--force]"
  exit 1
fi

CLIENT="$1"
if [[ "$CLIENT" != "okgp" && "$CLIENT" != "okcc" ]]; then
  echo "Unknown client: $CLIENT"
  echo "Usage: $0 [okgp|okcc] [dev|prod] [--force]"
  exit 1
fi

ENV="$2"
if [[ "$ENV" != "dev" && "$ENV" != "prod" ]]; then
  echo "Unknown environment: $ENV"
  echo "Usage: $0 [okgp|okcc] [dev|prod] [--force]"
  exit 1
fi

if [[ $# -eq 3 ]]; then
  if [[ "$3" == "--force" ]]; then
    FORCE=1
  else
    echo "Unknown option: $3"
    echo "Usage: $0 [okgp|okcc] [dev|prod] [--force]"
    exit 1
  fi
fi

TARGET_FILE="${CLIENT}_${ENV}.env"
LINK_PATH="${REPO_ROOT}/.env"
TARGET_PATH="${REPO_ROOT}/${TARGET_FILE}"

# Verify the target environment file exists before linking
if [[ ! -f "$TARGET_PATH" ]]; then
  echo "Error: target environment file '$TARGET_FILE' does not exist in $REPO_ROOT"
  exit 1
fi

# Refuse to overwrite a non-symlink .env unless --force is provided
if [[ -e "$LINK_PATH" && ! -L "$LINK_PATH" && $FORCE -ne 1 ]]; then
  echo "Error: '$LINK_PATH' exists and is not a symlink."
  echo "Refusing to overwrite it without --force."
  exit 1
fi

# Replace the .env link file with the appropriate environment file
rm -f "$LINK_PATH"
ln -s "$TARGET_FILE" "$LINK_PATH"
echo "Switched to $CLIENT $ENV environment"