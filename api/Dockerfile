FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/workspace

WORKDIR /workspace
COPY api/requirements.txt /workspace/api/requirements.txt
RUN pip install --no-cache-dir -r /workspace/api/requirements.txt
COPY api /workspace/api
COPY worker /workspace/worker
COPY labs /workspace/labs

EXPOSE 8000
CMD ["uvicorn", "api.app.main:app", "--host", "0.0.0.0", "--port", "8000"]
