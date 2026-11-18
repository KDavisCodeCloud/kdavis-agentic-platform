"""
scripts/comp_workspace.py — comp a workspace to a tier with no Stripe billing.

Operator CLI for the same action as POST /internal/workspaces/{id}/comp
(core/workspace_comp.py). Reads DATABASE_URL from the environment; writes a
workspace_comped audit_events row.

    DATABASE_URL=... python scripts/comp_workspace.py <workspace_id> <tier> "<reason>" "<actor>"
"""

import asyncio
import os
import sys

import asyncpg

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.workspace_comp import CompError, comp_workspace  # noqa: E402


async def _main(workspace_id: str, tier: str, reason: str, actor: str) -> int:
    dsn = os.environ.get("DATABASE_URL", "").replace("postgresql+asyncpg://", "postgresql://")
    if not dsn:
        print("DATABASE_URL is not set", file=sys.stderr)
        return 2
    conn = await asyncpg.connect(dsn, statement_cache_size=0)
    try:
        row = await comp_workspace(conn, workspace_id, tier, reason, actor)
    except CompError as exc:
        print(f"Refused: {exc}", file=sys.stderr)
        return 1
    finally:
        await conn.close()
    print(f"Comped {workspace_id}: tier={row['product_tier']} status={row['stripe_subscription_status']} "
          f"by={row['comped_by']} at={row['comped_at'].isoformat()}")
    return 0


if __name__ == "__main__":
    if len(sys.argv) != 5:
        print(__doc__, file=sys.stderr)
        sys.exit(2)
    sys.exit(asyncio.run(_main(*sys.argv[1:])))
