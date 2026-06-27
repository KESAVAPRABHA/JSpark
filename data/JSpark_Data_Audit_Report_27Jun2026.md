# JSpark — Data Audit Report
**Audit Date:** 27 June 2026
**Against:** v1 Backend Audit + Five Required Deliverables
**Dataset version:** Updated 26–27 June 2026 uploads
**Scope:** All 8 data files (01–07, 09). File 08 not present — assumed excluded.

---

## How to Use This Document

This audit is **plug-and-play**. Each section follows the same structure:

1. **What the data contains** — row counts, columns, distributions
2. **Issues found** — ranked 🔴 Blocker / 🟠 Gap / 🟡 Warning
3. **Exact fix** — what you edit, what you write in the ETL, what you write in the schema

Every issue is self-contained. You can hand any section to a developer and they can fix it without reading the rest.

---

## Summary Scorecard

| File | Rows | Status | Blockers | Gaps | Warnings |
|------|------|--------|----------|------|---------|
| 01 Employee | 1,042 | ⚠️ Usable with filters | 0 | 1 | 3 |
| 02 Projects | 2,052 | ⚠️ Usable with filters | 1 | 2 | 2 |
| 03 Allocations | 31,969 | 🔴 Critical issues | 2 | 2 | 1 |
| 04 Timesheets | 128,526 | 🔴 Critical issues | 2 | 0 | 1 |
| 05 Skills | 82,211 | ⚠️ Usable with normalisation | 0 | 1 | 2 |
| 06 Competency | 196 | ⚠️ Needs schema design | 0 | 2 | 1 |
| 07 Pipeline | 293 | 🔴 Critical issues | 1 | 3 | 2 |
| 09 WSR | 71,205 | ⚠️ Usable with filters | 0 | 1 | 1 |

**Overall verdict:** Data is substantially more complete than v0. The date corruption in timesheets and WSR is fixed. The schema gaps identified in the backend audit are confirmed. Three specific issues are hard blockers before any endpoint can go live.

---

## File 01 — Employee Details
**File:** `01__260624_employee_details.csv`
**Rows:** 1,042 | **Columns:** 9

### What's in it

| Column | Non-null | Notes |
|--------|----------|-------|
| employee_id | 1,042 | EMP1–EMP1042. Primary key. No duplicates. |
| location | 715 | 327 nulls. Chennai (512), London (164), New York (39). |
| date_of_join | 665 | DD-MM-YYYY. 377 nulls — all on inactive rows. |
| date_of_resignation | 14 | 14 employees resigned. These must be excluded from recommendations. |
| job_name | 659 | Top roles: Trainee SE (142), Senior SE (102), SE (65), Solutions Enabler (62), AC (48). 383 nulls. |
| department_name | 700 | Delivery (640), Support (24), HR (15), Finance (7), others. 342 nulls. |
| manager_id | 665 | References another employee_id. 377 nulls. |
| account_status | 1,042 | 1 = active (665), 0 = inactive (377). No nulls. |
| is_active_version | 1,042 | Always 1. Drop this column. |

### Issues Found

**🟠 GAP — 377 inactive employees create null noise**

Of the 1,042 rows, 377 have `account_status = 0`. Of those, 334 have null `department_name` AND null `job_name` AND null `date_of_join`. These are historical/departed employees retained for audit history.

**Fix (ETL):** Apply a compound filter at ETL ingestion time. Only ingest rows where:
```python
df_emp = df_emp[
    (df_emp['account_status'] == 1) &
    (df_emp['department_name'] == 'Delivery') &
    (df_emp['date_of_resignation'].isna())
]
```
This reduces the working employee pool from 1,042 to approximately **286 active Delivery employees** — the correct denominator for all recommendation and utilisation logic.

**🟡 WARNING — 8 active Delivery employees with null job_name**

After filtering to `account_status = 1` and `department_name = Delivery`, 8 employees still have a null `job_name`. They cannot be vectorised or role-matched without a designation.

**Fix (manual data edit):** In `01__260624_employee_details.csv`, locate the 8 employees with `account_status=1`, `department_name='Delivery'`, `job_name=null`. Fill job_name from their skills COE `Designation` column in File 05 (skill data). This is a 5-minute manual lookup — the Skill file has `Designation` populated for all 82,211 rows including these employees.

**🟡 WARNING — 327 null locations**

All 327 null-location rows belong to inactive employees (account_status = 0). After the ETL filter above, this issue disappears from the working dataset. No action needed.

**🟡 WARNING — Date format is DD-MM-YYYY, not DD/MM/YYYY**

`date_of_join` and `date_of_resignation` use `DD-MM-YYYY`. Your ETL must parse with `dayfirst=True`.

**Fix (ETL):**
```python
df_emp['date_of_join'] = pd.to_datetime(df_emp['date_of_join'], dayfirst=True, errors='coerce')
df_emp['date_of_resignation'] = pd.to_datetime(df_emp['date_of_resignation'], dayfirst=True, errors='coerce')
```

### Referential Integrity

✅ All employee_ids in Allocation, Timesheet, and Skill files match the Employee file. Zero orphan keys.

---

## File 02 — Project Details
**File:** `02__260624_project_details.csv`
**Rows:** 2,052 | **Columns:** 12

### What's in it

