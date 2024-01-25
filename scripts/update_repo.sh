#!/bin/bash

TARGET_DIR="$1"
EMAIL="$2"
USERNAME="$3"
JSON_DATA_PATH="$4"
HF_USERNAME="$5"
HF_TOKEN="$6"
HF_REPO="$7"

# Change working directory to the target directory
cd "$TARGET_DIR" || exit 1

# Set user email and username
git config --global user.email "$EMAIL"
git config --global user.name "$USERNAME"

# Commit all changes in the target directory
git add .
git commit -m "Update JSON files in $JSON_DATA_PATH"
git push "https://${HF_USERNAME}:${HF_TOKEN}@huggingface.co/spaces/${HF_USERNAME}/${HF_REPO}" main
