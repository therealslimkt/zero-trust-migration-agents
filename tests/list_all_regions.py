from google import genai
import os

for region in ["us-central1", "us-east4", "us-east1", "us-west1", "europe-west1", "europe-west4", "asia-southeast1"]:
    print(f"--- {region} ---")
    try:
        client = genai.Client(vertexai=True, project="ztm-agent-9049c3", location=region)
        for m in client.models.list():
            if "3.5" in m.name or "3." in m.name:
                print(m.name)
    except Exception as e:
        print(f"Failed: {e}")
