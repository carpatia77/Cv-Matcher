import asyncio
import json
import os
import re
import shutil
import tempfile
import time
import uuid
from pathlib import Path

import fitz
import numpy as np
from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fpdf import FPDF
from openai import OpenAI

BASE_DIR = Path(__file__).resolve().parent.parent
APP_DIR = BASE_DIR / "app"
TEMPLATES_DIR = APP_DIR / "templates"
STATIC_DIR = APP_DIR / "static"
DATA_DIR = BASE_DIR / "data"
JOBS_FILE = DATA_DIR / "jobs.json"
TMP_DIR = BASE_DIR / "tmp"

NVIDIA_API_KEY = os.getenv("NVIDIA_API_KEY", "")
NVIDIA_BASE_URL = os.getenv("NVIDIA_BASE_URL", "https://integrate.api.nvidia.com/v1")
APP_ENV = os.getenv("APP_ENV", "development")

TIMEOUT_EXTRACTION = float(os.getenv("TIMEOUT_EXTRACTION", "15"))
TIMEOUT_OPTIMIZATION = float(os.getenv("TIMEOUT_OPTIMIZATION", "40"))
TIMEOUT_EMBEDDING = float(os.getenv("TIMEOUT_EMBEDDING", "25"))
TIMEOUT_AUDIT = float(os.getenv("TIMEOUT_AUDIT", "40"))
TIMEOUT_PDF = float(os.getenv("TIMEOUT_PDF", "20"))

app = FastAPI(title="ATS Predictor MVP")
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

TMP_DIR.mkdir(exist_ok=True)
RESULTS = {}


def dbg(msg):
    print(f"[ATS-DBG] {time.strftime('%H:%M:%S')} {msg}", flush=True)


class ReportPDF(FPDF):
    def header(self):
        self.set_text_color(0, 51, 102)
        self.set_font(self.main_font, "B", 14)
        self.cell(
            0,
            10,
            pdf_text(self, "RELATORIO PREDITIVO DE EMPREGABILIDADE (ATS)"),
            align="C",
            new_x="LMARGIN",
            new_y="NEXT",
        )
        self.set_line_width(0.5)
        self.set_draw_color(0, 51, 102)
        self.line(15, 22, 195, 22)
        self.ln(8)

    def footer(self):
        self.set_y(-15)
        self.set_text_color(128, 128, 128)
        self.set_font(self.main_font, "", 8)
        self.cell(
            0,
            10,
            pdf_text(self, f"Pagina {self.page_no()} | Analise Neural"),
            align="C",
        )


def sanitize_text(text: str) -> str:
    if text is None:
        return ""

    text = str(text)
    subs = {
        "\u2013": "-",
        "\u2014": "-",
        "\u201c": '"',
        "\u201d": '"',
        "\u2018": "'",
        "\u2019": "'",
        "\u2022": "-",
        "\u2023": "-",
        "\u2043": "-",
        "\u2219": "-",
        "\u00b7": "-",
        "\u2026": "...",
        "\u00a0": " ",
        "\t": "    ",
    }

    for k, v in subs.items():
        text = text.replace(k, v)

    text = re.sub(r"[^\S\r\n]+", " ", text)
    text = "\n".join(line.rstrip() for line in text.splitlines())
    return text.strip()


def strip_tags(texto: str) -> str:
    texto = re.sub(r"\[SCORE_TECNICO\]\d+\[/SCORE_TECNICO\]", "", texto)
    texto = re.sub(r"\[SCORE_SENIORIDADE\]\d+\[/SCORE_SENIORIDADE\]", "", texto)
    texto = re.sub(r"\[PENALIDADE_FRICCAO\]\d+\[/PENALIDADE_FRICCAO\]", "", texto)
    return sanitize_text(texto)


def extract_note(tag: str, text: str, default: int = 0) -> int:
    m = re.search(rf"\[{tag}\](\d+)\[/{tag}\]", text)
    if m:
        return int(m.group(1))
    m2 = re.search(rf"{tag}.*?(\d+)", text, re.IGNORECASE | re.DOTALL)
    return int(m2.group(1)) if m2 else default


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
    return txt if getattr(pdf, "main_font", "Helvetica") == "Uni" else txt.encode("latin-1", "replace").decode("latin-1")


def safe_cell(pdf: FPDF, h: float, txt: str, **kwargs):
    pdf.cell(0, h, pdf_text(pdf, txt), **kwargs)


def safe_multicell(pdf: FPDF, w: float, h: float, txt: str, **kwargs):
    pdf.multi_cell(w, h, pdf_text(pdf, txt), **kwargs)


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


