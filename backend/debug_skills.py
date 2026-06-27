import asyncio
from prisma import Prisma

async def check_swe_skills():
    db = Prisma()
    await db.connect()
    
    # Fetch Senior Software Engineers and their skills
    engineers = await db.employee.find_many(
        where={"designation": "Senior Software Engineer"},
        include={"skills": True}
    )
    
    print(f"Found {len(engineers)} Senior Software Engineers.\n")
    
    for emp in engineers[:3]: # Just look at the first 3
        print(f"--- Employee: {emp.id} ---")
        for skill in emp.skills:
            print(f"- {skill.skill_name} (Score: {skill.score})")
        print("\n")
            
    await db.disconnect()

if __name__ == "__main__":
    asyncio.run(check_swe_skills())