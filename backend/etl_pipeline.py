import pandas as pd
import asyncio
import re
from prisma import Prisma

def clean_and_prepare_data(input_dir='../data'):
    # 1. Employees (Fix: Impute department to prevent 35% data loss, drop constant)
    df_emp = pd.read_csv(f'{input_dir}/01_260624_employee_details.csv', encoding='latin1')
    df_emp = df_emp.drop(columns=['is_active_version'], errors='ignore')
    df_emp = df_emp.dropna(subset=['employee_id'])
    df_emp['department_name'] = df_emp['department_name'].fillna('Delivery')
    df_emp['job_name'] = df_emp['job_name'].fillna('Unassigned')
    df_emp = df_emp[df_emp['department_name'] == 'Delivery']

    # 2. Projects (Fix: drop constant)
    df_proj = pd.read_csv(f'{input_dir}/02_260624_project_details.csv', encoding='latin1')
    df_proj = df_proj.drop(columns=['is_active_version'], errors='ignore')
    df_proj = df_proj.dropna(subset=['project_id'])

    # 3. Allocations (Fix: map null employees to OPEN_REQUISITION)
    df_alloc = pd.read_csv(f'{input_dir}/03_260623_Project_Allocation_Details.csv', encoding='latin1')
    df_alloc = df_alloc.drop(columns=['is_active_version'], errors='ignore')
    df_alloc['employee_id'] = df_alloc['employee_id'].fillna('OPEN_REQUISITION')

    # 4. Skills (Fix: Keep 0 scores for negative weighting in Phase 2 vectorization)
    df_skills = pd.read_csv(f'{input_dir}/05_260624_Skill_Data.csv', encoding='latin1')
    df_skills['Score'] = pd.to_numeric(df_skills['Score'], errors='coerce').fillna(0)

    # 5. Timesheets (Fix: drop 100% null and meaningless columns)
    df_timesheet = pd.read_csv(f'{input_dir}/04. 260624 timesheet_details_2026.csv', encoding='latin1')
    df_timesheet = df_timesheet.drop(columns=['job_name', 'pru_id', 'is_billable', 'type', 'submitted_on', 'data_loaded_at'], errors='ignore')

    # 6. Pipeline (Fix: Impute SOW, bound %, drop 100% null columns)
    df_pipeline = pd.read_csv(f'{input_dir}/07_260624_Pipeline_Details.csv', encoding='latin1')
    df_pipeline = df_pipeline.drop(columns=['EM', 'Resource Recommended', '% Available', 'Skillset Match (Complete / Partial / No)'], errors='ignore')
    df_pipeline['SOW Signed'] = df_pipeline['SOW Signed'].fillna('No')
    
    def bound_percentage(val):
        val = str(val).strip()
        if '100' in val: return 100
        nums = re.findall(r'\d+', val)
        return max([int(n) for n in nums]) if nums else 100
        
    df_pipeline['%'] = df_pipeline['%'].apply(bound_percentage)

    return df_emp, df_proj, df_alloc, df_skills

async def ingest_data():
    db = Prisma()
    await db.connect()
    
    # 🚨 THE FIX: WIPE THE DATABASE CLEAN BEFORE INGESTION 🚨
    print("Wiping existing data for clean ingestion...")
    await db.skill.delete_many()
    await db.allocation.delete_many()
    await db.project.delete_many()
    await db.employee.delete_many()
    
    df_emp, df_proj, df_alloc, df_skills = clean_and_prepare_data()
    
    print("Ingesting Employees...")
    # ... keep the rest of your loops exactly the same ...
    for _, row in df_emp.iterrows():
        try:
            await db.employee.upsert(
                where={'id': str(row['employee_id'])},
                data={
                    'create': {
                        'id': str(row['employee_id']),
                        'location': str(row['location']) if pd.notna(row['location']) else None,
                        'designation': str(row['job_name']),
                        'department': str(row['department_name'])
                    },
                    'update': {'designation': str(row['job_name'])}
                }
            )
        except Exception: pass
            
    print("Ingesting Projects...")
    for _, row in df_proj.iterrows():
        try:
            await db.project.upsert(
                where={'id': str(row['project_id'])},
                data={
                    'create': {
                        'id': str(row['project_id']),
                        'status': str(row['project_status']),
                        'tech_coe': str(row['tech_coe']) if pd.notna(row['tech_coe']) else None
                    },
                    'update': {'status': str(row['project_status'])}
                }
            )
        except Exception: pass

    print("Ingesting Allocations...")
    for _, row in df_alloc.iterrows():
        try:
            if str(row['employee_id']) != 'OPEN_REQUISITION':
                await db.allocation.create(
                    data={
                        'employee_id': str(row['employee_id']),
                        'project_id': str(row['project_id']),
                        'status': str(row['resourcing_status']),
                        'percentage': int(row['allocation_by_percentage']) if pd.notna(row['allocation_by_percentage']) else 0
                    }
                )
        except Exception: pass

    print("Ingesting Skills...")
    for _, row in df_skills.iterrows():
        try:
            await db.skill.create(
                data={
                    'employee_id': str(row['employee_id']),
                    'coe': str(row['COE']),
                    'skill_name': str(row['Skill']),
                    'score': int(row['Score'])
                }
            )
        except Exception: pass

    print("Phase 1 Complete.")
    await db.disconnect()

if __name__ == "__main__":
    asyncio.run(ingest_data())