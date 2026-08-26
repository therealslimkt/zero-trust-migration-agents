from google import genai
import os

client = genai.Client(vertexai=True, project="ztm-agent-9049c3", location="us-central1")
try:
    response = client.models.generate_content(
        model="gemini-2.5-pro",
        contents="test"
    )
    print("Success with 2.5-pro:", response.text)
except Exception as e:
    print(f"Error testing 2.5-pro: {e}")
