# Built from uv.lock, not a fresh pip resolve, so this image gets the exact
# package versions developed/tested against locally.
FROM python:3.12-slim

COPY --from=ghcr.io/astral-sh/uv:0.10.10 /uv /usr/local/bin/uv

WORKDIR /app
ENV UV_PROJECT_ENVIRONMENT=/usr/local

COPY pyproject.toml uv.lock ./
COPY src ./src

RUN uv sync --frozen --extra api --extra ml --no-dev

EXPOSE 8000
CMD ["uvicorn", "weatherml.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
