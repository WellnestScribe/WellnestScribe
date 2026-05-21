#!/bin/bash
# GNU Health container entrypoint
# 1. pip-install GNU Health modules from the bind-mounted source
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

# ── 1. Install GNU Health modules from mounted source ────────────────────────
if [ -d "$MODULES_SRC" ]; then
    echo "[gnuhealth] Installing modules from $MODULES_SRC ..."
    for dir in "$MODULES_SRC"/*/; do
        name=$(basename "$dir")
        if [ -f "$dir/pyproject.toml" ] || [ -f "$dir/setup.py" ]; then
            echo "  → $name"
            pip install --quiet --no-build-isolation --no-deps -e "$dir" \
                || echo "  ! Warning: could not install $name — skipping"
        fi
    done
    echo "[gnuhealth] Module installation done."
else
    echo "[gnuhealth] WARNING: GNUHEALTH_MODULES_DIR=$MODULES_SRC not found — starting without GNU Health modules."
fi

# ── 2. Wait for PostgreSQL ───────────────────────────────────────────────────
echo "[gnuhealth] Waiting for PostgreSQL at $DB_HOST:$DB_PORT ..."
until pg_isready -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" -q; do
    sleep 2
done
echo "[gnuhealth] PostgreSQL ready."

# ── 3. Initialise / update database ─────────────────────────────────────────
INIT_FLAG="/var/lib/trytond/.db_initialised"

if [ ! -f "$INIT_FLAG" ]; then
    echo "[gnuhealth] First-run: initialising database $DB_NAME ..."
    python -m trytond.admin \
        -c /etc/trytond.conf \
        -d "$DB_NAME" \
        --all \
        && touch "$INIT_FLAG" \
        || echo "[gnuhealth] WARNING: database init returned non-zero — it may already be initialised."
else
    echo "[gnuhealth] Running database upgrade check ..."
    python -m trytond.admin \
        -c /etc/trytond.conf \
        -d "$DB_NAME" \
        --update all \
        || echo "[gnuhealth] WARNING: upgrade returned non-zero."
fi

# Set / reset admin password
echo "[gnuhealth] Setting admin password ..."
python -m trytond.admin \
    -c /etc/trytond.conf \
    -d "$DB_NAME" \
    --password "$ADMIN_PASS" \
    2>/dev/null || echo "[gnuhealth] WARNING: could not set admin password."

# ── 4. Start trytond ─────────────────────────────────────────────────────────
echo "[gnuhealth] Starting trytond on 0.0.0.0:8069 ..."
exec python -m trytond -c /etc/trytond.conf
