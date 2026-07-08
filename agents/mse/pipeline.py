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
pipeline — chains opportunity_finder -> demand_validator -> product_spec_writer.
CLI entry point for a manual/cron-triggered MSE research run.
"""

import argparse
import asyncio

from agents.mse.demand_validator import DemandValidator
from agents.mse.opportunity_finder import OpportunityFinder
from agents.mse.product_spec_writer import ProductSpecWriter


async def run_pipeline(niche_hint: str = '') -> list[dict]:
    finder = OpportunityFinder()
    validator = DemandValidator()
    writer = ProductSpecWriter()
    opportunities = await finder.find(niche_hint)
    results = []
    for opp in opportunities:
        validated = await validator.validate(opp)
        if validated['go']:
            spec = await writer.write_spec(validated)
            results.append({**validated, 'spec': spec})
        else:
            results.append(validated)
    return results


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--niche', default='')
    args = parser.parse_args()
    results = asyncio.run(run_pipeline(args.niche))
    go_count = len([r for r in results if r.get('go')])
    print(f"Pipeline complete. {go_count} of {len(results)} opportunities validated.")
