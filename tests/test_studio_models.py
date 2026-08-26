from google import genai
import os

client = genai.Client(http_options={'api_version': 'v1alpha'})
try:
    for m in client.models.list():
        if "3.5" in m.name or "3." in m.name:
            print(m.name)
except Exception as e:
    print(f"Error: {e}")
