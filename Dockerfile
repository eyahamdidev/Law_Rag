FROM python:3.12-slim

WORKDIR /app

COPY requirements-legal.txt .
RUN pip install --no-cache-dir -r requirements-legal.txt

COPY backend ./backend
COPY frontend ./frontend
COPY law ./law
COPY grants_and_financial_aids ./grants_and_financial_aids
RUN mkdir -p fraud_detection business_plan data

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--app-dir", "backend"]
