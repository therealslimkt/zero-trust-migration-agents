FROM python:3.11-slim

WORKDIR /app

COPY . /app

# Mock dependency install for Antigravity
RUN pip install --no-cache-dir google-antigravity || echo "Skipping missing deps"

CMD ["python", "main.py"]
