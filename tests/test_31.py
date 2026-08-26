from google import genai
import os

client = genai.Client(vertexai=True, project="ztm-agent-9049c3", location="us-central1")
try:
    response = client.models.generate_content(
        model="gemini-3.1-pro-preview",
        contents="test"
    )
    print("Success with 3.1-pro-preview:", response.text)
except Exception as e:
    print(f"Error testing 3.1-pro-preview: {e}")
