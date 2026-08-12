# CV-Matcher (ATS Predictor Neural)

Plataforma em FastAPI para diagnóstico preditivo de aderência profissional. Realiza extração de texto de currículos em PDF, otimização semântica, cálculo de similaridade vetorial via embeddings NVIDIA e auditoria neural com modelos DeepSeek avançados.

## 🚀 Funcionalidades Refatoradas

- **Upload e Processamento Seguro**: Validação de magic bytes (`%PDF`), controle de tamanho máximo de upload (10MB) e proteção contra XSS no front-end.
- **Fluxo Assíncrono via BackgroundTasks**: O pipeline de análise roda em background, com polling em tempo real no dashboard visualizando o andamento etapa por etapa.
- **Persistência Robusta em SQLite**: Armazenamento seguro de vagas e do histórico de análises em `data/ats.db`.
- **Auditoria Preditiva Precisa**: Integração validada com o catálogo NVIDIA (`deepseek-ai/deepseek-r1` e `deepseek-ai/deepseek-v3`) e fallback robusto para `meta/llama-3.3-70b-instruct`.
- **Configurações Centralizadas**: Gestão profissional de variáveis de ambiente com `pydantic-settings`.
- **Observabilidade e Qualidade**: Logging estruturado JSON, proteção contra abusos via *rate limiting* (`slowapi`) e suíte completa de testes automatizados (`pytest`).

## 📁 Estrutura do Projeto

```bash
cv-matcher/
├── app/
│   ├── config.py          # Central de configurações (pydantic-settings)
│   ├── database.py        # Conexão e persistência SQLite
│   ├── logger.py          # Logging estruturado em JSON
│   ├── main.py            # Rotas FastAPI e controle de pipeline
│   ├── static/
│   │   ├── app.js         # Lógica assíncrona do dashboard (polling, validações)
│   │   └── style.css      # Design System (Tema Dark Ocean)
│   └── templates/
│       └── index.html     # Interface do Dashboard
├── data/
│   └── ats.db             # Banco de dados SQLite gerado automaticamente
├── tests/
│   └── test_api.py        # Suíte de testes automatizados
├── requirements.txt       # Dependências de produção fixadas
├── requirements-dev.txt   # Dependências de desenvolvimento e teste
├── Dockerfile             # Imagem otimizada para produção
├── docker-compose.yml     # Orquestração para deploy na nuvem
├── .env.example           # Modelo de variáveis de ambiente
└── README.md
```

## 💻 Execução Local

### Opção 1: Ambiente Virtual (Python 3.11+)

1. Clone o repositório e crie o ambiente virtual:
   ```bash
   python -m venv .venv
   source .venv/bin/activate  # Linux/macOS
   # .venv\Scripts\activate   # Windows PowerShell
   ```
2. Instale as dependências:
   ```bash
   pip install -r requirements.txt
   pip install -r requirements-dev.txt
   ```
3. Configure as variáveis de ambiente (copie `.env.example` para `.env`):
   ```bash
   cp .env.example .env
   # Edite o arquivo .env inserindo sua NVIDIA_API_KEY
   ```
4. Inicie o servidor:
   ```bash
   uvicorn app.main:app --reload
   ```
5. Acesse `http://localhost:8000`.

### Opção 2: Docker Compose

```bash
docker compose up --build
```
Acesse `http://localhost:8000`.

## ☁️ Deploy na Oracle Cloud VM

1. Na sua VM da Oracle Cloud (Ubuntu/Oracle Linux), certifique-se de ter o Docker e Docker Compose instalados.
2. Clone o repositório para a VM.
3. Crie e configure o arquivo `.env` na raiz do projeto com sua `NVIDIA_API_KEY` e defina `APP_ENV=production`.
4. Inicie o contêiner em modo detached:
   ```bash
   docker compose up -d --build
   ```
5. Configure as regras de firewall da VM (Ingress Rules na Oracle Cloud VCN e `ufw`/`iptables` local) para liberar a porta 8000 (ou configure um proxy reverso como Nginx apontando para `localhost:8000`).

## 🧪 Testes e Qualidade

Para rodar a suíte de testes automatizados e validação de código:

```bash
# Executar testes
pytest -v

# Verificar linting e formatação com ruff
ruff check .
```
