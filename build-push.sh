#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_FILE="${SCRIPT_DIR}/.env.deploy"
[[ -f "$ENV_FILE" ]] || { echo "Missing ${ENV_FILE}"; exit 1; }
# shellcheck source=.env.deploy
source "$ENV_FILE"

read -rp "Version: " VERSION
[[ -n "$VERSION" ]] || { echo "Version cannot be empty"; exit 1; }
TARVERSION=$(echo "$VERSION" | tr -d '.')

docker build -f Dockerfile.fx --platform linux/amd64 -t iansparkes/fxtrader:"$VERSION" .

docker save -o fx"$TARVERSION".tar iansparkes/fxtrader:"$VERSION"

scp fx"$TARVERSION".tar "${DEPLOY_USER}@${DEPLOY_HOST}:${DEPLOY_PATH}"

ssh "${DEPLOY_USER}@${DEPLOY_HOST}" \
  "docker load -i ${DEPLOY_PATH}/fx${TARVERSION}.tar"