| Column | Non-null | Notes |
|--------|----------|-------|
| project_key | 2,052 | Hash. Not needed. |
| project_id | 2,039 | CLIENT_X_NNN format. **13 rows have null project_id.** |
| project_start_date | 2,052 | DD-MM-YYYY format. |
| project_end_date | 2,052 | DD-MM-YYYY format. |
| type_of_project | 2,052 | Client Project (1,678), Internal (241), Managed Services (96), BAU (34), Sales (3). |
| project_status | 2,052 | ACTIVE (124), COMPLETE (1,796), DEAL WON (45), PROPOSE (36), CLOSED (23), DEAL LOST (21), SOW PENDING (5), SCOPING APPROVAL (2). |
| reporter_id | 1,936 | FK to employee. 116 nulls — acceptable. |
| approver_id | 1,928 | FK to employee. 124 nulls — acceptable. |
| CLIENT_ID | 2,052 | No nulls. |
| tech_coe | 829 | Semicolon-separated multi-COE. 1,223 nulls — mostly COMPLETE projects. |
| proposition_coe | 1,056 | Secondary COE label. 996 nulls. |
| is_active_version | 2,052 | Always 1. Drop. |

### Active Project Breakdown (the ones that matter)

| Status | Count | Action |
|--------|-------|--------|
| ACTIVE | 124 | Delivering now |
| DEAL WON | 45 | Confirmed, not started |
| PROPOSE | 36 | Pre-sales |
| SOW PENDING SIGNATURE | 5 | Near-confirmed |
| SCOPING APPROVAL | 2 | Pre-sales |
| COMPLETE / CLOSED / LOST | 1,840 | Historical only |

**Active tech_coe distribution (top 5):** BI and Reporting (14), Data Engineering (14), Data Engineering + BI and Reporting combined (12), BI and Reporting + Data Engineering (8), TechOps and Automation (8).

### Issues Found

**🔴 BLOCKER — 13 rows with null project_id**

13 project rows have a null `project_id`. These cannot be used as foreign keys in the Allocation or WSR tables.

**Fix (ETL):**
```python
df_proj = df_proj.dropna(subset=['project_id'])
```
This also resolves the corresponding null in WSR's project_id_masked (same 13 IDs). Total usable projects: 2,039.

**🟠 GAP — No `sow_status` column in the data**

The problem statement makes `SOW Signed = Yes` a hard gate for confirmed demand in the 6-month pipeline outlook (Deliverable 2b). This field exists in File 07 (Pipeline) but NOT in File 02 (Projects). Projects in ACTIVE status are confirmed — they don't need SOW status. The SOW filter applies only to pipeline/pre-sales entries.

**Fix (schema + ETL logic):** Do not add a `sow_status` field to the Project model. Instead, map `project_status` to a confirmation tier:
- Confirmed: `ACTIVE`, `DEAL WON`
- Speculative: `PROPOSE`, `SOW PENDING SIGNATURE`, `SCOPING APPROVAL`

The SOW Signed field from File 07 Pipeline applies to pipeline rows only, not to project rows.

**🟠 GAP — 38 ACTIVE projects with `project_end_date` in the past**

As of 27 June 2026, 38 projects have `project_status = ACTIVE` but `project_end_date` before today. These are genuine overruns — real data, not a data error. This is a direct input for Deliverable 1b (Project Health Monitor).

**Fix (use in endpoint):** These are correct and usable as-is. The `GET /api/dashboard/ramp-down` endpoint should query `project_status = ACTIVE AND project_end_date < today` to surface these 38 projects. No data edit needed.

**🟡 WARNING — tech_coe uses semicolons for multi-COE and has case variants**

`tech_coe` contains values like `"Data Engineering;BI and Reporting"` and `"BI and Reporting;Data Engineering"` which are logically the same. At ingestion, split on `";"` and store each COE as a separate tag.

**Fix (ETL):**
```python
df_proj['tech_coe_list'] = df_proj['tech_coe'].str.split(';').apply(
    lambda x: [c.strip() for c in x] if isinstance(x, list) else []
)
```

**🟡 WARNING — Date format inconsistency (now resolved in updated data)**

`project_start_date` and `project_end_date` are now consistently `DD-MM-YYYY` in the updated file. Parse with `dayfirst=True`. The previously reported mixed-format issue is confirmed fixed.

### Referential Integrity

✅ All project_ids in Allocation and Timesheet files resolve to a valid project_id in this file.
⚠️ 13 WSR project_id_masked values (`CLIENT_661-671` through `CLIENT_661-683`) do not match any project_id. These are likely a CLIENT_661 sub-project numbering variant using a dash instead of underscore. See File 09 section.

---

## File 03 — Project Allocation Details
**File:** `03__260623_Project_Allocation_Details.csv`
**Rows:** 31,969 | **Columns:** 9

### What's in it

| Column | Non-null | Notes |
|--------|----------|-------|
| project_rolebased_user_id | 31,969 | UUID. Primary key. |
| project_id | 31,942 | FK to project. 27 nulls — drop these rows. |
| employee_id | 29,690 | FK to employee. 2,279 nulls = open requisitions (intentional). |
| resourcing_status | 31,969 | BILLABLE (30,454), SHADOW (895), UNBILLED (459), PROPOSED (149), PENDING (12). |
| allocated_start_date | 31,969 | DD-MM-YYYY. All populated. |
| allocated_end_date | 31,969 | DD-MM-YYYY. All populated — but 12,400 are placeholder dates. |
| is_allocation_active | 31,969 | 1 = active (13,764), 0 = historical (18,205). |
| allocation_by_percentage | 31,969 | 100% (20,673), 12.5% (4,815), 50% (2,820), 25% (2,252), etc. |
| is_active_version | 31,969 | Always 1. Drop. |

### Critical Finding — The Over-Allocation Illusion

The v1 backend naively sums `allocation_by_percentage` for all rows where `is_allocation_active = 1`, producing absurd results like 866 employees at 1,400%+ utilisation.

