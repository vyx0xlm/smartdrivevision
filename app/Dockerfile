FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir flask flask-cors flask-login python-dotenv firebase-admin gunicorn

COPY . .

ENV PORT=8080
ENV BEHIND_PROXY=1
ENV FLASK_DEBUG=0

EXPOSE 8080

CMD python -c "from app import init_db; init_db()" && gunicorn --bind 0.0.0.0:${PORT} --workers 1 --threads 4 --timeout 120 app:app
