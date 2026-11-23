#!/usr/bin/env bash
# Dağıtımdan önce imajın imzasını doğrular.
# İmza, bu deponun CI iş akışı tarafından, main dalında atılmış olmalıdır.
set -euo pipefail

IMAGE="${1:?Kullanım: verify-image.sh <imaj@sha256:...>}"
: "${COSIGN_IMAGE:?COSIGN_IMAGE tanımlı olmalı}"
: "${GITHUB_REPOSITORY:?GITHUB_REPOSITORY tanımlı olmalı}"

case "$IMAGE" in
  *@sha256:*) ;;
  *) echo "HATA: imaj digest ile verilmeli: $IMAGE" >&2; exit 1 ;;
esac

CFG="$(mktemp -d)"
trap 'rm -rf "$CFG"' EXIT

if [ -n "${GHCR_TOKEN:-}" ]; then
  echo "$GHCR_TOKEN" | DOCKER_CONFIG="$CFG" docker login ghcr.io -u "${GHCR_USER:?GHCR_USER gerekli}" --password-stdin >/dev/null
fi

IDENTITY="https://github.com/${GITHUB_REPOSITORY}/.github/workflows/ci.yml@refs/heads/main"
ISSUER="https://token.actions.githubusercontent.com"

echo "Doğrulanıyor: $IMAGE"
echo "Beklenen imzalayan: $IDENTITY"
docker run --rm -u "$(id -u):$(id -g)" \
  -e HOME=/tmp -e DOCKER_CONFIG=/dockercfg \
  -v "$CFG:/dockercfg:ro" \
  "$COSIGN_IMAGE" verify \
    --certificate-identity "$IDENTITY" \
    --certificate-oidc-issuer "$ISSUER" \
    "$IMAGE" > /dev/null
echo "İmza doğrulandı: $IMAGE"
