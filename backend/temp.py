import chromadb

# Connect to your local ChromaDB
chroma_client = chromadb.PersistentClient(path="./chroma_db")
collection = chroma_client.get_collection(name="employee_skills")

# Fetch the specific document for EMP241
emp_id = "EMP241"
result = collection.get(ids=[emp_id])

if result and result["documents"]:
    print(f"\n--- Document stored in ChromaDB for {emp_id} ---")
    print(result["documents"][0])
    
    print(f"\n--- Metadata stored in ChromaDB for {emp_id} ---")
    print(result["metadatas"][0])
else:
    print(f"Employee {emp_id} not found in ChromaDB.")