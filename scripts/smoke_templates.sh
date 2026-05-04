#!/usr/bin/env bash
# End-to-end smoke test for hero templates.
#
# Registers two heroes from the canonical bot-sdk-python/examples templates
# (warrior + hunter) as `managed=true`, waits up to ~120s, and asserts they
# leave the sandbox zone. Exits 0 on success, 1 on failure.
#
# Isolation: pre-existing alive managed heroes are paused (managed=false)
# for the duration of the run and restored on exit. Without this, a busy
# tick loop wedges the API under load. The smoke heroes themselves stay
# managed=true (and visible in the world) when the script finishes, so
# you can keep watching them in the frontend.

set -euo pipefail

API="${WORLD_API_URL:-http://localhost:47800}"
EXAMPLES="$(cd "$(dirname "$0")/.." && pwd)/bot-sdk-python/examples"
TS="$(date +%Y%m%d-%H%M%S)"
TMP="$(mktemp -d -t wofa-smoke.XXXXXX)"
SNAPSHOT_FILE="$TMP/paused_heroes.txt"

WARRIOR_NAME="Smoke-Warrior-$TS"
HUNTER_NAME="Smoke-Hunter-$TS"
AUTHOR="@smoke-test"

bold()  { printf '\033[1m%s\033[0m\n' "$*"; }
ok()    { printf '\033[32m✓\033[0m %s\n' "$*"; }
fail()  { printf '\033[31m✗\033[0m %s\n' "$*"; }
info()  { printf '  %s\n' "$*"; }

psql_q () {
  docker compose exec -T postgres psql -U arena -d arena -tAc "$1" 2>/dev/null
}

restore_managed () {
  if [[ -s "$SNAPSHOT_FILE" ]]; then
    local count
    count="$(wc -l < "$SNAPSHOT_FILE" | tr -d ' ')"
    bold "restoring $count paused hero(es) → managed=true + restarting world-api"
    local ids
    ids="$(awk '{printf "'"'"'%s'"'"',",$1}' "$SNAPSHOT_FILE" | sed 's/,$//')"
    psql_q "UPDATE heroes SET managed=true WHERE id IN ($ids);" >/dev/null || true
    docker compose restart world-api >/dev/null 2>&1 || true
  fi
  rm -rf "$TMP"
}
trap restore_managed EXIT

bold "World of Agents — template smoke test ($TS)"

# --- Stack must be up -----------------------------------------------------
if ! docker compose ps postgres 2>/dev/null | grep -q 'Up'; then
  fail "postgres not running — try: make start"
  exit 1
fi
ok "stack is up"

# --- Snapshot + pause other managed heroes --------------------------------
# Anything currently alive AND managed gets parked for the run. We keep
# our smoke heroes out of the snapshot so they don't get accidentally
# restored to a different state at exit.
psql_q "
  SELECT id::text FROM heroes
  WHERE managed=true AND status='alive' AND author <> '$AUTHOR'
" | grep -v '^$' > "$SNAPSHOT_FILE" || true

PAUSED_COUNT="$(wc -l < "$SNAPSHOT_FILE" | tr -d ' ')"
if [[ "$PAUSED_COUNT" -gt 0 ]]; then
  ids="$(awk '{printf "'"'"'%s'"'"',",$1}' "$SNAPSHOT_FILE" | sed 's/,$//')"
  psql_q "UPDATE heroes SET managed=false WHERE id IN ($ids);" >/dev/null
  ok "paused $PAUSED_COUNT existing managed hero(es) (will restore on exit)"
  bold "restarting world-api to drop their managed runners…"
  docker compose restart world-api >/dev/null 2>&1
else
  ok "no other managed heroes to pause"
fi

# --- Wait for world-api /health 200 --------------------------------------
preflight_deadline=$((SECONDS + 90))
preflight_ok=0
while [[ $SECONDS -lt $preflight_deadline ]]; do
  if [[ "$(curl -s --max-time 8 -o /dev/null -w '%{http_code}' "$API/health" 2>/dev/null)" == "200" ]]; then
    preflight_ok=1
    break
  fi
  sleep 3
done
if [[ $preflight_ok -ne 1 ]]; then
  fail "world-api not healthy at $API/health within 90s"
  info "check logs: docker compose logs --tail=50 world-api"
  exit 1
fi
ok "world-api is healthy"

