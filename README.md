# ATS Predictor MVP

MVP em FastAPI para upload de curriculo em PDF, selecao de vaga e geracao de diagnostico ATS em PDF usando NVIDIA API.

## Funcionalidades

- Upload de curriculo PDF
- Seletor expandido de vagas via `data/jobs.json`
- Descricao customizavel da vaga
- Otimizacao semantica com `meta/llama-3.3-70b-instruct`
- Auditoria preditiva com `deepseek-ai/deepseek-v4-flash`
- Similaridade semantica com fallback de embeddings NVIDIA
- Exportacao do relatorio final em PDF
- Pronto para deploy no Render

## Estrutura

```bash
ats-mvp/
├── app/
│   ├── main.py
│   ├── static/style.css
│   └── templates/index.html
├── data/jobs.json
├── requirements.txt
├── render.yaml
└── README.md
```

## Execucao local

```bash
python -m venv .venv
source .venv/bin/activate  # Linux/macOS
# .venv\Scripts\activate   # Windows PowerShell
pip install -r requirements.txt
export NVIDIA_API_KEY="sua-chave-aqui"
uvicorn app.main:app --reload
```

Abra `http://127.0.0.1:8000`.

## Deploy no Render

1. Suba esta pasta para um repositorio no GitHub.
2. No Render, crie um novo Web Service a partir do repo.
3. O arquivo `render.yaml` pode ser detectado automaticamente.
4. Configure a variavel `NVIDIA_API_KEY` no painel do Render.
5. Faça o deploy.

## Observacoes importantes

- O processamento e sincrono e pode levar de 20 a 60 segundos.
- O filesystem do Web Service e temporario; neste MVP o PDF e retornado diretamente na resposta.
- Se quiser historico de analises, storage persistente e autenticacao, isso entra na fase 2.
- Alguns modelos de embedding podem nao estar disponiveis para toda conta NVIDIA; por isso o codigo possui fallback.

## Proximos passos sugeridos

- Adicionar logs estruturados
- Criar pagina de resultado HTML alem do PDF
- Migrar `jobs.json` para banco de dados
- Adicionar autenticacao
- Desacoplar processamento pesado em worker
