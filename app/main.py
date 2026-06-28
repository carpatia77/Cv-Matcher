import asyncio
import hashlib
import os
import re
import shutil
import time
import traceback
import uuid
from contextlib import asynccontextmanager

import fitz
import httpx
import numpy as np
from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile, BackgroundTasks
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.middleware.cors import CORSMiddleware
from fpdf import FPDF
from openai import AsyncOpenAI

from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded

from app.config import settings, BASE_DIR
from app.logger import logger
from app.database import init_db, load_jobs_db, save_run_db, get_run_db, cleanup_expired_runs


APP_DIR = BASE_DIR / "app"
TEMPLATES_DIR = APP_DIR / "templates"
STATIC_DIR = APP_DIR / "static"
TMP_DIR = BASE_DIR / "tmp"

# Modelos DeepSeek válidos no catálogo NVIDIA
DEEPSEEK_MODELS = [
    "deepseek-ai/deepseek-r1",
    "deepseek-ai/deepseek-v3",
]
FALLBACK_AUDIT_MODEL = "meta/llama-3.3-70b-instruct"

# Limiter para rate limit
limiter = Limiter(key_func=get_remote_address)

# ---------- INICIALIZAÇÃO FASTAPI ----------
@asynccontextmanager

async def lifespan(app: FastAPI):
    TMP_DIR.mkdir(exist_ok=True)
    init_db()
    logger.info("Aplicação inicializada com sucesso.")
    yield

app = FastAPI(title="ATS Predictor Neural", lifespan=lifespan)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


# ---------- FUNÇÕES AUXILIARES ----------
def sanitize_text(text: str) -> str:
    if not text:
        return ""
    text = str(text)
    subs = {
        "\u2013": "-", "\u2014": "-", "\u201c": '"', "\u201d": '"',
        "\u2018": "'", "\u2019": "'", "\u2022": "-", "\u2023": "-",
        "\u2043": "-", "\u2219": "-", "\u00b7": "-", "\u2026": "...",
        "\u00a0": " ", "\t": "    ",
    }
    for k, v in subs.items():
        text = text.replace(k, v)
    text = re.sub(r"[^\S\r\n]+", " ", text)
    text = "\n".join(line.rstrip() for line in text.splitlines())
    return text.strip()

def strip_tags(texto: str) -> str:
    texto = re.sub(r"\[SCORE_TECNICO\]\d+\[/SCORE_TECNICO\]", "", texto, flags=re.IGNORECASE)
    texto = re.sub(r"\[SCORE_SENIORIDADE\]\d+\[/SCORE_SENIORIDADE\]", "", texto, flags=re.IGNORECASE)
    texto = re.sub(r"\[PENALIDADE_FRICCAO\]\d+\[/PENALIDADE_FRICCAO\]", "", texto, flags=re.IGNORECASE)
    return sanitize_text(texto)

def extract_note(tag: str, text: str, default: int = 0, min_val: int = 0, max_val: int = 100) -> int:
    pattern = rf"\[{tag}\]\s*(\d+)\s*\[/{tag}\]"
    m = re.search(pattern, text, re.IGNORECASE)
    if m:
        val = int(m.group(1))
        return max(min_val, min(max_val, val))
    # Fallback restrito (apenas se houver dois pontos ou espaço próximo ao número)
    m2 = re.search(rf"{tag}[:\s]*(\d+)", text, re.IGNORECASE)
    if m2:
        val = int(m2.group(1))
        return max(min_val, min(max_val, val))
    return default

def cosine_sim(v1, v2):
    a, b = np.array(v1), np.array(v2)
    denom = np.linalg.norm(a) * np.linalg.norm(b)
    return 0.0 if denom == 0 else float(np.dot(a, b) / denom)

def configure_font(pdf: FPDF):
    regular = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
    bold = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
    if os.path.exists(regular) and os.path.exists(bold):
        pdf.add_font("Uni", "", regular)
        pdf.add_font("Uni", "B", bold)
        pdf.main_font = "Uni"
    else:
        pdf.main_font = "Helvetica"

def pdf_text(pdf: FPDF, txt: str) -> str:
    txt = sanitize_text(txt)
    if getattr(pdf, "main_font", "Helvetica") == "Uni":
        return txt
    return txt.encode("latin-1", "replace").decode("latin-1")

def safe_cell(pdf: FPDF, h: float, txt: str, **kwargs):
    pdf.cell(0, h, pdf_text(pdf, txt), **kwargs)

