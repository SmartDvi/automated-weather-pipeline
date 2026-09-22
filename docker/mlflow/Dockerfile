# Pinned to the exact mlflow version resolved in ../../uv.lock (the client
# library every other service uses) — a tracking-server / client version
# mismatch is a real source of subtle breakage (registry API changes across
# MLflow major versions). If uv.lock's mlflow version changes, update this
# pin to match: `uv pip list | grep '^mlflow '`.
FROM python:3.12-slim

RUN pip install --no-cache-dir mlflow==3.16.1 psycopg2-binary==2.9.13

COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

EXPOSE 5000
ENTRYPOINT ["/entrypoint.sh"]