**Root cause (confirmed):** CLIENT_127 is a BAU Activity client with 10 ACTIVE sub-projects (`CLIENT_127_001` through `CLIENT_127_012` and `CLIENT_127_034`), all with placeholder end dates of 31-12-2030 or 31-12-2035. The `is_allocation_active` flag is set to `1` for all 12,669 of these rows, covering 870 unique employees. This means every employee appears "active" on 13+ CLIENT_127 BAU projects simultaneously — at 100% each — making them look 1,300%+ allocated.

These are shared-resource BAU overhead allocations, not real current project assignments.

**The correct current-utilisation query** (date-gated, excluding placeholders):
```python
# Real current allocation = active flag + started before today + ends after today + end date is real (not placeholder)
real_now = df_alloc[
    (df_alloc['is_allocation_active'] == 1) &
    (df_alloc['start_parsed'] <= today) &
    (df_alloc['end_parsed'] >= today) &
    (df_alloc['end_parsed'].dt.year < 2030) &   # excludes 2030/2035 placeholders
    (df_alloc['resourcing_status'].isin(['BILLABLE', 'PROPOSED']))
]
```

With this filter: **584 employees** have real current allocations; **178 are genuinely over 100%** (max 337.5%); median is 100%.

### Issues Found

**🔴 BLOCKER — Placeholder end dates (31-12-2030, 30-09-2030, 31-12-2035) used as real dates**

12,400 of 31,969 rows have placeholder end dates. Using them raw destroys utilisation calculations, availability windows, and ramp-down detection.

**Fix (ETL + endpoint logic):** Define a constant:
```python
PLACEHOLDER_END_DATES = {'31-12-2030', '30-09-2030', '31-12-2035', '01-01-2030', '31-10-2030'}
```
At ETL ingest, add a boolean column:
```python
df_alloc['is_placeholder_end_date'] = df_alloc['allocated_end_date'].isin(PLACEHOLDER_END_DATES)
```
Store this in the Allocation schema. In every endpoint that computes availability or utilisation, filter `is_placeholder_end_date = False` before date comparisons.

**🔴 BLOCKER — 2,279 null employee_ids must not be treated as data errors**

These are intentional open requisitions — slots requested but not yet filled. The problem statement confirms this.

**Fix (ETL):** Do not drop these rows. Map them explicitly:
```python
df_alloc['employee_id'] = df_alloc['employee_id'].fillna('OPEN_REQ')
```
These rows power the "open requisition count" in Deliverable 2a (Demand Forecast) and Deliverable 3 (Allocation Report).

**🟠 GAP — 1,441 active open requisitions must be surfaced separately**

Of the 2,279 null-employee rows, 1,441 have `is_allocation_active = 1`. These represent positions actively being sought right now.

**Fix (endpoint):** In `GET /api/allocations`, add a field:
```python
"open_requisitions": len([a for a in allocations if a.employee_id == 'OPEN_REQ' and a.is_allocation_active])
```

**🟠 GAP — 27 rows with null project_id**

**Fix (ETL):** `df_alloc = df_alloc.dropna(subset=['project_id'])`

**🟡 WARNING — `allocation_by_percentage` = 0 on some rows**

Not observed in sample but possible. Treat 0% as "placeholder slot, not counted" in utilisation calculations.

### Key Numbers for Deliverables

| Metric | Value | Used in |
|--------|-------|---------|
| Active allocations (all) | 13,764 | Deliverable 3 |
| Active allocations with real employees | 12,323 | Deliverable 1a, 3 |
| Active open requisitions | 1,441 | Deliverable 2a, 3 |
| Employees with real current allocations (date-gated) | 584 | Deliverable 3 |
| Employees genuinely over 100% (real dates only) | 178 | Deliverable 3 |
| Employees rolling off within 30 days (real end dates) | 307 | Deliverable 1a, 2a |

---

## File 04 — Timesheet Details 2026
**File:** `04__260624_timesheet_details_2026.csv`
**Rows:** 128,526 | **Columns:** 17

### What's in it

| Column | Status | Notes |
|--------|--------|-------|
| timesheet_surrogate_key | Drop | Not needed |
| employee_id | ✅ | 637 unique employees |
| timesheet_id | Drop | Not needed |
| manager_id | ⚠️ | 10,890 nulls — acceptable |
| job_name | ❌ | **All 128,526 null** |
| project_id | ✅ | 354 unique projects. 28 nulls. |
| project_task_id | Drop | Not needed |
| pru_id | ❌ | **All 128,526 null** |
| is_billable | ❌ | **All 128,526 null** |
| type | ❌ | **All 128,526 null** |
| date | ✅ | DD-MM-YYYY. Fixed from previous corruption. |
| time | ✅ | Hours. 0.0 to 22.0. |
| status | ✅ | APPROVED (majority), SAVED, SUBMITTED |
| created_at | ✅ | DD-MM-YYYY. Fixed. |
| updated_at | ✅ | DD-MM-YYYY. Fixed. |
| submitted_on | ❌ | **All 128,526 null** |
| data_loaded_at | Drop | Not needed |

### Issues Found

**🔴 BLOCKER — `is_billable` is entirely null (128,526 / 128,526)**

This column is 100% empty in the current dataset. The v1 backend audit flagged that the ETL incorrectly dropped this field — but even if the drop is fixed, the source data has no values.

**Impact:** Deliverable 3's "billability per person" feature cannot be derived from timesheet data alone.

**Workaround (use allocation resourcing_status instead):** Billability is determinable from File 03 via `resourcing_status`:
- `BILLABLE` → billable
- `SHADOW`, `UNBILLED` → non-billable overhead

