"""
Every router module api/main.py imports must be mounted.

api/routes/policies.py was imported but never passed to include_router, so
Settings → Policies (execution policy, resource exemptions, "Exempt this
resource" on the incident card) returned 404 in production.
"""
import ast
import importlib
from pathlib import Path

import pytest

_MAIN = Path(__file__).resolve().parents[1] / "api" / "main.py"


def _imported_route_modules() -> list[str]:
    names = []
    for node in ast.parse(_MAIN.read_text()).body:
        if isinstance(node, ast.ImportFrom) and node.module == "api.routes":
            names += [alias.name for alias in node.names]
    return names


def test_main_imports_route_modules():
    assert "policies" in _imported_route_modules()


@pytest.mark.parametrize("module", _imported_route_modules())
def test_every_imported_router_is_mounted(module):
    from api.main import app
    router = getattr(importlib.import_module(f"api.routes.{module}"), "router", None)
    assert router is not None, f"api.routes.{module} has no router"
    served = {(getattr(r, "path", ""), tuple(sorted(getattr(r, "methods", None) or ()))) for r in app.routes}
    missing = [
        route.path for route in router.routes
        if not any(path.endswith(route.path) and methods == tuple(sorted(route.methods or ()))
                   for path, methods in served)
    ]
    assert missing == [], f"api.routes.{module} is imported in api/main.py but these routes aren't mounted: {missing}"


def test_policies_routes_are_served():
    from api.main import app
    paths = {getattr(r, "path", "") for r in app.routes}
    assert {"/api/v1/workspace/policies/exemptions",
            "/api/v1/incidents/{incident_id}/exempt-resource"} <= paths


def test_no_execution_policy_toggle_is_served():
    """Approval can't be turned off: the auto_execution_enabled toggle was removed (2026-11-18)."""
    from api.main import app
    paths = {getattr(r, "path", "") for r in app.routes}
    assert "/api/v1/workspace/policies" not in paths
    assert "/api/v1/workspace/policies/execution" not in paths
