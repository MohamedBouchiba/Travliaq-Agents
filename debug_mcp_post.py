import requests
import threading
import time
import json

url = "https://travliaq-mcp-production.up.railway.app/mcp"

def listen_sse(session_id):
    print(f"Starting SSE listener for session {session_id}")
    headers = {
        "Accept": "text/event-stream",
        "Mcp-Session-Id": session_id
    }
    try:
        with requests.get(url, headers=headers, stream=True) as response:
            print(f"SSE Status: {response.status_code}")
            for line in response.iter_lines():
                if line:
                    print(f"SSE Received: {line}")
    except Exception as e:
        print(f"SSE Error: {e}")

# 1. Get Session ID
print("Getting Session ID...")
resp = requests.get(url, headers={"Accept": "text/event-stream"})
session_id = resp.headers.get("Mcp-Session-Id")

if not session_id:
    print("Failed to get session ID")
    exit(1)

print(f"Got Session ID: {session_id}")

# 2. Start listener
t = threading.Thread(target=listen_sse, args=(session_id,))
t.daemon = True
t.start()

# 3. Wait a bit
time.sleep(2)

endpoints = [
    f"{url}/messages?sessionId={session_id}",
    f"{url.replace('/mcp', '')}/messages?sessionId={session_id}",
    f"{url}?sessionId={session_id}",  # POST to same URL?
]

for post_url in endpoints:
    print(f"Trying POST to {post_url}")
    try:
        resp = requests.post(post_url, json=payload)
        print(f"POST Status: {resp.status_code}")
        if resp.status_code != 404:
            print(f"POST Response: {resp.text}")
            break
    except Exception as e:
        print(f"POST Error: {e}")

# Wait to see if we get a response on SSE
time.sleep(5)
