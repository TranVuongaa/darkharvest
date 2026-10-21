FROM python:3.11-slim
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 \
    ARTICLES_DIR=/app/articles \
    LIMIT="" TIKTOKEN_CACHE_DIR=/opt/tiktoken
WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt && \
    python -c "import tiktoken; tiktoken.get_encoding('cl100k_base')" && \
    chmod -R a+rX /opt/tiktoken && useradd --uid 10001 --create-home job && chown job:job /app
COPY main.py scrape.py upload_knowledge.py ./
COPY src/ ./src/
USER job
CMD ["python", "main.py"]
