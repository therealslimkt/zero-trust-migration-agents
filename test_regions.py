import sys
from google import genai


def main() -> int:
    regions = [
        "us-central1",
        "us-east1",
        "us-east4",
        "us-east5",
        "us-west1",
        "us-west4",
        "europe-west1",
        "europe-west4",
        "europe-west9",
        "asia-northeast1",
    ]
    for region in regions:
        try:
            client = genai.Client(
                vertexai=True,
                location=region,
                project="ztm-agent-9049c3",
            )
            client.models.generate_content(model="gemini-3.5-flash", contents="hi")
            print(f"SUCCESS in {region}")
            return 0
        except Exception as exc:
            print(f"Failed in {region}: {str(exc)[:100]}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