def load_jobs():
    with open(JOBS_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def extract_text_from_pdf(file_path: str) -> str:
    doc = fitz.open(file_path)
    text = " ".join(page.get_text() for page in doc)
    return " ".join(text.split())


def get_client() -> OpenAI:
    if not NVIDIA_API_KEY:
        raise RuntimeError("NVIDIA_API_KEY não configurada no ambiente.")
    return OpenAI(
        base_url=NVIDIA_BASE_URL,
        api_key=NVIDIA_API_KEY,
        timeout=30.0,
        max_retries=0,
    )

async def timed_call(label, coro, timeout_s, fallback=None):
    dbg(f"{label} start timeout={timeout_s}")
    try:
        result = await asyncio.wait_for(coro, timeout=timeout_s)
        dbg(f"{label} ok")
        return result, None
    except asyncio.TimeoutError:
        dbg(f"{label} timeout")
        return fallback, f"timeout:{label}"
    except Exception as e:
        dbg(f"{label} error {repr(e)}")
        return fallback, f"error:{label}:{repr(e)}"


async def extract_text_with_timeout(file_path: str):
    return await asyncio.wait_for(asyncio.to_thread(extract_text_from_pdf, file_path), timeout=TIMEOUT_EXTRACTION)


async def generate_pdf_with_timeout(*args, **kwargs):
    return await asyncio.wait_for(asyncio.to_thread(generate_pdf, *args, **kwargs), timeout=TIMEOUT_PDF)


def calcular_similaridade_semantica(texto1: str, texto2: str, cliente_api: OpenAI) -> float:
    texto1 = sanitize_text(texto1)[:2000]
    texto2 = sanitize_text(texto2)[:2000]
    tentativas = [
        {"model": "nvidia/llama-3.2-nv-embedqa-1b-v2", "payload": {"input_type": "passage"}},
        {"model": "nvidia/nv-embedqa-e5-v5", "payload": {"input_type": "passage"}},
        {"model": "nvidia/nv-embed-v1", "payload": {}},
    ]
    last_err = None
    for t in tentativas:
        try:
            resp1 = cliente_api.embeddings.create(model=t["model"], input=texto1, **t["payload"])
            resp2 = cliente_api.embeddings.create(model=t["model"], input=texto2, **t["payload"])
            v1 = resp1.data[0].embedding
            v2 = resp2.data[0].embedding
            return round(max(0.0, min(100.0, cosine_sim(v1, v2) * 100)), 2)
        except Exception as e:
            last_err = e
            dbg(f"embedding fail model={t['model']} err={repr(e)}")
    dbg(f"embedding fallback 50.0 last_err={repr(last_err)}")
    return 50.0


async def run_ats_pipeline(input_pdf: str, output_pdf: str, vaga_alvo: str, descricao_vaga: str):
    t0 = time.time()
    dbg(f"pipeline start vaga={vaga_alvo}")
    cv_text_raw = await extract_text_with_timeout(input_pdf)
    dbg(f"pdf extract done len={len(cv_text_raw)} elapsed={time.time()-t0:.2f}s")
    if not cv_text_raw.strip():
        raise RuntimeError("Não foi possível extrair texto do PDF enviado.")

    client = get_client()
    DELIMITADOR_CV = "=== CURRICULO_OTIMIZADO_INICIO ==="

        prompt_auditoria = f"""
Você é um Headhunter Executivo.
Analise a aderência do currículo à vaga abaixo e retorne APENAS:

[SCORE_TECNICO]XX[/SCORE_TECNICO]
[SCORE_SENIORIDADE]XX[/SCORE_SENIORIDADE]
[PENALIDADE_FRICCAO]XX[/PENALIDADE_FRICCAO]

Depois, escreva um resumo curto com 3 bullets sobre os principais riscos.

VAGA: {descricao_vaga}
CURRÍCULO: {cv_otimizado_texto[:1800]}
""".strip()

    fallback_audit = """
**ANÁLISE DE RISCO DO RECRUTADOR**
- Auditoria indisponível no momento.
- O sistema aplicou fallback conservador.
- Revise manualmente o currículo e a descrição da vaga.
""".strip()

    try:
        dbg("audit request start")
        comp_auditoria = await asyncio.wait_for(
            asyncio.to_thread(
                lambda: client.chat.completions.create(
                    model="deepseek-ai/deepseek-v4-flash",
                    messages=[{"role": "user", "content": prompt_auditoria}],
                    temperature=0.1,
                    max_tokens=700,
                    request_timeout=20,
                )
            ),
            timeout=TIMEOUT_AUDIT,
        )
        dbg("audit response ok")
        resposta_auditoria = sanitize_text(comp_auditoria.choices[0].message.content)
        audit_err = None
    except Exception as e:
        dbg(f"audit fallback err={repr(e)}")
        resposta_auditoria = fallback_audit
        audit_err = e
    if comp_auditoria and hasattr(comp_auditoria, "choices"):
        resposta_auditoria = sanitize_text(comp_auditoria.choices[0].message.content)
    else:
        resposta_auditoria = fallback_audit
        dbg("audit fallback used")

       s_tech = extract_note("SCORE_TECNICO", resposta_auditoria, default=45 if audit_err else 50)
    s_senior = extract_note("SCORE_SENIORIDADE", resposta_auditoria, default=45 if audit_err else 50)
    penalidade = extract_note("PENALIDADE_FRICCAO", resposta_auditoria, default=10 if audit_err else 0)

    await generate_pdf_with_timeout(vaga_alvo, score_final, s_tech, s_senior, s_nlp, penalidade, resposta_auditoria, output_pdf)
    dbg(f"pipeline done elapsed={time.time()-t0:.2f}s")

    return {
        "vaga_alvo": vaga_alvo,
        "score_final": score_final,
        "s_tech": s_tech,
        "s_senior": s_senior,
        "s_nlp": s_nlp,
        "penalidade": penalidade,
        "analise_texto": resposta_auditoria,
        "output_pdf": output_pdf,
        "fallbacks": {
            "optimization": opt_err is not None,
            "audit": audit_err is not None,
        },
    }


@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    return templates.TemplateResponse(request=request, name="index.html", context={"app_env": APP_ENV})


@app.get("/api/health")
async def health():
    return {"status": "ok", "env": APP_ENV}


@app.get("/api/jobs")
async def list_jobs():
    return JSONResponse(load_jobs())


@app.post("/api/analyze")
async def analyze(job_id: str = Form(...), descricao_customizada: str = Form(""), cv_file: UploadFile = File(...)):
    dbg(f"analyze start filename={cv_file.filename} job_id={job_id}")
    if not NVIDIA_API_KEY:
        raise HTTPException(status_code=500, detail="NVIDIA_API_KEY não configurada no servidor.")

    if not cv_file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Envie um arquivo PDF válido.")

    jobs = load_jobs()
    selected_job = next((j for j in jobs if j["id"] == job_id), None)
    if not selected_job and not descricao_customizada.strip():
        raise HTTPException(status_code=400, detail="Vaga inválida e sem descrição customizada.")

    descricao_final = descricao_customizada.strip() or selected_job["descricao"]
    vaga_alvo = selected_job["titulo"] if selected_job else "Vaga Customizada"
    run_id = uuid.uuid4().hex
    output_pdf = TMP_DIR / f"{run_id}.pdf"
    dbg(f"analyze prepared run_id={run_id} output_pdf={output_pdf}")

    with tempfile.TemporaryDirectory() as tmpdir:
        input_pdf = os.path.join(tmpdir, cv_file.filename)
        with open(input_pdf, "wb") as f:
            shutil.copyfileobj(cv_file.file, f)
        dbg(f"upload saved input_pdf={input_pdf}")

        try:
            result = await run_ats_pipeline(
                input_pdf=input_pdf,
                output_pdf=str(output_pdf),
                vaga_alvo=vaga_alvo,
                descricao_vaga=descricao_final,
            )
        except Exception as e:
            dbg(f"analyze error err={repr(e)}")
            raise HTTPException(status_code=500, detail=f"Erro ao processar análise: {str(e)}")

    RESULTS[run_id] = {"pdf_path": str(output_pdf), "result": result}
    dbg(f"analyze done run_id={run_id}")

    return JSONResponse(content={
        "status": "ok",
        "run_id": run_id,
        "download_url": f"/api/result/{run_id}",
        "vaga_alvo": result["vaga_alvo"],
        "score_final": result["score_final"],
        "s_tech": result["s_tech"],
        "s_senior": result["s_senior"],
        "s_nlp": result["s_nlp"],
        "penalidade": result["penalidade"],
        "headline": "Análise concluída com sucesso.",
        "detail": "O PDF foi gerado e está pronto para download.",
        "fallbacks": result["fallbacks"],
    })


@app.get("/api/result/{run_id}")
async def download_result(run_id: str):
    item = RESULTS.get(run_id)
    if not item:
        raise HTTPException(status_code=404, detail="Resultado não encontrado ou expirado.")
    pdf_path = item["pdf_path"]
    if not os.path.exists(pdf_path):
        raise HTTPException(status_code=404, detail="Arquivo PDF não encontrado.")
    return FileResponse(path=pdf_path, media_type="application/pdf", filename="diagnostico_ats.pdf")
