# PROMPT: revoke-license
# Usage: Paste this entire block into a new Claude conversation
# to revoke a client license.
# Fill in all [bracketed fields] before pasting.
# ═══════════════════════════════════════════════════════════

I am building the KDavis Agentic Platform — a proprietary,
LLM-agnostic, Obsidian-backed agentic DevOps platform.
Private GitHub repo: KDavisCodeCloud/kdavis-agentic-platform

REVOKE CLIENT LICENSE:

Client name:       [full name]
Client slug:       [slug]
License key:       [KDAP-SLUG-T#-EXPIRY-CHECKSUM]
Revocation reason: [non-payment | breach of agreement |
                   termination | mutual agreement]
Effective:         [immediately | end of billing period — date]
Outstanding balance: $[X] (if any)

SITUATION:
[Describe what happened — why the license is being revoked.
Be specific. This becomes part of the legal record.]

BUILD THE FOLLOWING — IN ORDER:
1. Move license key from active to revoked in key registry
2. Push revocation to license server
3. Revocation notice letter to client (.docx)
   - Formal and professional
   - States effective date
   - States outstanding balance if any
   - States data destruction requirements
   - References the license agreement section violated
4. Final invoice if balance outstanding (.docx)
5. Cease and desist letter if breach involved (.docx)
6. Log revocation event to knowledge/operator/license-registry.md
7. Log revocation to knowledge/clients/[slug]/audit-trail/
8. Update client status in knowledge/operator/client-registry.md

TONE:
Professional and factual. Not aggressive but firm.
Every document becomes a legal record if this escalates.
