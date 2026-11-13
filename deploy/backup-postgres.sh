#!/bin/sh
set -eu
umask 077
out_dir="${1:-./backups}"
mkdir -p "$out_dir"
stamp="$(date -u +%Y%m%dT%H%M%SZ)"
target="$out_dir/macrovision-$stamp.dump"
docker compose -f docker-compose.production.yml exec -T db pg_dump -U macrovision -d macrovision -Fc > "$target"
test -s "$target"
sha256sum "$target" > "$target.sha256"
printf '%s\n' "$target"
