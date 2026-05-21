FROM python:3.12-slim

LABEL maintainer="WellnestScribe"
LABEL description="GNU Health 5.0 / Tryton 7.0 server"

RUN apt-get update && apt-get install -y --no-install-recommends \
    postgresql-client \
    libpq-dev \
    gcc \
    g++ \
    libffi-dev \
    libxml2-dev \
    libxslt1-dev \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Core Tryton 7.0 modules that GNU Health health module requires
# (party, company, currency, product — NOT account/stock, those bring unwanted deps)
RUN pip install --no-cache-dir \
    "trytond>=7.0,<7.1" \
    "trytond-party>=7.0,<7.1" \
    "trytond-company>=7.0,<7.1" \
    "trytond-currency>=7.0,<7.1" \
    "trytond-product>=7.0,<7.1" \
    "trytond-country>=7.0,<7.1" \
    psycopg2-binary \
    pillow \
    pytz \
    python-dateutil \
    "python-sql>=1.3" \
    matplotlib \
    lxml \
    relatorio \
    Genshi

# GNU Health core module from PyPI — installs into trytond/modules/health/
# This avoids needing to mount the F: drive into Docker
RUN pip install --no-cache-dir "gnuhealth==5.0.6"

# Tryton web extras (werkzeug, passlib) — needed to serve the SAO web client
RUN pip install --no-cache-dir "trytond[web]>=7.0,<7.1"

# proteus — Tryton XML-RPC client used by the WellnestScribe bridge layer
RUN pip install --no-cache-dir "proteus>=7.0,<7.1"

# Web root: bake in a status page (always present), then try to layer SAO on top.
# The COPY guarantees index.html exists even if all download strategies fail.
RUN mkdir -p /opt/gnuhealth/web
COPY web/index.html /opt/gnuhealth/web/index.html

# Try to install the SAO browser client — if it works it overwrites index.html.
# Failures are intentionally swallowed; the status page above is the fallback.
RUN pip install --no-cache-dir "tryton-sao>=7.0,<7.1" 2>/dev/null && \
    SAO_PATH=$(python -c "import tryton_sao, os; print(os.path.dirname(tryton_sao.__file__))") && \
    cp -r "$SAO_PATH/." /opt/gnuhealth/web/ && \
    echo "SAO installed from PyPI" || \
    echo "SAO not available — status page will be served instead"

WORKDIR /opt/gnuhealth

# WellnestScribe Tryton module — copied into /modules/ so entrypoint.sh symlinks it
COPY modules/ /modules/

COPY trytond.conf /etc/trytond.conf
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

RUN mkdir -p /var/lib/trytond

EXPOSE 8069

ENTRYPOINT ["/entrypoint.sh"]
