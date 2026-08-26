from google import genai
import os

client = genai.Client(vertexai=True, project="ztm-agent-9049c3", location="us-central1")
try:
    models = []
    for m in client.models.list():
        if "3." in m.name:
            models.append(m.name)
    print("Found 3.x models:", models)
    
    # Try inference with 3.5-pro
    response = client.models.generate_content(
        model="gemini-3.5-pro",
        contents="test"
    )
    print("Success with gemini-3.5-pro:", response.text)
except Exception as e:
    print(f"Error testing 3.5-pro: {e}")