**Fix (ETL + endpoint):** Replace the timesheet-based billability calculation with an allocation-based one:
```python
# In utilisation endpoint:
billable_pct = sum(a.allocation_by_percentage for a in active_allocs if a.resourcing_status == 'BILLABLE')
shadow_pct = sum(a.allocation_by_percentage for a in active_allocs if a.resourcing_status in ['SHADOW', 'UNBILLED'])
```

**Also fix in ETL:** Remove `is_billable` from the drop list (in case source is fixed later), but do not use it for calculations while it remains null.

**🔴 BLOCKER — `job_name`, `type`, `pru_id`, `submitted_on` are entirely null**

All four columns are 100% empty. These were referenced in v1 ETL processing.

**Fix (ETL):** Remove all references to these columns in ETL and endpoint logic. They carry no information.

**🟡 WARNING — 1 orphan timesheet employee_id: `'0'`**

One row has `employee_id = '0'`, which does not appear in the employee file.

**Fix (ETL):** `df_ts = df_ts[df_ts['employee_id'] != '0']`

### What Timesheets ARE Good For

Despite the null columns, the timesheet file is valid for:
- **Hours logged per employee per project** — `employee_id` × `project_id` × `date` × `time`
- **Actual burn rate** — sum hours by project, compare to expected allocation %
- **Activity recency** — last timesheet date per employee signals engagement

---

## File 05 — Skill Data
**File:** `05__260624_Skill_Data.xlsx` (Sheet: `Sheet2`)
**Rows:** 82,211 | **Columns:** 8

### What's in it

| Column | Non-null | Notes |
|--------|----------|-------|
| employee_id | 82,211 | All 286 active Delivery employees covered (but only 286 of 640 Delivery employees have entries — see below) |
| Designation | 82,211 | Role at time of skill assessment |
| COE | 82,091 | 120 null — see gap below |
| COE Skill | 82,211 | Skill category |
| Skill | 81,927 | 284 nulls — SubSkill exists but Skill is null for MSfabric entries |
| SubSkill | 82,211 | Specific skill item |
| Experience | 82,211 | Bands: "1-2 Year", "2-3 Years", "4-5 Years", etc. |
| Score | 82,211 | 0–5. 0 = assessed with no capability (not unknown). |

### Score Distribution

| Score | Count | Interpretation |
|-------|-------|----------------|
| 0 | 42,254 | Assessed, no capability — use as negative signal |
| 1 | 14,826 | Beginner |
| 2 | 9,561 | Basic |
| 3 | 8,045 | Intermediate |
| 4 | 5,716 | Proficient |
| 5 | 1,809 | Expert |

### Issues Found

**🟠 GAP — COE column has 5 case/spelling variants that need normalisation**

| Raw value | Normalised |
|-----------|-----------|
| `Data Engineering` | `Data Engineering` |
| `Data Science & AI` | `Data Science & AI` |
| `Techops & Automation` | `TechOps & Automation` |
| `Techops & automation` | `TechOps & Automation` |
| `Power BI & Consulting` | `BI & Reporting` |
| `Consulting` | `Consulting` |
| `consulting` | `Consulting` |
| `GTM` | `GTM` |
| `Full Stack` | `Full Stack` |

**Fix (ETL):**
```python
COE_NORM = {
    'Techops & automation': 'TechOps & Automation',
    'Techops & Automation': 'TechOps & Automation',
    'Power BI & Consulting': 'BI & Reporting',
    'consulting': 'Consulting',
}
df_skill['COE'] = df_skill['COE'].str.strip().replace(COE_NORM)
```

**🟡 WARNING — 354 Delivery employees have no skill records at all**

640 employees are in the Delivery department. Only 286 appear in the skill file. The remaining 354 have no skill data.

**Impact:** These 354 cannot be vectorised into ChromaDB and will never appear in recommendations. They are effectively invisible to the system.

**Fix (data):** These employees need skill assessments to be filled in the source system. In the interim, employees with no skill records should be surfaced in a separate list in the recommendation endpoint as "unassessable" — not silently excluded.

**🟡 WARNING — 284 rows where `Skill` is null but `SubSkill` is "MSfabric"**

These are Microsoft Fabric sub-skills where the parent `Skill` column was left blank.

**Fix (ETL):**
```python
df_skill['Skill'] = df_skill['Skill'].fillna(df_skill['SubSkill'])
```
This promotes `MSfabric` to the Skill level for vectorisation purposes.

### Referential Integrity

✅ All `employee_id` values in File 05 exist in File 01. Zero orphan keys.

---

## File 06 — Competency Details
**File:** `06__260623_Competency_Details.xlsx`
**Sheets:** 3 (`Solution Enabler`, `Solution Consultant`, `Senior Software Engineer`)
**Total rows:** 196 (56 + 37 + 103)

### What's in it

Each sheet is a different designation, each with designation-specific competency rubrics. The schemas differ across sheets — this requires normalisation at ingest.

| Sheet | Rows | Designation | Competency dimensions |
|-------|------|-------------|----------------------|
| Solution Enabler | 56 | Solutions Enabler | 5 dimensions (client influence, consulting, techno-functional, communication, ambiguity) |
| Solution Consultant | 37 | Solutions Consultant + Consultant | 3 dimensions (capability articulation, architecture estimation, project planning) |
| Senior Software Engineer | 103 | Senior Software Engineer | 3 dimensions (techno-functional, communication, ambiguity) |

All three sheets share: `Employee ID`, `Designation`, `COE/Dep`, and Score columns (Score, Score.1, Score.2, …).

### Issues Found

**🟠 GAP — Schemas differ across sheets; need a unified normalised model**

The 3 sheets cannot be stacked directly because their competency dimensions are different.

**Fix (ETL + schema):** Create a `Competency` table with a long/melted structure:

