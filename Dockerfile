FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    APP_ENV=production

WORKDIR /app

# Instalar dependências de sistema necessárias para PyMuPDF/fpdf2 e fontes
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    fontconfig \
    fonts-dejavu \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

COPY . .

# Criar diretórios necessários com permissão adequada
RUN mkdir -p data tmp && chmod 777 data tmp

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers"]
