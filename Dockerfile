FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt
# Amazon Jobs crawling uses Crawl4AI's Playwright browser at runtime.
RUN playwright install --with-deps chromium
COPY . .
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
