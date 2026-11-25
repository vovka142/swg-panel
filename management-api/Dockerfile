FROM python:3.12-slim
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY main.py .
EXPOSE 8090
CMD ["sh", "-c", "uvicorn main:app --host \"${GATEWAY_HOST:-0.0.0.0}\" --port \"${GATEWAY_PORT:-8090}\""]
