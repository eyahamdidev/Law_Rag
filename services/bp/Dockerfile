FROM python:3.11-slim
WORKDIR /srv
COPY requirements.lock .
RUN pip install --no-cache-dir -r requirements.lock
COPY app ./app
COPY eval ./eval
COPY templates ./templates
COPY guidance ./guidance
COPY prompts ./prompts
COPY mock ./mock
ENV UPLOADS_DIR=/data/uploads PYTHONUNBUFFERED=1
EXPOSE 8104
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8104"]
