#!/bin/bash
# GNU Health container entrypoint
# 1. Symlink GNU Health modules into trytond's modules directory
# 2. Wait for PostgreSQL
# 3. Initialise the database on first run
# 4. Start trytond
set -e

MODULES_SRC="${GNUHEALTH_MODULES_DIR:-/modules}"
DB_NAME="${GNUHEALTH_DB_NAME:-gnuhealth}"
DB_HOST="${GNUHEALTH_DB_HOST:-gnuhealth-db}"
DB_PORT="${GNUHEALTH_DB_PORT:-5432}"
DB_USER="${GNUHEALTH_DB_USER:-gnuhealth}"
ADMIN_PASS="${GNUHEALTH_ADMIN_PASSWORD:-change_me_before_deploy}"

# ── 1. Link GNU Health modules into trytond ───────────────────────────────────
TRYTOND_MODULES=$(python -c "import trytond.modules, os; print(os.path.dirname(trytond.modules.__file__))")
echo "[gnuhealth] trytond modules dir: $TRYTOND_MODULES"

if [ -d "$MODULES_SRC" ]; then
    echo "[gnuhealth] Linking modules from $MODULES_SRC ..."
    linked=0
    skipped=0
    for dir in "$MODULES_SRC"/*/; do
        name=$(basename "$dir")
        # Only link real Tryton modules — they must have a tryton.cfg
        if [ ! -f "$dir/tryton.cfg" ]; then
            skipped=$((skipped+1))
            continue
        fi
        target="$TRYTOND_MODULES/$name"
        if [ ! -e "$target" ]; then
            ln -s "$dir" "$target"
            echo "  -> linked $name"
            linked=$((linked+1))
        fi
    done
    echo "[gnuhealth] Done: $linked linked, $skipped skipped (no tryton.cfg)."
else
    echo "[gnuhealth] WARNING: $MODULES_SRC not found — starting without GNU Health modules."
fi

# ── 2. Wait for PostgreSQL ────────────────────────────────────────────────────
echo "[gnuhealth] Waiting for PostgreSQL at $DB_HOST:$DB_PORT ..."
until pg_isready -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" -q; do
    sleep 2
done
echo "[gnuhealth] PostgreSQL ready."

# ── 3. Initialise / update database ──────────────────────────────────────────
INIT_FLAG="/var/lib/trytond/.db_initialised"

if [ ! -f "$INIT_FLAG" ]; then
    echo "[gnuhealth] First-run: initialising database $DB_NAME ..."
    trytond-admin \
        -c /etc/trytond.conf \
        -d "$DB_NAME" \
        --all \
        && touch "$INIT_FLAG" \
        || echo "[gnuhealth] WARNING: init returned non-zero — may already exist."
else
    echo "[gnuhealth] Running upgrade check ..."
    trytond-admin \
        -c /etc/trytond.conf \
        -d "$DB_NAME" \
        --update all \
        2>/dev/null || echo "[gnuhealth] WARNING: upgrade returned non-zero."
fi

# Refresh module list so any new modules in /modules are visible in Tryton admin UI
echo "[gnuhealth] Updating module list ..."
trytond-admin -c /etc/trytond.conf -d "$DB_NAME" -m \
    2>/dev/null || echo "[gnuhealth] WARNING: module list update returned non-zero."

# Set admin password via TRYTONPASSFILE (trytond-admin -p reads from file, not CLI arg)
echo "[gnuhealth] Setting admin password ..."
PASS_FILE=$(mktemp)
echo "$ADMIN_PASS" > "$PASS_FILE"
TRYTONPASSFILE="$PASS_FILE" trytond-admin \
    -c /etc/trytond.conf \
    -d "$DB_NAME" \
    -p \
    2>/dev/null && echo "[gnuhealth] Admin password set." \
    || echo "[gnuhealth] WARNING: could not set admin password."
rm -f "$PASS_FILE"

# ── 4. Start trytond ──────────────────────────────────────────────────────────
echo "[gnuhealth] Starting trytond on 0.0.0.0:8069 ..."
exec trytond -c /etc/trytond.conf
