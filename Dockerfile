FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY incident_intent ./incident_intent
COPY app.py .
COPY static ./static

RUN mkdir -p /app/temp/caseone /app/temp/incidents

ENV PORT=8090
ENV POC_TEMP_DIR=/app/temp
ENV OLLAMA_BASE_URL=http://tsrag-ollama:11434
ENV OLLAMA_MODEL=llama3.1:8b-instruct-q6_K

EXPOSE 8090

CMD ["python", "-m", "uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8090"]
