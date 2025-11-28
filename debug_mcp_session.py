import requests
import uuid

url = "https://travliaq-mcp-production.up.railway.app/mcp"
headers = {"Accept": "text/event-stream"}

print(f"1. Initial request to {url}")
try:
    response = requests.get(url, headers=headers)
    print(f"Status: {response.status_code}")
    print(f"Headers: {response.headers}")
    print(f"Content: {response.text}")
    
    session_id = response.headers.get("Mcp-Session-Id")
    if session_id:
        print(f"\nGot Session ID: {session_id}")
        
        print(f"2. Retry with Session ID in header")
        headers["Mcp-Session-Id"] = session_id
        response2 = requests.get(url, headers=headers, stream=True)
        print(f"Status: {response2.status_code}")
        print(f"Headers: {response2.headers}")
        # Read a bit of the stream if successful
        if response2.status_code == 200:
            print("Stream opened!")
            for i, line in enumerate(response2.iter_lines()):
                if line:
                    print(f"Line {i}: {line}")
                if i > 10:
                    break
        else:
            print(f"Content: {response2.text}")
            
        print(f"\n3. Retry with Session ID in query param")
        url_with_param = f"{url}?sessionId={session_id}"
        response3 = requests.get(url_with_param, headers={"Accept": "text/event-stream"}, stream=True)
        print(f"Status: {response3.status_code}")
        print(f"Headers: {response3.headers}")
        if response3.status_code == 200:
            print("Stream opened!")
    else:
        print("No Session ID returned")

except Exception as e:
    print(f"Error: {e}")
