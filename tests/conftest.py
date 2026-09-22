import os

# Safety net so any incidental Settings() construction during unit test
# collection/import doesn't blow up on missing required fields — integration
# tests that need a real database override DATABASE_URL themselves.
os.environ.setdefault("WEATHERSTACK_API_KEY", "test-key")
os.environ.setdefault("DATABASE_URL", "postgresql+psycopg2://test:test@localhost:5432/test")
os.environ.setdefault("USE_MOCK_CLIENT", "true")
os.environ.setdefault("MLFLOW_DISABLE_AGENT_HINT", "1")
