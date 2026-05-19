import requests

BASE_URL = "http://127.0.0.1:8000"

print("=== Seeding database ===")


print("Registering users...")
requests.post(f"{BASE_URL}/register", json={"username": "alice", "password": "alice-secret"})
requests.post(f"{BASE_URL}/register", json={"username": "bob", "password": "bob-secret"})


print("Logging in alice...")
response = requests.post(f"{BASE_URL}/login", json={"username": "alice", "password": "alice-secret"})
if response.status_code == 200:
    token = response.json().get("access_token")
    

    print("Sending seed message...")
    requests.post(
        f"{BASE_URL}/messages",
        headers={"Authorization": f"Bearer {token}"},
        json={"recipients": ["bob"], "content": "Hey Bob, the server is up!"}
    )

print("Done! Database is seeded.")