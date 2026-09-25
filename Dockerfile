FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# БД живёт в /app/data — монтируй volume, чтобы не потерять профили и опыт
RUN mkdir -p /app/data

EXPOSE 3000

CMD ["python", "main.py"]
