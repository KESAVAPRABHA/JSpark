"""
seed_sow.py — P0-2 Fix: Promote speculative pipeline rows to SOW Signed=True

PROBLEM: Only 7 pipeline rows have sow_signed=True in the raw data.
Running GET /api/dashboard/pipeline-outlook?sow_filter=confirmed returns near-zero demand.

USAGE: Run ONCE after etl_pipeline.py, before the demo.
  python seed_sow.py

This promotes the top 40 speculative rows (sorted by earliest start_date) to
SOW Signed=True so the confirmed pipeline view shows meaningful demand.

Note: This is a demo data enrichment step. In production, SOW status would
be managed in the CRM and pushed via a webhook.
"""

import asyncio
from prisma import Prisma


async def promote_sow():
    db = Prisma()
    await db.connect()

    # Show current state
    all_rows = await db.pipelinerequest.find_many()
    current_signed = [r for r in all_rows if r.sow_signed]
    print(f"Current state: {len(all_rows)} total pipeline rows, {len(current_signed)} SOW=Yes")

    # Get top N speculative rows by start_date (closest to today first)
    speculative = await db.pipelinerequest.find_many(
        where={"sow_signed": False, "start_date": {"not": None}},
        order={"start_date": "asc"},
        take=40,
    )

    if not speculative:
        print("No speculative rows with start dates found — nothing to promote.")
        await db.disconnect()
        return

    ids = [r.id for r in speculative]
    await db.pipelinerequest.update_many(
        where={"id": {"in": ids}},
        data={"sow_signed": True},
    )

    # Verify
    new_count = await db.pipelinerequest.count(where={"sow_signed": True})
    print(f"✅ Promoted {len(ids)} rows to SOW Signed=True")
    print(f"   New total SOW=Yes: {new_count} / {len(all_rows)}")
    print(f"   Run: GET /api/dashboard/pipeline-outlook?sow_filter=confirmed")

    await db.disconnect()


if __name__ == "__main__":
    asyncio.run(promote_sow())
