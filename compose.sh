#!/usr/bin/env sh
# Запуск docker compose с env/docker.env.
# Использование: ./compose.sh up --build  |  ./compose.sh -e ./env/docker.env ps

set -eu

ENV_FILE="${ENV_FILE:-./env/docker.env}"
if [ "${1:-}" = "-e" ]; then
  shift
  ENV_FILE="${1:?missing path after -e}"
  shift
fi
exec docker compose --env-file "$ENV_FILE" "$@"
