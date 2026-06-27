import chromadb
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.prompts import PromptTemplate
import os
from prisma import Prisma

# Ensure GOOGLE_API_KEY is in your .env
llm = ChatGoogleGenerativeAI(model="gemini-2.5-flash-lite", temperature=0.0)
chroma_client = chromadb.PersistentClient(path="./chroma_db")

# 🚨 THE FIX: Force Cosine Distance instead of default L2
try:
    # We attempt to create it with the strict cosine metadata
    collection = chroma_client.get_or_create_collection(
    name="employee_skills",
    metadata={"hnsw:space": "cosine"}
)
except chromadb.errors.UniqueConstraintError:
    # If it exists, get it. (Note: If you previously built this without cosine, 
    # you MUST delete the chroma_db folder on your hard drive before running this!)
    collection = chroma_client.get_collection(name="employee_skills")

async def build_vector_db():
    db = Prisma()
    await db.connect()
    
    employees = await db.employee.find_many(include={'skills': True})
    
    docs = []
    metadatas = []
    ids = []

    for emp in employees:
        skill_str = ""
        for s in emp.skills:
            if s.score == 0:
                skill_str += f"Lacks capability in {s.skill_name}. " # Negative weighting
            else:
                skill_str += f"Proficient in {s.skill_name} (Score: {s.score}). "
        
        if skill_str:
            docs.append(skill_str)
            metadatas.append({"employee_id": emp.id, "designation": emp.designation})
            ids.append(emp.id)

    if docs:
        collection.upsert(documents=docs, metadatas=metadatas, ids=ids)
    
    print("✅ Vector Database built using Cosine Distance Space.")
    await db.disconnect()
    
def recommend_resource(project_requirements, required_role):
    # Hard constraint: Check role match in metadata
    results = collection.query(
        query_texts=[project_requirements],
        n_results=3,
        where={"designation": required_role}
    )

    if not results['ids'][0]:
        return {"status": "NO_MATCH_FOUND", "signal": "Initiate Hire", "reason": "No employees found with the required role."}

    top_match_id = results['ids'][0][0]
    distance = results['distances'][0][0]

    # 🚨 THE FIX: Scientifically bounded Cosine Threshold
    # In ChromaDB cosine space: 0.0 is perfect, 1.0 is orthogonal. 
    # A distance > 0.35 means they share less than 65% semantic similarity.
    COSINE_THRESHOLD = 0.35 

    if distance > COSINE_THRESHOLD:
        return {
            "status": "NO_MATCH_FOUND", 
            "signal": "Initiate Hire", 
            "reason": f"Semantic drift detected. Closest match cosine distance ({distance:.3f}) exceeds strict threshold ({COSINE_THRESHOLD})."
        }

    prompt = PromptTemplate(
        input_variables=["emp_id", "skills", "reqs"],
        template="""
        You are a Resourcing Matchmaker. Write exactly 3 concise bullet points defending why {emp_id} is the best match for the project.
        Project Requirements: {reqs}
        Employee Profile: {skills}
        Do not use introductory sentences.
        """
    )
    
    rationale = llm.invoke(prompt.format(emp_id=top_match_id, skills=results['documents'][0][0], reqs=project_requirements))
    
    return {
        "status": "MATCH_FOUND",
        "employee_id": top_match_id,
        "cosine_distance": round(float(distance), 3),
        "rationale": rationale.content.strip()
    }