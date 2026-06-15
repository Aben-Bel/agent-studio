FROM python:3.11-slim
WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8000

# MOCK_LLM defaults to 1 (offline mock, no AWS calls).
# Set MOCK_LLM=0 plus AWS creds in .env to use real Bedrock.
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
