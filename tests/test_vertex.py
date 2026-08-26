from google import genai
import os

client = genai.Client(
    vertexai=True,
    project="ztm-agent-9049c3",
    location="us-central1"
)
try:
    for m in client.models.list():
        if "gemini" in m.name:
            print(m.name)
except Exception as e:
    print(f"Error: {e}")
