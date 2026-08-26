import sys
from google import genai
regions = ['us-central1', 'us-east1', 'us-east4', 'us-east5', 'us-west1', 'us-west4', 'europe-west1', 'europe-west4', 'europe-west9', 'asia-northeast1']
for r in regions:
    try:
        client = genai.Client(vertexai=True, location=r, project='ztm-agent-9049c3')
        resp = client.models.generate_content(model='gemini-3.5-flash', contents='hi')
        print(f"SUCCESS in {r}")
        sys.exit(0)
    except Exception as e:
        print(f"Failed in {r}: {str(e)[:100]}")
