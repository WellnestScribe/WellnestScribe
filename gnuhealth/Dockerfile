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
    && rm -rf /var/lib/apt/lists/*

# Tryton 7.0 core + standard modules GNU Health depends on
RUN pip install --no-cache-dir \
    "trytond>=7.0,<7.1" \
    "trytond-party>=7.0,<7.1" \
    "trytond-company>=7.0,<7.1" \
    "trytond-currency>=7.0,<7.1" \
    "trytond-product>=7.0,<7.1" \
    "trytond-country>=7.0,<7.1" \
    "trytond-account>=7.0,<7.1" \
    psycopg2-binary \
    pillow \
    pytz \
    python-dateutil \
    "python-sql>=1.3" \
    matplotlib \
    lxml \
    relatorio \
    Genshi

# proteus client (for health checks / admin scripts)
RUN pip install --no-cache-dir "proteus>=7.0,<7.1"

WORKDIR /opt/gnuhealth

COPY trytond.conf /etc/trytond.conf
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

RUN mkdir -p /var/lib/trytond

EXPOSE 8069

ENTRYPOINT ["/entrypoint.sh"]
