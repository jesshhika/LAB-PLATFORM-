FROM python:3.11-slim

WORKDIR /app
COPY ops/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt
COPY ops/reap_vms.py ./reap_vms.py

ENTRYPOINT ["python", "/app/reap_vms.py"]
