FROM python:3.11-slim

# UTF-8 no container: sem isso o locale cai em ASCII e qualquer acento / "…" / "←"
# quebra (relatório da IA, e-mail, WhatsApp). PYTHONUTF8=1 força o modo UTF-8 do Python.
ENV PYTHONUTF8=1 \
    PYTHONUNBUFFERED=1 \
    LANG=C.UTF-8 \
    LC_ALL=C.UTF-8

WORKDIR /app

RUN apt-get update && apt-get install -y \
    gcc postgresql-client \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8000

# Produção: sem --reload
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
