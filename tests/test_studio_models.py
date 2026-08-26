"""Manual Gemini model-list probe; never runs during test collection."""

from google import genai


def main() -> None:
    client = genai.Client(http_options={"api_version": "v1alpha"})
    try:
        for model in client.models.list():
            if "3.5" in model.name or "3." in model.name:
                print(model.name)
    except Exception as exc:
        print(f"Error: {exc}")


if __name__ == "__main__":
    main()
