#!/bin/bash
# Creates a new release by bumping the version, tagging, and pushing.
# GitHub Actions picks up the tag and builds both macOS and Windows releases automatically.
set -e
cd "$(dirname "$0")"

echo "============================================================"
echo " HD Clearance Tracker — Release (macOS)"
echo "============================================================"
echo ""

CURRENT=$(cat version.txt 2>/dev/null || echo "unknown")
echo "Current version: $CURRENT"
echo ""
read -rp "Enter new version (e.g. 1.0.1): " VERSION
if [ -z "$VERSION" ]; then
    echo "ERROR: Version cannot be empty."
    exit 1
fi

# Validate format
if ! echo "$VERSION" | grep -qE '^[0-9]+\.[0-9]+\.[0-9]+$'; then
    echo "ERROR: Version must be in the format MAJOR.MINOR.PATCH (e.g. 1.0.1)"
    exit 1
fi

TAG="v${VERSION}"

# Check the tag doesn't already exist
if git rev-parse "$TAG" >/dev/null 2>&1; then
    echo "ERROR: Tag $TAG already exists. Choose a different version."
    exit 1
fi

echo ""
echo "Updating version.txt → $VERSION"
echo "$VERSION" > version.txt

echo "Committing version bump..."
git add version.txt
git commit -m "Release $TAG"

echo "Tagging $TAG..."
git tag "$TAG"

echo "Pushing to GitHub..."
git push origin main
git push origin "$TAG"

echo ""
echo "============================================================"
echo " Tag $TAG pushed."
echo " GitHub Actions will now:"
echo "   1. Build HD-Tracker.app  (macOS)"
echo "   2. Build HD-Tracker.exe  (Windows)"
echo "   3. Publish a GitHub Release with both zips"
echo ""
echo " Track progress: https://github.com/DOM-LAB-X/claude-HD-checker/actions"
echo "============================================================"
