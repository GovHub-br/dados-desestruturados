FROM python:3.11-slim

WORKDIR /app
COPY portal/requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt
COPY portal /app/portal

ENV PYTHONUNBUFFERED=1
EXPOSE 8000
CMD ["uvicorn", "portal.app:app", "--host", "0.0.0.0", "--port", "8000"]