# --- Patch templates with unique name + non-placeholder author -----------
patch_template () {
  local src="$1" dst="$2" new_name="$3"
  sed -e "s/^  name: \"[^\"]*\"$/  name: \"$new_name\"/" \
      -e "s/^  author: \"[^\"]*\"$/  author: \"$AUTHOR\"/" \
      "$src" > "$dst"
}
patch_template "$EXAMPLES/minimal_hero.yaml" "$TMP/warrior.yaml" "$WARRIOR_NAME"
patch_template "$EXAMPLES/lyra_hunter.yaml"  "$TMP/hunter.yaml"  "$HUNTER_NAME"
ok "patched templates → $WARRIOR_NAME, $HUNTER_NAME"

# --- Register both as managed --------------------------------------------
register () {
  local name="$1" file="$2" attempt body code
  for attempt in 1 2 3; do
    body="$(curl -s --max-time 30 -X POST "$API/heroes/register?managed=true" \
              -F "manifest=@$file;type=application/x-yaml" \
              -w $'\n%{http_code}' 2>/dev/null || true)"
    code="${body##*$'\n'}"
    body="${body%$'\n'*}"
    if [[ "$code" == "201" ]]; then
      python3 -c "import json,sys; print(json.loads(sys.argv[1])['id'])" "$body"
      return 0
    fi
    sleep 4
  done
  fail "register failed for $name after 3 attempts (last HTTP $code): $body"
  exit 1
}

WARRIOR_ID="$(register "$WARRIOR_NAME" "$TMP/warrior.yaml")"
ok "registered $WARRIOR_NAME → $WARRIOR_ID"
HUNTER_ID="$(register "$HUNTER_NAME"  "$TMP/hunter.yaml")"
ok "registered $HUNTER_NAME → $HUNTER_ID"

# --- Poll for sandbox exit (DB direct) -----------------------------------
DEADLINE=$((SECONDS + 120))
hero_zone () { psql_q "SELECT zone FROM heroes WHERE id='$1';" | tr -d ' \n'; }

bold "waiting for both to leave the sandbox (≤120s)…"
WARRIOR_ZONE=""; HUNTER_ZONE=""
while [[ $SECONDS -lt $DEADLINE ]]; do
  WARRIOR_ZONE="$(hero_zone "$WARRIOR_ID")"
  HUNTER_ZONE="$(hero_zone "$HUNTER_ID")"
  printf '  %3ds   warrior=%-15s hunter=%-15s\n' \
    "$SECONDS" "${WARRIOR_ZONE:-?}" "${HUNTER_ZONE:-?}"
  if [[ -n "$WARRIOR_ZONE" && "$WARRIOR_ZONE" != "sandbox" \
        && -n "$HUNTER_ZONE" && "$HUNTER_ZONE" != "sandbox" ]]; then
    break
  fi
  sleep 4
done

# --- Final assertions ----------------------------------------------------
exit_code=0
final_state () {
  psql_q "SELECT zone || ' (' || pos_x || ',' || pos_y || ') hp=' || hp FROM heroes WHERE id='$1';" \
    | tr -s ' ' | sed 's/^ *//;s/ *$//'
}
event_count () {
  psql_q "SELECT COUNT(*) FROM events WHERE hero_id='$1' AND kind='action.resolved';"
}

bold "final state"
W_FINAL="$(final_state "$WARRIOR_ID")"
H_FINAL="$(final_state "$HUNTER_ID")"
W_EVENTS="$(event_count "$WARRIOR_ID")"
H_EVENTS="$(event_count "$HUNTER_ID")"
info "warrior $WARRIOR_NAME → $W_FINAL  ($W_EVENTS resolved actions)"
info "hunter  $HUNTER_NAME → $H_FINAL  ($H_EVENTS resolved actions)"

if [[ -z "$WARRIOR_ZONE" || "$WARRIOR_ZONE" == "sandbox" ]]; then
  fail "warrior never left sandbox — leave_sandbox reflex didn't fire"
  exit_code=1
else
  ok "warrior exited sandbox → $WARRIOR_ZONE"
fi
if [[ -z "$HUNTER_ZONE" || "$HUNTER_ZONE" == "sandbox" ]]; then
  fail "hunter never left sandbox — leave_sandbox reflex didn't fire"
  exit_code=1
else
  ok "hunter exited sandbox → $HUNTER_ZONE"
fi

bold "spectate URLs"
info "$API/heroes/$WARRIOR_ID"
info "$API/heroes/$HUNTER_ID"
info "frontend: ${API/47800/47900}/heroes/$WARRIOR_ID"
info "frontend: ${API/47800/47900}/heroes/$HUNTER_ID"

exit "$exit_code"
