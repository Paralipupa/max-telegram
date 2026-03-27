FROM python:3.11-slim

ARG ENVIRONMENT="production"

WORKDIR /app

RUN pip install playwright==1.58.0 --no-cache-dir && playwright install chromium

COPY requirements.txt .

RUN pip install --no-cache-dir -r requirements.txt

RUN apt-get update && apt-get install -y wget libnss3 \
    libatk1.0-0 libatk-bridge2.0-0 libcups2 libdrm2 libxkbcommon0 libxcomposite1 \
    libxdamage1 libxfixes3 libxrandr2 libgbm1 libasound2 libpangocairo-1.0-0 \
    libpango-1.0-0 libcairo2 libatspi2.0-0 libxshmfence1 && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

RUN if [ "$ENVIRONMENT" = "development" ]; then pip install debugpy; fi

COPY entrypoint.sh .
COPY app/ .
RUN chmod +x /app/entrypoint.sh

EXPOSE 8081

ENTRYPOINT ["/app/entrypoint.sh"]
