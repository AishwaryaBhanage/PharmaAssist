#!/usr/bin/env bash
# Publish the two application images for both CPU architectures to a public registry, so anyone can
# run the stack without building (deploy/prebuilt.override.yml). Run from the repository root
# after `docker login` to the registry (GitHub: `gh auth refresh -s write:packages` then
# `gh auth token | docker login ghcr.io -u <user> --password-stdin`).
#
#   deploy/publish_images.sh ghcr.io/<user> [tag]          # tag defaults to the short git commit; "latest" is also pushed
#
# Builds linux/arm64 and linux/amd64 (the amd64 worker image takes a long time on Apple Silicon: Docling
# models are baked in under emulation; both builds are cached after the first run), pushes per-arch
# tags and assembles one multi-arch manifest per image and tag.
set -euo pipefail
REPO=${1:?registry path, e.g. ghcr.io/aishwaryabhanage}
TAG=${2:-$(git rev-parse --short HEAD)}
SOURCE_LABEL="org.opencontainers.image.source=https://github.com/AishwaryaBhanage/PharmaAssist"
[ -f deploy/aws/Dockerfile ] || { echo "run from the repository root" >&2; exit 1; }

publish() {  # name dockerfile
  local name=$1 file=$2 arch
  for arch in arm64 amd64; do
    echo "== $name linux/$arch" >&2
    docker buildx build --platform "linux/$arch" --provenance=false -f "$file" \
      --label "$SOURCE_LABEL" --label "org.opencontainers.image.revision=$(git rev-parse HEAD)" \
      -t "$REPO/$name:$TAG-$arch" --push . >&2
  done
  for t in "$TAG" latest; do
    docker buildx imagetools create -t "$REPO/$name:$t" "$REPO/$name:$TAG-arm64" "$REPO/$name:$TAG-amd64" >&2
  done
  echo "$REPO/$name:$TAG  (also :latest; arm64 + amd64)"
}

publish pharmassist-v2-web deploy/aws/Dockerfile
publish pharmassist-v2-ingest deploy/aws/Dockerfile.ingest
echo
echo "Run it: docker compose -f deploy/docker-compose.yml -f deploy/prebuilt.override.yml --env-file .env up"
echo "with PHARMASSIST_IMAGES=$REPO PHARMASSIST_TAG=$TAG (or the latest defaults in the override file)."
echo "GitHub packages are private until switched to Public in each package's settings."
