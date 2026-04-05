FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
# Entry point: runs server.py (webhook + scheduler, no interactive CLI)
ENTRYPOINT ["python", "-u", "server.py"]
