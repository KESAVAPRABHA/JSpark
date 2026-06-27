import asyncio
from prisma import Prisma

async def clean_garbage_data():
    db = Prisma()
    await db.connect()
    
    # Delete all allocations for our test dummy employees
    deleted = await db.allocation.delete_many(
        where={
            "employee_id": {"in": ["EMP999", "EMP998"]}
        }
    )
    
    print(f"✅ Deleted {deleted} corrupted test allocations.")
    await db.disconnect()

if __name__ == "__main__":
    asyncio.run(clean_garbage_data())