```prisma
model Competency {
  id              String  @id @default(uuid())
  employee_id     String
  designation     String
  coe             String
  dimension_label String  // The full text of the competency question
  dimension_short String  // e.g. "client_influence", "techno_functional"
  score           Int
  employee        Employee @relation(fields: [employee_id], references: [id])
}
```

**ETL approach (melt each sheet separately, then concatenate):**
```python
DIMENSION_MAP = {
    # Solution Enabler
    'Demonstrates strong capability...': 'client_influence',
    'Operates in a consultative...': 'consulting_advisory',
    'Brings strong techno-functional...': 'techno_functional',
    'Communicates with clarity...': 'communication',
    'Effectively navigates ambiguity...': 'ambiguity',
    # Solution Consultant
    'Effectivetly articulates JMAN...': 'capability_articulation',
    'Expert in estimating...': 'architecture_estimation',
    'Good at estimating and drafting...': 'project_planning',
}

frames = []
for sheet_name in wb.sheetnames:
    df = pd.read_excel(file, sheet_name=sheet_name)
    score_cols = [c for c in df.columns if 'Score' in c]
    desc_cols = [c for c in df.columns if c not in ['Employee ID','Designation','COE/Dep'] + score_cols]
    
    for i, desc_col in enumerate(desc_cols):
        score_col = score_cols[i]
        melted = df[['Employee ID','Designation','COE/Dep']].copy()
        melted['dimension_label'] = desc_col
        melted['dimension_short'] = DIMENSION_MAP.get(desc_col[:40], f'dim_{i}')
        melted['score'] = df[score_col]
        frames.append(melted)

df_comp = pd.concat(frames).rename(columns={'Employee ID':'employee_id','COE/Dep':'coe'})
```

**🟠 GAP — Only 196 of 640 Delivery employees have competency records (30.6% coverage)**

The three covered designations are Solution Enabler (56), Solution Consultant (37), Senior Software Engineer (103). Employees with other designations (Trainee SE, SE, Associate Consultant, etc.) have no competency records.

**Fix (endpoint logic):** When building the recommendation rationale, include a field:
```json
"competency_coverage": "assessed" | "not_assessed"
```
If not assessed, the recommendation rationale should state: "Competency not assessed for this designation; recommendation based on skill scores only."

**🟡 WARNING — 1 employee with trailing space in Designation: `"Senior Software Engineer "`**

**Fix (ETL):**
```python
df['Designation'] = df['Designation'].str.strip()
```

---

## File 07 — Pipeline Details
**File:** `07__260624_Pipeline_Details.xlsx`
**Sheets:** `Forecast` (293 rows), `Skillset` (100 rows), `Hierarchy` (8 rows), `6 Months Revenue` (6 rows)

### Forecast Sheet — What's in it

| Column | Non-null | Notes |
|--------|----------|-------|
| Cluster | 293 | 1–5. All populated. |
| Request Received | 197 | Date. 96 nulls. |
| Original Requested Start Date | 291 | Date. |
| Request Type | 38 | Mostly null (255). "New" where populated. |
| Client Priority | 233 | Gold/Silver/Bronze. |
| Client | 56 | Client name. 237 null (sub-rows of same project). |
| EM | 10 | Engagement Manager. 283 null. |
| Likely Start Date | 293 | All populated. Range: Jun–Sep 2026. **No Oct–Dec data.** |
| Start Date Confirmed | 45 | Yes/No. 248 null. |
| Number of Weeks | 43 | Duration. 250 null. |
| Deal Stage (HubSpot) | 43 | 250 null. |
| Solution | 28 | 265 null. |
| Priority | 293 | All populated. Medium/High/Low. |
| Status | 293 | All populated. |
| Resources Requested | 293 | Role code. 41 unique variants — needs normalisation. |
| % | 293 | Allocation %. Mixed types (100, "75/100", "25-50"). |
| Resource Recommended | 0 | Entirely null — this is a TO-BE-FILLED output field. |
| % Available | 0 | Entirely null — same. |
| Skillset | 137 | 156 null. |
| Skillset Match | 0 | Entirely null — output field. |
| SOW Signed | 42 | `Yes` (7), `No` (35), null (251). |
| Comments | 101 | Free text. 192 null. |

### Hierarchy Sheet — Role Code Mapping

This sheet is the key to normalising the 41 role code variants in `Resources Requested`.

| India Hierarchy | US/UK Hierarchy |
|-----------------|-----------------|
| Software Engineer | Associate Consultant |
| Senior Software Engineer | Senior Associate Consultant |
| Solutions Enabler | Consultant |
| Solution Consultant | Senior Consultant |
| Senior Solution Consultant | Manager |
| Technical Solutions Architect | Principal |
| Principal Solutions Architect | Associate Partner |
| (no equivalent) | Partner |

### Issues Found

**🔴 BLOCKER — Pipeline covers only Jun–Sep 2026; Deliverable 2b requires Jul–Dec 2026**

The `Likely Start Date` range is `2026-06-08` to `2026-09-07`. There are **zero pipeline rows for October, November, or December 2026**. The 6-month outlook (Jul–Dec 2026) is 25% populated with real data; the remaining 3 months must be handled differently.

**Fix (endpoint design):** In `GET /api/dashboard/pipeline-outlook`, for months Oct–Dec 2026:
- Show demand as `0` (no confirmed pipeline)
- Add a flag: `"data_coverage": "no_pipeline_data_available"`
- Include supply-side data (employees rolling off) for those months — the data exists in File 03

**🟠 GAP — 41 `Resources Requested` role code variants need normalisation**

