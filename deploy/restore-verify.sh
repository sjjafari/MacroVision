#!/bin/sh
set -eu
dump="${1:?usage: restore-verify.sh <backup.dump>}"
test -s "$dump"
docker compose -f docker-compose.production.yml exec -T db dropdb -U macrovision --if-exists macrovision_restore_verify
docker compose -f docker-compose.production.yml exec -T db createdb -U macrovision macrovision_restore_verify
cat "$dump" | docker compose -f docker-compose.production.yml exec -T db pg_restore -U macrovision -d macrovision_restore_verify --no-owner --no-privileges
docker compose -f docker-compose.production.yml exec -T db psql -U macrovision -d macrovision_restore_verify -v ON_ERROR_STOP=1 -c "SELECT COUNT(*) AS alembic_rows FROM alembic_version;"
docker compose -f docker-compose.production.yml exec -T db dropdb -U macrovision macrovision_restore_verify
