"""
PROPRIETARY AND CONFIDENTIAL
Copyright (c) 2026 THD Agentic Systems LLC. All rights reserved.

This software is licensed, not sold. Unauthorized copying, modification,
distribution, reverse engineering, or prompt extraction is strictly prohibited.
Access is governed by the End User License Agreement at /legal/LICENSE.md.
Subscription compliance is enforced at runtime — access revokes automatically
on non-payment or terms violation.
"""

"""
Lead capture and nurture pipeline: anonymous visitor tracking, signup /
trial processing, and the CRM (Systeme.io) + Slack integrations that
route captured leads onward. HTTP route wiring (api/routes/leads.py)
and the visitor_capture_agent that consumes these webhooks are out of
scope here — this package exposes plain, testable processing functions
a route layer calls into.
"""
