
FROM python:3.11-slim
WORKDIR /app

COPY app /app/app
RUN pip install --no-cache-dir -r /app/app/requirements.txt
RUN pip install playwright && playwright install chromium

CMD ["python","/app/app/runner.py"]
