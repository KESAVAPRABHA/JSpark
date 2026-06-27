import asyncio
from prisma import Prisma

async def check_available_roles():
    db = Prisma()
    await db.connect()
    
    # Fetch all employees and get unique designations
    employees = await db.employee.find_many()
    unique_roles = set([emp.designation for emp in employees if emp.designation])
    
    print("🎯 AVAILABLE ROLES IN YOUR DATABASE:")
    for role in sorted(unique_roles):
        print(f'- "{role}"')
        
    await db.disconnect()

if __name__ == "__main__":
    asyncio.run(check_available_roles())