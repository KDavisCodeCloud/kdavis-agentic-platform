"""
mcp/ imports flatly (`from config import ...`, `from auth.models import ...`),
matching how server.py itself runs with mcp/ as the working directory
(Dockerfile: WORKDIR /app, COPY . .). Put mcp/ on sys.path so tests can
import the same way without needing a package install.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Config reads DB/Supabase values from the environment at import time.
# Tests never talk to a real DB or Supabase project -- set harmless
# placeholders so importing config.py and its dependents doesn't require
# real production secrets.
os.environ.setdefault("MCP_UPSTREAM_URL", "http://localhost:8000")
os.environ.setdefault("MCP_SERVICE_KEY", "test-service-key")
os.environ.setdefault("SUPABASE_URL", "https://example.supabase.co")
os.environ.setdefault("SUPABASE_JWT_SECRET", "test-jwt-secret")
os.environ.setdefault("DATABASE_URL", "postgresql://test:test@localhost:5432/test")
os.environ.setdefault("MCP_AUDIENCE", "mcp.theclouddecoded.com")
