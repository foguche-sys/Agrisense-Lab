#!/usr/bin/env bash
# Replays the SQL each test ran on SQLite against a fresh PostgreSQL database.
# Usage: PG_TRACE_DIR=/tmp/trace python -m pytest -q tests && tools/pg_replay.sh /tmp/trace "psql -h HOST -p PORT -U USER"
set -euo pipefail
dir=$1; psql=$2; fail=0; n=0
schema=$(python3 -c "from agrisense.db import Database; print(Database('postgresql://x').schema_sql())")
for f in "$dir"/*.sql; do
  n=$((n+1))
  $psql -q -d postgres -c "DROP DATABASE IF EXISTS replay" >/dev/null 2>&1
  $psql -q -d postgres -c "CREATE DATABASE replay" >/dev/null
  echo "$schema" | $psql -q -d replay -v ON_ERROR_STOP=1 >/dev/null
  if ! $psql -q -d replay -v ON_ERROR_STOP=1 -f "$f" >/dev/null 2>/tmp/replay.err; then
    echo "FAIL $(basename "$f"): $(head -3 /tmp/replay.err)"; fail=$((fail+1))
  fi
done
echo "$n traces replayed on PostgreSQL, $fail failed"
[ "$fail" -eq 0 ]
