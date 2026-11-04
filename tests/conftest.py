"""Tests never touch the real state/cache folders or the real API."""
import os
import tempfile

_tmp = tempfile.mkdtemp(prefix="assistant-test-")
os.environ["ASSISTANT_STATE_DIR"] = os.path.join(_tmp, "state")
os.environ["ASSISTANT_CACHE_DIR"] = os.path.join(_tmp, "cache")
os.environ.pop("ANTHROPIC_API_KEY", None)
