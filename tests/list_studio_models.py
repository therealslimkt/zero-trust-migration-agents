from google import genai
import os

client = genai.Client()
try:
    models = client.models.list()
    found = False
    for m in models:
        if "3.5" in m.name or "3." in m.name:
            print(m.name)
            found = True
    if not found:
        print("No 3.x models found in AI Studio.")
except Exception as e:
    print(f"Error: {e}")
