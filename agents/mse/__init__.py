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
Micro SaaS Engine (MSE) research pipeline — discovers and validates
micro-SaaS opportunities for CEO dashboard review. Session 8.

opportunity_finder -> demand_validator -> product_spec_writer, chained by
pipeline.py. All LLM calls route through providers/router.py (never a
concrete provider SDK directly, per CLAUDE.md CORE PRINCIPLE 1). Every
call is DataSanitizationShield'd first and writes an audit_log entry,
win or lose (CORE PRINCIPLE 9).
"""
