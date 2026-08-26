from google import genai
import os

client = genai.Client(
    vertexai=True,
    project="ztm-agent-9049c3",
    location="us-central1"
)
models_to_test = [
    "gemini-1.5-pro",
    "gemini-1.5-pro-002",
    "gemini-2.5-flash",
    "gemini-3.5-flash"
]
for model in models_to_test:
    try:
        response = client.models.generate_content(
            model=model,
            contents='test'
        )
        print(f"Success with {model}: {response.text}")
    except Exception as e:
        print(f"Failed with {model}: {e}")
