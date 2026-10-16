FROM python:3.11-slim

WORKDIR /app
COPY services/aid/requirements.lock /app/requirements.lock
RUN pip install --no-cache-dir -r /app/requirements.lock
COPY backend /app/backend
COPY services/aid /app/services/aid
COPY grants_and_financial_aids /app/grants_and_financial_aids
COPY law /app/law

ENV PYTHONPATH=/app/backend
EXPOSE 8103
CMD ["uvicorn", "services.aid.app:app", "--host", "0.0.0.0", "--port", "8103"]
