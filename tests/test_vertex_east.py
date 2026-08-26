from google import genai
import os

for region in ["us-east4", "us-east1", "us-west1", "europe-west1"]:
    try:
        client = genai.Client(
            vertexai=True,
            project="ztm-agent-9049c3",
            location=region
        )
        response = client.models.generate_content(
            model='gemini-3.5-flash',
            contents='test'
        )
        print(f"Success in {region}: {response.text}")
        break
    except Exception as e:
        print(f"Failed in {region}: {e}")
