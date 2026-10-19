FROM python:3.13-slim
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    WEDECIDE_DATA_DIR=/app/data \
    WEDECIDE_HOST=0.0.0.0 \
    WEDECIDE_PORT=8000
WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt \
    && groupadd --gid 10001 wedecide \
    && useradd --uid 10001 --gid wedecide --no-create-home wedecide \
    && mkdir /app/data \
    && chown wedecide:wedecide /app/data
COPY wedecide ./wedecide
COPY web ./web
USER wedecide
EXPOSE 8000
CMD ["python", "-m", "wedecide.cli", "serve"]
