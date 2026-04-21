import os
import sys
from pathlib import Path

# app.py reads required env vars at import time. Seed placeholders so `import app`
# succeeds in unit tests that don't actually hit any network.
os.environ.setdefault("LITELLM_BASE_URL", "http://unused/v1")
os.environ.setdefault("LITELLM_API_KEY", "test-key")
os.environ.setdefault("ROUTER_API_KEY", "test-key")
os.environ.setdefault("LLMROUTER_DB_PATH", "/tmp/llmrouter-test.db")
os.environ.setdefault("LOG_REQUESTS", "0")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
