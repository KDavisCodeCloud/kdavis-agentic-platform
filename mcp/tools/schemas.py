"""
PROPRIETARY AND CONFIDENTIAL
Copyright (c) 2026 THD Agentic Systems LLC. All rights reserved.
"""

"""
JSON Schema definitions for all MCP tool inputs.

Every tool call validates its arguments against the schema here before
reaching the upstream backend. Invalid inputs are rejected immediately
with the caller identity logged. Argument values are never logged —
only argument shapes (which keys were present, which were missing).
"""

# ── Read tools ────────────────────────────────────────────────────────────────

LIST_INCIDENTS_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "status_filter": {
            "type": "string",
            "enum": ["pending", "approved", "rejected", "executed", "failed"],
            "description": "Filter by incident status. Omit to return all.",
        },
    },
    "additionalProperties": False,
}

GET_INCIDENT_SCHEMA: dict = {
    "type": "object",
    "required": ["incident_id"],
    "properties": {
        "incident_id": {
            "type": "string",
            "minLength": 1,
            "maxLength": 128,
            "pattern": r"^[a-zA-Z0-9_\-]+$",
            "description": "Unique incident identifier.",
        },
    },
    "additionalProperties": False,
}

LIST_AGENTS_SCHEMA: dict = {
    "type": "object",
    "properties": {},
    "additionalProperties": False,
}

GET_WORKSPACE_STATUS_SCHEMA: dict = {
    "type": "object",
    "properties": {},
    "additionalProperties": False,
}

# ── Write tools ───────────────────────────────────────────────────────────────

APPROVE_INCIDENT_SCHEMA: dict = {
    "type": "object",
    "required": ["incident_id"],
    "properties": {
        "incident_id": {
            "type": "string",
            "minLength": 1,
            "maxLength": 128,
            "pattern": r"^[a-zA-Z0-9_\-]+$",
        },
        "approver_note": {
            "type": "string",
            "maxLength": 1000,
            "description": "Optional note from the approver. Written to audit trail.",
        },
    },
    "additionalProperties": False,
}

REJECT_INCIDENT_SCHEMA: dict = {
    "type": "object",
    "required": ["incident_id", "reason"],
    "properties": {
        "incident_id": {
            "type": "string",
            "minLength": 1,
            "maxLength": 128,
            "pattern": r"^[a-zA-Z0-9_\-]+$",
        },
        "reason": {
            "type": "string",
            "minLength": 1,
            "maxLength": 2000,
            "description": "Reason for rejection. Written to audit trail.",
        },
    },
    "additionalProperties": False,
}

REQUEST_TRIAGE_SCHEMA: dict = {
    "type": "object",
    "required": ["description"],
    "properties": {
        "description": {
            "type": "string",
            "minLength": 10,
            "maxLength": 5000,
            "description": "Human-readable description of the event to triage.",
        },
        "context": {
            "type": "object",
            "description": "Optional structured context: environment, service name, log snippet, etc.",
            "additionalProperties": True,
            "maxProperties": 20,
        },
    },
    "additionalProperties": False,
}

# ── Schema registry — used by the kill switch / validation middleware ─────────

TOOL_SCHEMAS: dict[str, dict] = {
    "list_incidents":       LIST_INCIDENTS_SCHEMA,
    "get_incident":         GET_INCIDENT_SCHEMA,
    "list_agents":          LIST_AGENTS_SCHEMA,
    "get_workspace_status": GET_WORKSPACE_STATUS_SCHEMA,
    "approve_incident":     APPROVE_INCIDENT_SCHEMA,
    "reject_incident":      REJECT_INCIDENT_SCHEMA,
    "request_triage":       REQUEST_TRIAGE_SCHEMA,
}