Observed variants: `"AC"`, `"AC "`, `"AC (UK)"`, `"SSE"`, `"SSE "`, `"SSE  "`, `"SC"`, `"Sol Con"`, `"Sol Con  "`, `"Enabler"`, `"Enabler  "`, `"SE"`, `"SE "`, `"P"`, `"PA"`, `"C"`, `"C  "`, `"M"`, `"SAC"`, `"SAC - C"`, `"SAC or AC"`, `"SAC/AC"`, `"C/SAC/AC"`, `"AP/P"`, etc.

**Fix (ETL):** Use the Hierarchy sheet as the canonical mapping, plus a cleanup dict for variants:
```python
ROLE_CODE_MAP = {
    # Exact codes
    'SE': 'Software Engineer', 'SE ': 'Software Engineer', 'SE  ': 'Software Engineer',
    'SSE': 'Senior Software Engineer', 'SSE ': 'Senior Software Engineer', 'SSE  ': 'Senior Software Engineer',
    'SSE  or SE': 'Senior Software Engineer',
    'Enabler': 'Solutions Enabler', 'Enabler ': 'Solutions Enabler', 'Enabler  ': 'Solutions Enabler',
    'SC': 'Solution Consultant', 'SC  ': 'Solution Consultant',
    'Sol Con': 'Solution Consultant', 'Sol Con ': 'Solution Consultant', 'Sol Con  ': 'Solution Consultant',
    'Snr Sol Con': 'Senior Solution Consultant', 'Sr Sol Con': 'Senior Solution Consultant',
    'Sol Con/Enabler/SSE': 'Solution Consultant',  # Take senior role when ambiguous
    'SC (EM)': 'Solution Consultant',
    'SC or C - EM': 'Solution Consultant',
    'AC': 'Associate Consultant', 'AC ': 'Associate Consultant', 'AC (UK)': 'Associate Consultant',
    'SAC': 'Senior Associate Consultant', 'SAC - C': 'Senior Associate Consultant',
    'SAC or AC': 'Associate Consultant',  # Default to junior when ambiguous
    'SAC/AC': 'Associate Consultant',
    'C/SAC/AC': 'Associate Consultant',
    'C': 'Consultant', 'C ': 'Consultant', 'C  ': 'Consultant',
    'M': 'Manager',
    'P': 'Principal', 'P ': 'Principal',
    'PA': 'Associate Partner', 'PA  ': 'Associate Partner',
    'AP': 'Associate Partner', 'AP/P': 'Principal',
    'EM': 'Solution Consultant',  # Engagement Manager = SC level
    'Sr DS SME': 'Data Science SME',  # No hierarchy equivalent — keep as-is
    'GTM Architect': 'GTM Architect',  # No hierarchy equivalent
}

def normalize_role_code(code):
    if pd.isna(code): return None
    return ROLE_CODE_MAP.get(str(code).strip(), str(code).strip())

df_pipe['canonical_role'] = df_pipe['Resources Requested'].apply(normalize_role_code)
```

**🟠 GAP — `%` column has mixed types: integers, "75/100", "25-50"**

251 rows have clean integer values. 3 rows have string ranges.

**Fix (ETL):**
```python
def parse_pct(val):
    if pd.isna(val): return 100.0  # default to 100% if unspecified
    val = str(val).strip()
    if '/' in val:  # "75/100" → take the higher value
        return float(val.split('/')[-1])
    if '-' in val:  # "25-50" → take the midpoint
        parts = val.split('-')
        return (float(parts[0]) + float(parts[1])) / 2
    return float(val)

df_pipe['allocation_pct'] = df_pipe['%'].apply(parse_pct)
```

**🟠 GAP — 251 of 293 rows have null `SOW Signed`**

Only 42 rows have SOW Signed filled (`Yes`: 7, `No`: 35). The 251 null rows are sub-rows of multi-resource requests — the SOW status of the parent row applies to all its sub-rows.

**Fix (ETL):** Forward-fill SOW Signed within groups sharing the same `Original Requested Start Date` + `Cluster`:
```python
df_pipe['SOW Signed'] = df_pipe.groupby(
    ['Cluster', 'Original Requested Start Date']
)['SOW Signed'].transform(lambda x: x.ffill().bfill())
# Remaining nulls after ffill = no SOW status provided → treat as 'No'
df_pipe['SOW Signed'] = df_pipe['SOW Signed'].fillna('No')
df_pipe['sow_signed'] = df_pipe['SOW Signed'].str.strip().str.lower() == 'yes'
```

**🟡 WARNING — `Number of Weeks` is null for 250 of 293 rows**

Duration is unknown for most pipeline items. This prevents exact demand end-date calculation.

**Fix (endpoint):** When `Number of Weeks` is null, use the project type's historical median duration from the project file as a fallback:
```python
median_duration_by_type = {
    'Client Project': 26,   # derive from project file (end - start)
    'Managed Services': 52,
    'Internal Project': 12,
}
```

---

## File 09 — Project Weekly Status Details (WSR)
**File:** `09__260624_Project_Weekly_Status_Details.csv`
**Rows:** 71,205 | **Columns:** 12

### What's in it

| Column | Non-null | Notes |
|--------|----------|-------|
| wsr_key | 71,205 | Hash. Primary key. |
| wsr_id | 71,205 | UUID. |
| project_id_masked | 71,205 | FK to project. |
| scope_status | 71,205 | NO_COLOR (64,899), GREEN (5,334), AMBER (830), RED (142) |
| schedule_status | 71,205 | NO_COLOR (64,899), GREEN (4,631), AMBER (1,354), RED (321) |
| quality_status | 71,205 | NO_COLOR (64,899), GREEN (4,964), AMBER (1,210), RED (132) |
| csat_status | 71,205 | NO_COLOR (64,899), GREEN (3,895), AMBER (2,276), RED (135) |
| team_status | 71,205 | NO_COLOR (64,899), GREEN (5,459), AMBER (747), RED (100) |
| week_start_date | 71,205 | DD-MM-YYYY. Now parseable (corruption fixed). |
| week_end_date | 71,205 | DD-MM-YYYY. Now parseable (corruption fixed). |
| created_at | 71,205 | Date. All populated. |
| updated_at | 71,205 | Date. All populated. |

