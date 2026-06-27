import pandas as pd, os, sys

CLEANED_DIR = "../data/cleaned"
files = {
    "02_projects": "02_projects_clean.csv",
    "03_alloc": "03_allocations_clean.csv", 
    "05_skills": "05_skills_clean.csv",
    "09_wsr": "09_wsr_clean.csv",
}

for label, fname in files.items():
    path = os.path.join(CLEANED_DIR, fname)
    if os.path.exists(path):
        df = pd.read_csv(path, nrows=2, encoding="latin1")
        print(f"\n=== {label} ({fname}) ===")
        print(f"Columns: {list(df.columns)}")
        print(df.head(1).to_string())
    else:
        print(f"\n=== {label} NOT FOUND at {path} ===")
