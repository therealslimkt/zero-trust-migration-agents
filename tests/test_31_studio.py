from google import genai
import os

client = genai.Client()
try:
    response = client.models.generate_content(
        model="gemini-3.1-pro-preview",
        contents="test"
    )
    print("Success with 3.1-pro-preview:", response.text)
except Exception as e:
    print(f"Error testing 3.1-pro-preview: {e}")