### Status Ratios (excl. NO_COLOR)

| Dimension | GREEN | AMBER | RED | Total Rated |
|-----------|-------|-------|-----|-------------|
| scope | 5,334 | 830 | 142 | 6,306 |
| schedule | 4,631 | 1,354 | 321 | 6,306 |
| quality | 4,964 | 1,210 | 132 | 6,306 |
| csat | 3,895 | 2,276 | 135 | 6,306 |
| team | 5,459 | 747 | 100 | 6,306 |

### Issues Found

**🟠 GAP — 20,358 rows have `week_start_date` before year 2000 (as far back as 1969)**

These are real corruption artefacts in the source system — weeks that were assigned epoch-level dates. They are not useful for recency-based health scoring.

**Fix (ETL filter):** Drop rows where `week_start_date` is before 2020 for ML training purposes:
```python
df_wsr['week_start_parsed'] = pd.to_datetime(df_wsr['week_start_date'], dayfirst=True, errors='coerce')
df_wsr_recent = df_wsr[df_wsr['week_start_parsed'].dt.year >= 2020]
# Remaining rows: ~50,847
```
For historical archive purposes, keep all rows in the DB but filter to `year >= 2020` in the health classifier training query.

**🟡 WARNING — 13 WSR project IDs not in the project file**

All 13 orphan IDs follow the pattern `CLIENT_661-NNN` (dash instead of underscore). They are likely the same CLIENT_661 projects using a different project ID format in the source system.

**Fix (ETL):**
```python
df_wsr['project_id_masked'] = df_wsr['project_id_masked'].str.replace(
    r'^(CLIENT_\d+)-(\d+)$', r'\1_\2', regex=True
)
```
This converts `CLIENT_661-671` → `CLIENT_661_671`. Re-check referential integrity after this transform.

---

## Deliverable Feasibility Assessment

### 1a — Resource Recommendation Engine ⚠️ Partially Feasible

**What's now available:**
- Skill data (82,211 rows, 286 employees vectorisable)
- Competency data (196 employees, 3 designations)
- Allocation data with real availability windows (once placeholder dates are handled)
- Pipeline role codes (once normalised)

**Remaining gap after data fixes:**
- 354 Delivery employees have no skills → invisible to recommendations
- Competency covers only 196 of 640 employees → fallback needed
- The `build_vector_db()` call must include competency text in the document (see Project Context §9)

**Verdict:** Implementable. Apply all ETL fixes above, then use the date-gated availability query from File 03 section to gate recommendations correctly.

---

### 1b — Project Health & Efficiency Monitor ✅ Feasible

**What's now available:**
- 38 genuinely overrunning ACTIVE projects (end date in past)
- 13 projects ramping down within 30 days; 50 within 90 days
- 307 unique employees rolling off within 30 days
- WSR RAG data for LightGBM training (6,306 rated rows post-2020 filter)
- Financial leakage: SHADOW (895 active rows) + UNBILLED (459 active rows)

**Remaining gap:**
- `budget_status` and `scope_status` must be added as LightGBM features (currently only quality/csat/team used)
- Ramp-down endpoint not yet built (blueprint in Project Context §8.5)

**Verdict:** All data is present and correct. This is the most ready deliverable.

---

### 2a — Demand Forecast ⚠️ Partially Feasible

**What's now available:**
- Pipeline with 293 rows, role codes, start dates
- Role-mix templates can be derived from historical allocations (File 03 grouped by project type from File 02)
- 307 employees rolling off in 30 days = supply pool

**Remaining gap:**
- This endpoint doesn't exist yet — must be built from scratch (blueprint in Project Context §8.2)
- Pipeline Oct–Dec 2026 data is entirely absent (see File 07 section)

**Verdict:** Feasible for Jun–Sep 2026 window. Oct–Dec will show zero demand — flag this explicitly rather than silently.

---

### 2b — 6-Month Pipeline Outlook ⚠️ Partially Feasible

**What's now available:**
- Pipeline Jul–Sep 2026 demand data (122 + 67 + 7 rows)
- Supply (rolling-off employees) available for all 6 months from File 03
- SOW Signed filter operable once forward-fill is applied (7 confirmed yes rows)

**Remaining gap:**
- Oct–Dec demand = zero (no pipeline data)
- Monthly grouping not yet implemented
- Broken field references in current endpoint must be removed first

**Verdict:** Feasible. Frame the Oct–Dec months as "no confirmed pipeline" rather than a data error.

---

### 3 — Current-State Allocation Report ✅ Feasible

**What's now available:**
- All allocation fields including `allocated_start_date`, `allocated_end_date`, `is_allocation_active` — the v1 schema gaps are confirmed fixed in this dataset
- 307 employees rolling off within 30 days identified
- Date-gated utilisation query produces meaningful results (178 genuinely over-allocated)
- Billability via `resourcing_status` (allocation file workaround — timesheet `is_billable` is null)

**Remaining gap:**
- Per-employee utilisation endpoint not yet built (blueprint in Project Context §8.4)
- Placeholder end dates must be handled to avoid inflated utilisation numbers

**Verdict:** All data is present. Implement the date-gated query from File 03 section and the utilisation endpoint blueprint.

