"""Manual Gemini model-access probe; never runs during test collection."""

from google import genai


def main() -> None:
    client = genai.Client()
    try:
        response = client.models.generate_content(
            model="gemini-3.1-pro-preview",
            contents="test",
        )
        print("Success with 3.1-pro-preview:", response.text)
    except Exception as exc:
        print(f"Error testing 3.1-pro-preview: {exc}")


if __name__ == "__main__":
    main()
