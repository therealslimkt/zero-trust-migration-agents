import re

class PIIRedactor:
    def __init__(self):
        # Regex for SSN (XXX-XX-XXXX or XXXXXXXXX)
        self.ssn_pattern = re.compile(r'\b\d{3}-\d{2}-\d{4}\b|\b\d{9}\b')
        # Regex for email
        self.email_pattern = re.compile(r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b')

    def redact(self, text: str) -> str:
        """Simulates Gemma SLM intercepting text stream and redacting PII."""
        # Redact SSN
        redacted_text = self.ssn_pattern.sub('[REDACTED_SSN]', text)
        # Redact Email
        redacted_text = self.email_pattern.sub('[REDACTED_EMAIL]', redacted_text)
        
        return redacted_text

if __name__ == "__main__":
    redactor = PIIRedactor()
    sample_text = "User John Doe has SSN 123-45-6789 and email john.doe@example.com."
    print("Original:", sample_text)
    print("Redacted:", redactor.redact(sample_text))