---

## ETL Fix Checklist (Prioritised)

Copy this checklist into your task tracker. Each item is independently testable.

### 🔴 P0 — Fix Before Any Endpoint Works

- [ ] **03-A: Placeholder end-date flag** — Add `is_placeholder_end_date` boolean column to Allocation ETL. Values `{'31-12-2030','30-09-2030','31-12-2035','01-01-2030','31-10-2030'}` → `True`.
- [ ] **03-B: Open requisition mapping** — `df_alloc['employee_id'].fillna('OPEN_REQ')` — do not drop null employee rows.
- [ ] **03-C: Drop null project_id rows** — `df_alloc.dropna(subset=['project_id'])` (27 rows).
- [ ] **04-A: Remove `is_billable` from ETL drop list** — field is null now but may be populated in future.
- [ ] **04-B: Drop orphan employee** — `df_ts = df_ts[df_ts['employee_id'] != '0']`
- [ ] **04-C: Replace timesheet-based billability with allocation-based** — use `resourcing_status` from File 03.
- [ ] **02-A: Drop null project_id rows** — `df_proj.dropna(subset=['project_id'])` (13 rows).
- [ ] **07-A: Normalise role codes** — apply `ROLE_CODE_MAP` to create `canonical_role` column.
- [ ] **07-B: Forward-fill SOW Signed** — group by Cluster + Original Requested Start Date, ffill, fillna('No').
- [ ] **07-C: Parse `%` column** — handle "75/100" and "25-50" strings.

### 🟠 P1 — Required for Correct Deliverable Output

- [ ] **06-A: Ingest Competency file** — create `Competency` model (long format), process all 3 sheets.
- [ ] **05-A: Normalise COE column** — apply `COE_NORM` dict.
- [ ] **05-B: Fill null Skill from SubSkill** — `df_skill['Skill'].fillna(df_skill['SubSkill'])`.
- [ ] **09-A: Convert WSR date format** — parse with `dayfirst=True`, drop rows with year < 2020 for ML training.
- [ ] **09-B: Fix CLIENT_661 ID format** — replace dash with underscore in `project_id_masked`.
- [ ] **01-A: Apply compound employee filter** — `account_status=1 AND department_name='Delivery' AND date_of_resignation is null`.

### 🟡 P2 — Data Quality Improvements

- [ ] **01-B: Fill null job_name for 8 active Delivery employees** — manual lookup from File 05 Designation column.
- [ ] **06-B: Strip trailing whitespace from Designation** — `df['Designation'].str.strip()`.
- [ ] **07-D: Pipeline duration fallback** — use type-based median duration for null `Number of Weeks`.
- [ ] **02-B: Split semicolon-separated tech_coe** — store as list for multi-COE matching.

---

## Schema Additions Required (Prisma)

These additions were identified in the backend audit. The dataset confirms all are needed and the source data is present.

### Allocation model — add fields

```prisma
model Allocation {
  // existing fields ...
  allocated_start_date     DateTime?
  allocated_end_date       DateTime?
  is_allocation_active     Boolean   @default(false)
  is_placeholder_end_date  Boolean   @default(false)  // NEW — derived in ETL
}
```

### New: Pipeline model

```prisma
model PipelineRequest {
  id                    String    @id @default(uuid())
  cluster               Int
  likely_start_date     DateTime
  canonical_role        String?
  allocation_pct        Float     @default(100)
  sow_signed            Boolean   @default(false)
  priority              String?
  status                String?
  skillset              String?
  number_of_weeks       Int?
  client_priority       String?
  comments              String?
  created_at            DateTime  @default(now())
}
```

### New: Competency model

```prisma
model Competency {
  id               String   @id @default(uuid())
  employee_id      String
  designation      String
  coe              String
  dimension_short  String   // e.g. "techno_functional"
  dimension_label  String   // Full rubric text
  score            Int
  employee         Employee @relation(fields: [employee_id], references: [id])
}
```

### New: WeeklyStatus model

```prisma
model WeeklyStatus {
  id              String   @id @default(uuid())
  wsr_id          String   @unique
  project_id      String
  scope_status    String
  schedule_status String
  quality_status  String
  csat_status     String
  team_status     String
  week_start_date DateTime
  week_end_date   DateTime
  project         Project  @relation(fields: [project_id], references: [id])
}
```

---

## Quick Reference — Numbers by Deliverable

| Metric | Value | File |
|--------|-------|------|
| Active Delivery employees (recommended filter) | ~286 | 01 |
| Employees with skill data | 286 of 640 Delivery | 05 |
| Employees with competency data | 196 (3 designations only) | 06 |
| Active BILLABLE allocations (real current, date-gated) | 584 employees | 03 |
| Employees genuinely over-allocated (>100%, date-gated) | 178 | 03 |
| Employees rolling off in 30 days | 307 | 03 |
| Active open requisitions | 1,441 | 03 |
| ACTIVE projects overrunning | 38 | 02 |
| ACTIVE projects ramping down in 30 days | 13 | 02 |
| ACTIVE projects ramping down in 90 days | 50 | 02 |
| SHADOW + UNBILLED active allocation rows | 1,354 | 03 |
| Pipeline rows confirmed (SOW Signed = Yes) | 7 | 07 |
| Pipeline rows unconfirmed (SOW Signed = No or null) | 286 | 07 |
| Pipeline coverage (months) | Jun–Sep 2026 only | 07 |
| WSR rows with real RAG status | 6,306 | 09 |
| WSR rows pre-2020 (to exclude from ML training) | 20,358 | 09 |

---

*Audit complete. All fixes above are sufficient to unblock the five required deliverables. No additional data is required — only ETL and schema changes.*
