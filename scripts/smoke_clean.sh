#!/usr/bin/env bash
# Delete every hero registered by the smoke test (author='@smoke-test')
# along with their dependent rows. Safe to run any time — no-op when
# there are no smoke heroes.

set -euo pipefail

bold() { printf '\033[1m%s\033[0m\n' "$*"; }
ok()   { printf '\033[32m✓\033[0m %s\n' "$*"; }
fail() { printf '\033[31m✗\033[0m %s\n' "$*"; }
info() { printf '  %s\n' "$*"; }

psql_q () {
  docker compose exec -T postgres psql -U arena -d arena -tAc "$1" 2>/dev/null
}

if ! docker compose ps postgres 2>/dev/null | grep -q 'Up'; then
  fail "postgres not running — try: make start"
  exit 1
fi

COUNT_BEFORE="$(psql_q "SELECT COUNT(*) FROM heroes WHERE author='@smoke-test';" | tr -d ' \n')"
if [[ "${COUNT_BEFORE:-0}" == "0" ]]; then
  ok "nothing to clean (no heroes with author='@smoke-test')"
  exit 0
fi

bold "deleting $COUNT_BEFORE smoke hero(es) and dependent rows…"

# All tables that reference heroes.id by uuid column. For tables that
# treat the hero as a primary subject (events, journal_entries, quests,
# items, etc.) we delete the row. For optional ownership pointers
# (buildings, npcs.tamed_by) we null the column so the row survives.
psql_q "
BEGIN;
WITH s AS (SELECT id FROM heroes WHERE author='@smoke-test')
DELETE FROM events             WHERE hero_id        IN (SELECT id FROM s);
WITH s AS (SELECT id FROM heroes WHERE author='@smoke-test')
DELETE FROM journal_entries    WHERE hero_id        IN (SELECT id FROM s);
WITH s AS (SELECT id FROM heroes WHERE author='@smoke-test')
DELETE FROM quests             WHERE hero_id        IN (SELECT id FROM s);
WITH s AS (SELECT id FROM heroes WHERE author='@smoke-test')
DELETE FROM hero_tools         WHERE hero_id        IN (SELECT id FROM s);
WITH s AS (SELECT id FROM heroes WHERE author='@smoke-test')
DELETE FROM tournament_entries WHERE hero_id        IN (SELECT id FROM s);
WITH s AS (SELECT id FROM heroes WHERE author='@smoke-test')
DELETE FROM statuses           WHERE hero_id        IN (SELECT id FROM s)
                                  OR source_hero_id IN (SELECT id FROM s);
WITH s AS (SELECT id FROM heroes WHERE author='@smoke-test')
DELETE FROM contracts          WHERE poster_hero_id     IN (SELECT id FROM s)
                                  OR claimed_by_hero_id IN (SELECT id FROM s)
                                  OR target_hero_id     IN (SELECT id FROM s);
WITH s AS (SELECT id FROM heroes WHERE author='@smoke-test')
DELETE FROM trade_offers       WHERE from_hero_id IN (SELECT id FROM s)
                                  OR to_hero_id   IN (SELECT id FROM s);
WITH s AS (SELECT id FROM heroes WHERE author='@smoke-test')
DELETE FROM tool_copies        WHERE copied_by_hero IN (SELECT id FROM s);
WITH s AS (SELECT id FROM heroes WHERE author='@smoke-test')
DELETE FROM items              WHERE owner_hero_id        IN (SELECT id FROM s)
                                  OR stash_owner_hero_id  IN (SELECT id FROM s);
WITH s AS (SELECT id FROM heroes WHERE author='@smoke-test')
UPDATE buildings SET owner_hero_id=NULL WHERE owner_hero_id IN (SELECT id FROM s);
WITH s AS (SELECT id FROM heroes WHERE author='@smoke-test')
UPDATE npcs SET tamed_by_hero_id=NULL WHERE tamed_by_hero_id IN (SELECT id FROM s);
DELETE FROM heroes WHERE author='@smoke-test';
COMMIT;
" >/dev/null

COUNT_AFTER="$(psql_q "SELECT COUNT(*) FROM heroes WHERE author='@smoke-test';" | tr -d ' \n')"
if [[ "${COUNT_AFTER:-0}" != "0" ]]; then
  fail "$COUNT_AFTER smoke hero(es) still present after cleanup"
  exit 1
fi

# The smoke runner doesn't itself spin up managed runners that survive
# this delete; the registry will skip missing ids on next tick. Restart
# world-api so any in-flight references drop cleanly.
info "restarting world-api so any in-memory references drop"
docker compose restart world-api >/dev/null 2>&1 || true

ok "deleted $COUNT_BEFORE smoke hero(es)"
