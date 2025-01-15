import requests

# Your Railway URL
url = "https://jim-production.up.railway.app"

# API Key setup
headers = {
    "Authorization": "Bearer jeremy"
}

# Test crawl - note the "urls" field instead of "url"
response = requests.post(
    f"{url}/crawl",
    headers=headers,
    json={
        "urls": "https://example.com",  # Changed from url to urls
        "priority": 10
    }
)
print(response.json())

# Get task status if we get a task_id
if "task_id" in response.json():
    task_id = response.json()["task_id"]
    status_response = requests.get(
        f"{url}/task/{task_id}",
        headers=headers
    )
    print("Task status:", status_response.json())