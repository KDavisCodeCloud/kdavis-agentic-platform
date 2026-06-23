# End User License Agreement (EULA)
# Cloud Decoded — KDavis Agentic Systems LLC
# Effective Date: 2026-01-01

Copyright (c) 2026 KDavis Agentic Systems LLC. All rights reserved.

## 1. Grant of License

KDavis Agentic Systems LLC ("Licensor") grants you ("Licensee") a non-exclusive, non-transferable, revocable license to access and use the Cloud Decoded platform ("Software") strictly in accordance with this Agreement and your active subscription tier.

## 2. Restrictions

Licensee shall NOT:

- Copy, modify, distribute, sublicense, or sell any portion of the Software
- Reverse engineer, decompile, disassemble, or attempt to extract source code, agent prompts, system architectures, or LLM routing logic from the Software
- Circumvent, disable, or bypass any subscription enforcement, token metering, or access control mechanism
- Use the Software to build a competing product or service
- Share workspace tokens, API credentials, or access artifacts with unauthorized parties
- Extract, scrape, or export agent prompt templates, SOPs, or workflow logic

## 3. BYOK (Bring Your Own Key) Policy

Licensee supplies their own LLM provider API key ("BYOK Key"). The Software:
- Stores BYOK Keys encrypted at rest using AES-256 (Fernet)
- Uses BYOK Keys solely to process Licensee's own incidents and tasks
- Never transmits BYOK Keys to third parties or logs them in plain text
- Revokes BYOK Key access automatically upon subscription cancellation or terms violation

## 4. Subscription & Access

Access is contingent on an active, paid subscription. The Software automatically enforces:
- Subscription status checks on every API request
- Token budget limits per workspace per calendar month
- Automatic suspension upon non-payment, exceeding limits, or terms violation

KDavis Agentic Systems LLC reserves the right to suspend or terminate access without refund for material violations of this Agreement.

## 5. No Autonomous Execution

The Software is designed with mandatory Human-in-the-Loop (HITL) gates. The Licensor makes no warranty that the Software will prevent all unintended infrastructure actions. Licensee is solely responsible for reviewing and approving all remediation options before execution.

## 6. Limitation of Liability

TO THE MAXIMUM EXTENT PERMITTED BY LAW, LICENSOR SHALL NOT BE LIABLE FOR ANY INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES, INCLUDING BUT NOT LIMITED TO LOSS OF DATA, INFRASTRUCTURE OUTAGES, OR FINANCIAL LOSSES, ARISING FROM USE OF THE SOFTWARE.

## 7. Governing Law

This Agreement is governed by the laws of the State of [STATE], United States, without regard to conflict of law principles.

## 8. Contact

For licensing inquiries: legal@kdavisagentic.com
