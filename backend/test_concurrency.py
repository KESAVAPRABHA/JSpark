import threading
import requests
import time

def fire_allocation_request(manager_name):
    url = "http://localhost:8000/api/allocate"
    payload = {
        "employee_id": "NINJA_TEST_EMP",       # Using a test employee ID
        "project_id": "NINJA_PROJECT",    # Using a test project ID
        "percentage": 50
    }
    
    print(f"[{manager_name}] Firing request...")
    
    # Record start time to prove they fire simultaneously
    start_time = time.time()
    response = requests.post(url, json=payload)
    end_time = time.time()
    
    # Print the result
    if response.status_code == 200:
        print(f"✅ [{manager_name}] SUCCESS! Acquired lock and allocated resource in {end_time - start_time:.4f}s.")
    elif response.status_code == 409:
        print(f"🛑 [{manager_name}] BLOCKED! Hit 409 Conflict (Lock already held).")
    else:
        print(f"⚠️ [{manager_name}] Failed with status {response.status_code}: {response.text}")

if __name__ == "__main__":
    print("--- STARTING CONCURRENCY RACE CONDITION TEST ---")
    
    # We will simulate 3 Resource Managers trying to allocate EMP999 simultaneously
    managers = ["Manager Alice", "Manager Bob", "Manager Charlie"]
    threads = []
    
    # Initialize threads
    for manager in managers:
        t = threading.Thread(target=fire_allocation_request, args=(manager,))
        threads.append(t)
        
    # Start all threads at the exact same time
    for t in threads:
        t.start()
        
    # Wait for all threads to finish
    for t in threads:
        t.join()
        
    print("--- TEST COMPLETE ---")