def safe_multicell(pdf: FPDF, w: float, h: float, txt: str, **kwargs):
    pdf.multi_cell(w, h, pdf_text(pdf, txt), **kwargs)

# ---------- RELATÓRIO PDF ----------
class ReportPDF(FPDF):
    def header(self):
        self.set_text_color(0, 51, 102)
        self.set_font(self.main_font, "B", 14)
        self.cell(0, 10, pdf_text(self, "RELATORIO PREDITIVO DE EMPREGABILIDADE (ATS)"),
                  align="C", new_x="LMARGIN", new_y="NEXT")
        self.set_line_width(0.5)
        self.set_draw_color(0, 51, 102)
        self.line(15, 22, 195, 22)
        self.ln(8)

    def footer(self):
        self.set_y(-15)
        self.set_text_color(128, 128, 128)
        self.set_font(self.main_font, "", 8)
        self.cell(0, 10, pdf_text(self, f"Pagina {self.page_no()} | Analise Neural"), align="C")

def generate_pdf(vaga_alvo, score_final, s_tech, s_senior, s_nlp, penalidade, analise_texto, output_path: str):
    pdf = ReportPDF()
    configure_font(pdf)
    pdf.set_margins(15, 25, 15)
    pdf.set_auto_page_break(auto=True, margin=20)
    pdf.add_page()
    page_width = pdf.w - pdf.l_margin - pdf.r_margin

    pdf.set_text_color(50, 50, 50)
    pdf.set_font(pdf.main_font, "B", 12)
    safe_cell(pdf, 6, f"Vaga Alvo: {vaga_alvo.upper()}", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(4)

    if score_final >= 75:
        pdf.set_text_color(34, 139, 34)
    elif score_final >= 50:
        pdf.set_text_color(204, 119, 34)
    else:
        pdf.set_text_color(200, 0, 0)

    pdf.set_font(pdf.main_font, "B", 18)
    safe_cell(pdf, 10, f"SCORE DE PROBABILIDADE FINAL: {score_final}/100", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(2)

    pdf.set_text_color(0, 0, 0)
    pdf.set_font(pdf.main_font, "", 11)
    for line in [
        f"- Alinhamento de Hard Skills (Tecnico): {s_tech}/100",
        f"- Fit de Maturidade e Senioridade: {s_senior}/100",
        f"- Aderencia Semantica Vetorial (NLP): {s_nlp}%",
        f"- Fator de Friccao de Mercado: -{penalidade} pts",
    ]:
        safe_cell(pdf, 6, line, new_x="LMARGIN", new_y="NEXT")

    pdf.ln(10)
    pdf.set_font(pdf.main_font, "B", 14)
    pdf.set_text_color(0, 51, 102)
    safe_cell(pdf, 10, "DIAGNOSTICO E ANALISE DE RISCO", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(2)

    analise_limpa = strip_tags(analise_texto)
    for p in analise_limpa.split("\n"):
        p = p.strip()
        if not p:
            pdf.ln(3)
            continue
        pdf.set_text_color(0, 0, 0)
        if p.startswith("#"):
            pdf.set_font(pdf.main_font, "B", 12)
            safe_multicell(pdf, page_width, 6, re.sub(r"^#+\s*", "", p), new_x="LMARGIN", new_y="NEXT")
            pdf.ln(1)
        elif p.startswith(("-", "*")):
            pdf.set_font(pdf.main_font, "", 11)
            pdf.set_x(pdf.l_margin + 5)
            safe_multicell(pdf, page_width - 5, 5.5, re.sub(r"^[\-\*]\s*", "- ", p), new_x="LMARGIN", new_y="NEXT")
        elif "**" in p:
            pdf.set_font(pdf.main_font, "B", 11)
            safe_multicell(pdf, page_width, 5.5, p.replace("**", ""), new_x="LMARGIN", new_y="NEXT")
        else:
            pdf.set_font(pdf.main_font, "", 11)
            safe_multicell(pdf, page_width, 5.5, p, new_x="LMARGIN", new_y="NEXT")

    pdf.output(output_path)
    return output_path

# ---------- EXTRAÇÃO DE TEXTO DO PDF ----------
def extract_text_from_pdf(file_path: str) -> str:
    doc = fitz.open(file_path)
    text = " ".join(page.get_text() for page in doc)
    return " ".join(text.split())

async def extract_text_with_timeout(file_path: str):
    return await asyncio.wait_for(asyncio.to_thread(extract_text_from_pdf, file_path), timeout=settings.TIMEOUT_EXTRACTION)

# ---------- CLIENTE ASSÍNCRONO ----------
async def get_async_client() -> AsyncOpenAI:
    if not settings.NVIDIA_API_KEY:
        raise RuntimeError("NVIDIA_API_KEY não configurada no ambiente.")
    return AsyncOpenAI(
        base_url=settings.NVIDIA_BASE_URL,
        api_key=settings.NVIDIA_API_KEY,
        timeout=httpx.Timeout(settings.HTTPX_TIMEOUT, connect=30.0, read=settings.HTTPX_TIMEOUT, write=30.0, pool=30.0),
        max_retries=1,
    )

# ---------- TIMED CALL (CONTROLE DE TIMEOUT) ----------
async def timed_call(label, coro, timeout_s, fallback=None):
    logger.debug(f"{label} start timeout={timeout_s}")
    try:
        result = await asyncio.wait_for(coro, timeout=timeout_s)
        logger.debug(f"{label} ok")
        return result, None
    except asyncio.TimeoutError:
        logger.warning(f"{label} timeout")
        return fallback, f"timeout:{label}"
    except Exception as e:
        logger.error(f"{label} error type={type(e).__name__} msg={repr(e)}")
        logger.debug(f"{label} traceback: {traceback.format_exc()}")
        return fallback, f"error:{label}:{type(e).__name__}:{repr(e)}"

# ---------- SIMILARIDADE SEMÂNTICA ----------
_embedding_cache = {}

async def calcular_similaridade_semantica(texto1: str, texto2: str, cliente_api: AsyncOpenAI) -> float:
    texto1 = sanitize_text(texto1)[:2000]
    texto2 = sanitize_text(texto2)[:2000]

    h1 = hashlib.md5(texto1.encode()).hexdigest()
    h2 = hashlib.md5(texto2.encode()).hexdigest()

    cache_key = f"{h1}_{h2}"
    if cache_key in _embedding_cache:
        logger.debug(f"embedding cache hit key={cache_key}")
        return _embedding_cache[cache_key]

    tentativas = [
        {"model": "nvidia/nv-embed-v1"},
        {"model": "nvidia/nv-embedqa-mistral-7b-v2"},
        {"model": "nvidia/llama-3.2-nv-embedqa-1b-v2"},
    ]

    last_err = None
    for t in tentativas:
        try:
            logger.debug(f"embedding trying model={t['model']}")
            resp1 = await cliente_api.embeddings.create(
                model=t["model"],
                input=texto1,
                encoding_format="float"
            )
            resp2 = await cliente_api.embeddings.create(
                model=t["model"],
                input=texto2,
                encoding_format="float"
            )
            v1 = resp1.data[0].embedding
            v2 = resp2.data[0].embedding
            sim = round(cosine_sim(v1, v2) * 100, 2)
            val = max(0.0, min(100.0, sim))
            logger.debug(f"embedding success model={t['model']} similarity={val}%")
            _embedding_cache[cache_key] = val
            return val
        except Exception as e:
            last_err = e
            logger.debug(f"embedding fail model={t['model']} err={type(e).__name__}: {repr(e)}")

    logger.debug(f"embedding all models failed, returning fallback 50.0. last_err={repr(last_err)}")
    return 50.0

# ---------- AUDITORIA COM FALLBACK ----------
async def run_audit_with_fallback(client: AsyncOpenAI, prompt_auditoria: str, fallback_audit: str):
    for model_name in DEEPSEEK_MODELS:
        logger.debug(f"audit trying model={model_name} with timeout={settings.TIMEOUT_AUDIT}s")
        try:
            comp_auditoria, audit_err = await timed_call(
                f"audit-{model_name}",
                client.chat.completions.create(
                    model=model_name,
                    messages=[{"role": "user", "content": prompt_auditoria}],
                    temperature=0.1,
                    max_tokens=settings.AUDIT_MAX_TOKENS,
                ),
                timeout_s=settings.TIMEOUT_AUDIT,
                fallback=None,
            )
            if comp_auditoria and hasattr(comp_auditoria, "choices"):
                raw_audit = comp_auditoria.choices[0].message.content or ""
                logger.debug(f"audit model={model_name} raw response length={len(raw_audit)}")
                if raw_audit.strip():
                    logger.debug(f"audit SUCCESS with model={model_name}")
                    return sanitize_text(raw_audit), None, model_name
                else:
                    logger.debug(f"audit model={model_name} returned EMPTY response")
            else:
                logger.debug(f"audit model={model_name} failed: audit_err={audit_err}")
        except asyncio.TimeoutError:
            logger.warning(f"audit model={model_name} TIMEOUT after {settings.TIMEOUT_AUDIT}s")
        except Exception as e:
            logger.error(f"audit model={model_name} exception: {type(e).__name__}: {repr(e)}")
            if "rate_limit" in str(e).lower():
                await asyncio.sleep(5)

    logger.debug(f"audit all DeepSeek failed, trying fallback model={FALLBACK_AUDIT_MODEL}")
    try:
        comp_auditoria, audit_err = await timed_call(
            "audit-fallback",
            client.chat.completions.create(
                model=FALLBACK_AUDIT_MODEL,
                messages=[{"role": "user", "content": prompt_auditoria}],
                temperature=0.1,
                max_tokens=settings.AUDIT_MAX_TOKENS + 500,
            ),
            timeout_s=settings.TIMEOUT_AUDIT + 30,
            fallback=None,
        )
        if comp_auditoria and hasattr(comp_auditoria, "choices"):
            raw_audit = comp_auditoria.choices[0].message.content or ""
            if raw_audit.strip():
                logger.debug(f"audit SUCCESS with fallback model={FALLBACK_AUDIT_MODEL}")
                return sanitize_text(raw_audit), None, FALLBACK_AUDIT_MODEL
    except Exception as e:
        logger.error(f"audit fallback exception: {type(e).__name__}: {repr(e)}")

    logger.debug("audit ALL models failed, returning hardcoded fallback")
    return fallback_audit, RuntimeError("Todos os modelos de auditoria falharam"), "none"

# ---------- PIPELINE ASSÍNCRONO ----------
async def generate_pdf_with_timeout(*args, **kwargs):
    return await asyncio.wait_for(asyncio.to_thread(generate_pdf, *args, **kwargs), timeout=settings.TIMEOUT_PDF)

async def run_ats_pipeline_bg(run_id: str, input_pdf: str, output_pdf: str, vaga_alvo: str, descricao_vaga: str):
    t0 = time.time()
    logger.info(f"pipeline start run_id={run_id} vaga={vaga_alvo}")

    try:
        cv_text_raw = await extract_text_with_timeout(input_pdf)
        logger.debug(f"pdf extract done len={len(cv_text_raw)} elapsed={time.time()-t0:.2f}s")
        if not cv_text_raw.strip():
            raise RuntimeError("Não foi possível extrair texto do PDF enviado.")

        client = await get_async_client()
        try:
            # ---- 1. OTIMIZAÇÃO DO CURRÍCULO ----
            DELIMITADOR_CV = "=== CURRICULO_OTIMIZADO_INICIO ==="
            prompt_otimizacao = f"""
Como Especialista ATS, reescreva este currículo para ter máxima aderência semântica com a vaga alvo, sem inventar informações.

VAGA ALVO: {vaga_alvo}
VAGA: {descricao_vaga}
CURRÍCULO ORIGINAL: {cv_text_raw}

{DELIMITADOR_CV}
Escreva SOMENTE o currículo reformulado abaixo desta linha. Use Markdown simples.
""".strip()

            fallback_cv = sanitize_text(cv_text_raw)[:3500]
            comp_otimizacao, opt_err = await timed_call(
                "optimization",
                client.chat.completions.create(
                    model="meta/llama-3.3-70b-instruct",
                    messages=[{"role": "user", "content": prompt_otimizacao}],
                    temperature=0.2,
                    max_tokens=2500,
                ),
                settings.TIMEOUT_OPTIMIZATION,
                fallback=None,
            )

            if comp_otimizacao and hasattr(comp_otimizacao, "choices"):
                resposta_otimizacao = sanitize_text(comp_otimizacao.choices[0].message.content)
                cv_otimizado_texto = (
                    resposta_otimizacao.split(DELIMITADOR_CV, 1)[1].strip()
                    if DELIMITADOR_CV in resposta_otimizacao
                    else resposta_otimizacao.strip()
                )
            else:
                cv_otimizado_texto = fallback_cv
                logger.debug("optimization fallback used")

            # ---- 2. SIMILARIDADE SEMÂNTICA (NLP) ----
            try:
                s_nlp = await asyncio.wait_for(
                    calcular_similaridade_semantica(cv_otimizado_texto, descricao_vaga, client),
                    timeout=settings.TIMEOUT_EMBEDDING,
                )
            except Exception as e:
                logger.debug(f"similarity fallback err={repr(e)}")
                s_nlp = 50.0

            # ---- 3. AUDITORIA (DEEPSEEK ou FALLBACK) ----
            prompt_auditoria = f"""
Você é Headhunter Executivo. Avalie o candidato para a vaga.

REGRAS:
1. OBRIGATORIAMENTE comece com:
[SCORE_TECNICO]0-100[/SCORE_TECNICO]
[SCORE_SENIORIDADE]0-100[/SCORE_SENIORIDADE]
[PENALIDADE_FRICCAO]0-30[/PENALIDADE_FRICCAO]

2. Título: **ANÁLISE DE RISCO DO RECRUTADOR**

3. Conteúdo (use bullets):
- Resumo executivo
- Hard skills & gaps
- Senioridade e maturidade
- Riscos e fricções
- Forças competitivas
- Fragilidades que travam shortlist
- Recomendações práticas (3 itens)
- Conclusão final com parecer

Seja crítico. NÃO invente.

VAGA: {descricao_vaga[:500]}

CURRÍCULO OTIMIZADO:
{cv_otimizado_texto[:1500]}
""".strip()

            fallback_audit = """
[SCORE_TECNICO]45[/SCORE_TECNICO]
[SCORE_SENIORIDADE]45[/SCORE_SENIORIDADE]
[PENALIDADE_FRICCAO]10[/PENALIDADE_FRICCAO]

**ANÁLISE DE RISCO DO RECRUTADOR**
- Auditoria indisponível no momento. Sistema aplicou fallback conservador.
- Revise manualmente o currículo e a descrição da vaga.
"""

            resposta_auditoria, audit_err, audit_model_used = await run_audit_with_fallback(
                client, prompt_auditoria, fallback_audit
            )
            logger.debug(f"audit final model_used={audit_model_used} has_error={audit_err is not None}")

            # ---- 4. EXTRAÇÃO DOS SCORES ----
            s_tech = extract_note("SCORE_TECNICO", resposta_auditoria, default=45 if audit_err else 50, min_val=0, max_val=100)
            s_senior = extract_note("SCORE_SENIORIDADE", resposta_auditoria, default=45 if audit_err else 50, min_val=0, max_val=100)
            penalidade = extract_note("PENALIDADE_FRICCAO", resposta_auditoria, default=10 if audit_err else 0, min_val=0, max_val=30)

            # ---- 5. CÁLCULO DO SCORE FINAL ----
            score_final = round((s_tech * 0.45) + (s_senior * 0.35) + (s_nlp * 0.20) - penalidade, 1)
            score_final = max(0.0, min(100.0, score_final))

            # ---- 6. GERAÇÃO DO PDF ----
            await generate_pdf_with_timeout(vaga_alvo, score_final, s_tech, s_senior, s_nlp, penalidade, resposta_auditoria, output_pdf)

            logger.info(f"pipeline done run_id={run_id} elapsed={time.time()-t0:.2f}s")

            result_data = {
                "vaga_alvo": vaga_alvo,
                "score_final": score_final,
                "s_tech": s_tech,
                "s_senior": s_senior,
                "s_nlp": s_nlp,
                "penalidade": penalidade,
                "analise_texto": resposta_auditoria,
                "output_pdf": output_pdf,
                "audit_model_used": audit_model_used,
                "fallbacks": {
                    "optimization": opt_err is not None,
                    "audit": audit_err is not None,
                },
            }
            save_run_db(run_id, status="success", result=result_data)

        finally:
            await client.close()
            logger.debug("async client closed")

    except Exception as e:
        logger.error(f"Erro no background pipeline run_id={run_id}: {e}\n{traceback.format_exc()}")
        save_run_db(run_id, status="error", detail=str(e))
    finally:
        if os.path.exists(input_pdf):
            try:
                os.remove(input_pdf)
                logger.debug(f"Arquivo temporário removido: {input_pdf}")
            except Exception as e:
                logger.error(f"Erro ao remover arquivo temporário {input_pdf}: {e}")

# ---------- ENDPOINTS ----------
@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    return templates.TemplateResponse(request=request, name="index.html", context={"app_env": settings.APP_ENV})

@app.get("/api/health")
async def health():
    return {
        "status": "ok",
        "env": settings.APP_ENV,
        "nvidia_api_key_present": bool(settings.NVIDIA_API_KEY)
    }

@app.get("/api/jobs")
async def list_jobs():
    cleanup_expired_runs()
    return JSONResponse(load_jobs_db())

@app.get("/api/debug/models")
async def debug_models():
    if settings.APP_ENV not in ("development", "dev"):
        raise HTTPException(status_code=403, detail="Apenas em desenvolvimento.")
    try:
        client = await get_async_client()
        models = await client.models.list()
        await client.close()
        return {"models": [m.id for m in models.data]}
    except Exception as e:
        return {"error": str(e), "traceback": traceback.format_exc()}

@app.post("/api/analyze")
@limiter.limit("5/minute")
async def analyze(
    request: Request,
    background_tasks: BackgroundTasks,
    job_id: str = Form(...),
    descricao_customizada: str = Form(""),
    cv_file: UploadFile = File(...)
):
    logger.info(f"analyze start filename={cv_file.filename} job_id={job_id}")
    if not settings.NVIDIA_API_KEY:
        raise HTTPException(status_code=500, detail="NVIDIA_API_KEY não configurada no servidor.")

    if not cv_file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Envie um arquivo PDF válido.")

    # Validação de magic bytes %PDF e tamanho máximo
    magic_bytes = await cv_file.file.read(4)
    if magic_bytes != b"%PDF":
        raise HTTPException(status_code=400, detail="O arquivo enviado não é um PDF válido (magic bytes incorretos).")
    await cv_file.file.seek(0, 2) # ir para o final
    file_size = await cv_file.file.tell()
    await cv_file.file.seek(0) # voltar pro começo

    if file_size > settings.MAX_UPLOAD_MB * 1024 * 1024:
        raise HTTPException(status_code=400, detail=f"O arquivo excede o limite de {settings.MAX_UPLOAD_MB} MB.")

    jobs = load_jobs_db()
    selected_job = next((j for j in jobs if j["id"] == job_id), None)
    if not selected_job and not descricao_customizada.strip():
        raise HTTPException(status_code=400, detail="Vaga inválida e sem descrição customizada.")

    descricao_final = descricao_customizada.strip() or selected_job["descricao"]
    vaga_alvo = selected_job["titulo"] if selected_job else "Vaga Customizada"
    run_id = uuid.uuid4().hex
    output_pdf = TMP_DIR / f"{run_id}.pdf"
    input_pdf = TMP_DIR / f"input_{run_id}.pdf"
    logger.info(f"analyze prepared run_id={run_id} output_pdf={output_pdf}")

    with open(input_pdf, "wb") as f:
        shutil.copyfileobj(cv_file.file._file, f)

    save_run_db(run_id, status="processing")
    background_tasks.add(run_ats_pipeline_bg, run_id, str(input_pdf), str(output_pdf), vaga_alvo, descricao_final)
    cleanup_expired_runs()

    return JSONResponse(content={
        "status": "processing",
        "run_id": run_id,
        "status_url": f"/api/status/{run_id}",
        "message": "Análise iniciada em background."
    })

@app.get("/api/status/{run_id}")
async def get_status(run_id: str):
    cleanup_expired_runs()
    run_data = get_run_db(run_id)
    if not run_data:
        raise HTTPException(status_code=404, detail="Resultado não encontrado ou expirado.")
    
    status = run_data["status"]
    if status == "processing":
        return JSONResponse(content={"status": "processing", "run_id": run_id})
    elif status == "error":
        return JSONResponse(content={"status": "error", "run_id": run_id, "detail": run_data.get("detail")})
    else:
        return JSONResponse(content={
            "status": "success",
            "run_id": run_id,
            "download_url": f"/api/result/{run_id}",
            "vaga_alvo": run_data["vaga_alvo"],
            "score_final": run_data["score_final"],
            "s_tech": run_data["s_tech"],
            "s_senior": run_data["s_senior"],
            "s_nlp": run_data["s_nlp"],
            "penalidade": run_data["penalidade"],
            "headline": run_data["headline"],
            "detail": run_data["detail"],
            "fallbacks": run_data.get("fallbacks", {}),
            "audit_model_used": run_data["audit_model_used"],
            "analise_texto": run_data["analise_texto"],
        })

@app.get("/api/result/{run_id}")
async def download_result(run_id: str):
    cleanup_expired_runs()
    item = get_run_db(run_id)
    if not item or item["status"] != "success":
        raise HTTPException(status_code=404, detail="Resultado não encontrado ou expirado.")
    pdf_path = item["pdf_path"]
    if not os.path.exists(pdf_path):
        raise HTTPException(status_code=404, detail="Arquivo PDF não encontrado.")
    return FileResponse(path=pdf_path, media_type="application/pdf", filename="diagnostico_ats.pdf")
