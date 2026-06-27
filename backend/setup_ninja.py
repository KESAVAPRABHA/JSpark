import asyncio
from prisma import Prisma

async def setup_test_data():
    db = Prisma()
    await db.connect()
    
    print("Injecting Ninja into the database...")
    
    # 1. Create the Employee
    try:
        await db.employee.upsert(
            where={"id": "NINJA_TEST_EMP"},
            data={
                "create": {"id": "NINJA_TEST_EMP", "designation": "Test Ninja", "department": "Delivery"},
                "update": {}
            }
        )
        print("✅ Ninja Employee created.")
    except Exception as e:
        print(f"Error creating employee: {e}")

    # 2. Create the Project
    try:
        await db.project.upsert(
            where={"id": "NINJA_PROJECT"},
            data={
                "create": {"id": "NINJA_PROJECT", "status": "ACTIVE"},
                "update": {}
            }
        )
        print("✅ Ninja Project created.")
    except Exception as e:
        print(f"Error creating project: {e}")
        
    await db.disconnect()

if __name__ == "__main__":
    asyncio.run(setup_test_data())