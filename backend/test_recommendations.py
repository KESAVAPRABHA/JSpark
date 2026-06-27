import asyncio
from prisma import Prisma
from datetime import datetime, timezone

async def check_candidate_skills(target_role: str = "Senior Software Engineer"):
    db = Prisma()
    await db.connect()

    today = datetime.now(timezone.utc)

    employees = await db.employee.find_many(
        where={
            "designation": target_role,
            "is_recommended_pool": True
        },
        include={"allocations": True}
    )

    print(f"--- Skills Report for Available {target_role}s ---")

    for emp in employees:
        active_pct = 0
        for alloc in emp.allocations or []:
            if alloc.is_allocation_active and not alloc.is_placeholder_date:
                if alloc.allocated_end_date and alloc.allocated_end_date < today:
                    continue
                active_pct += alloc.percentage
        
        # Filter for available candidates only (< 100% allocation)
        if active_pct < 100:
            print(f"\nID: {emp.id} | Available: {100 - active_pct}%")
            
            # Print available skill/text fields dynamically based on schema attributes
            skills = getattr(emp, "skills", None)
            skills_list = getattr(emp, "skills_list", None)
            bio = getattr(emp, "bio", None)
            resume = getattr(emp, "resume_text", None)
            
            if skills:
                print(f" - Skills: {skills}")
            if skills_list:
                print(f" - Skills List: {skills_list}")
            if bio:
                print(f" - Bio: {bio}")
            if resume:
                print(f" - Resume Text: {resume}")
                
            # If skills are stored in a nested JSON or relation, fallback to printing all non-relational fields
            if not any([skills, skills_list, bio, resume]):
                emp_dict = emp.model_dump()
                emp_dict.pop("allocations", None)
                print(f" - Data: {emp_dict}")

    await db.disconnect()

if __name__ == "__main__":
    asyncio.run(check_candidate_skills())