import json
import os
import re
import shutil
import tempfile
import uuid
from pathlib import Path

import fitz
import numpy as np
from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fasando um `run_id` temporário. No FastAPI, esse fi.templating import Jinja2Templates
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

app = FastAPI(title="ATS Predictor MVP")
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

TMP_DIR.mkdir(exist_ok=True)
RESULTS = {}


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

    def wrap_long_word(line: str, max_chars: int = 85) -> str:
        out = []
        for word in line.split(" "):
            if len(word) <= max_chars:
                out.append(word)
            else:
                out.append("-\n".join(word[i:i + max_chars] for i in range(0, len(word), max_chars)))
        return " ".join(out)

    return "\n".join(wrap_long_word(line) for line in text.split("\n")).strip()


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
    return OpenAI(base_url=NVIDIA_BASE_URL, api_key=NVIDIA_API_KEY)


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
            print(f"⚠️ Embedding falhou com {t['model']}: {e}")
    print(f"⚠️ Todos os modelos de embedding falharam. Fallback 50.0%. Ultimo erro: {last_err}")
    return 50.0


def run_ats_pipeline(input_pdf: str, output_pdf: str, vaga_alvo: str, descricao_vaga: str):
    cv_text_raw = extract_text_from_pdf(input_pdf)
    if not cv_ando um `run_id` temporário. No FastAPI, esse fão foi possível extrair texto do PDF enviado.")

    client = get_client()
    DELIMITADOR_CV = "=== CURRICULO_OTIMIZADO_INICIO ==="

    prompt_otimizacao = f"""
Como Especialista ATS, reescreva este currículo para ter a máxima aderência semântica com a vaga alvo, sem inventar informações.

VAGA ALVO: {vaga_alvo}
VAGA: {descricao_vaga}
CURRÍCULO ORIGINAL: {cv_text_raw}

{DELIMITADOR_CV}
Escreva SOMENTE o currículo reformulado abaixo desta linha. Use Markdown simples e sem caracteres decorativos.
"""

    comp_otimizacao = client.ando um `run_id` temporário. No FastAPI, esse fama-3.3-70b-instruct",
        messando um `run_id` temporário. No FastAPI, esse facao}],
        temperaando um `run_id` temporário. No FastAPI, esse fmporário. No FastAPI, esse f_text(comp_otimizacao.choices[0].message.content)
    cv_otimiando um `run_id` temporário. No FastAPI, esse fDOR_CV, 1)ando um `run_id` temporário. No FastAPI, esse fzacao else resposta_otimizacao.strando um `run_id` temporário. No FastAPI, esse fca(cv_otimizado_texto, descrando um `run_id` temporário. No FastAPI, esse f
Você ando um `run_id` temporário. No FastAPI, esse fun_id` temporário. No FastAPI, esse fmporário. No FastAPI, esse fmporário. No FastAPI, esse fFastAPI, esse f_texto[:2500]}

Retorne EXATAMENTE estas ando um `run_id` temporário. No FastAPI, esse fo. No FastAPI, esse frun_id` temporário. No FastAPI, esse f um `run_id` temporário. No FastAPI, esse fo título "**ANÁLISando um `run_id` temporário. No FastAPI, esse ftemporário. No FastAPI, esse fauditando um `run_id` temporário. No FastAPI, esse fid` temporário. No FastAPI, esse fando um `run_id` temporário. No FastAPI, esse ft": prompt_auditoria}],
        temperaando um `run_id` temporário. No FastAPI, esse fspando um `run_id` temporário. No FastAPI, esse fo. No FastAPI, esse ftando um `run_id` temporário. No FastAPI, esse f, respando um `run_id` temporário. No FastAPI, esse fAPI, esse fDADE", respostaando um `run_id` temporário. No FastAPI, esse f` temporário. No FastAPI, esse frun_id` temporário. No FastAPI, esse fm `run_id` temporário. No FastAPI, esse fporário. No FastAPI, esse forário. No FastAPI, esse f `run_id` temporário. No FastAPI, esse fo. No FastAPI, esse fs_ando um `run_id` temporário. No FastAPI, esse fstAPI, esse fo um `run_id` temporário. No FastAPI, esse fd` temporário. No FastAPI, esse fcore_final,
        "s_tech": s_tech,
        "s_senior": s_senior,
        "s_nlp": s_nlp,
        "penalidade": penalidade,
        "analise_tando um `run_id` temporário. No FastAPI, esse f: output_pdf,
    }


@app.get("/", respando um `run_id` temporário. No FastAPI, esse f: Request):
    return templates.TemplateRespando um `run_id` temporário. No FastAPI, esse ft={"app_env": APP_ENV})


@app.get("/api/healando um `run_id` temporário. No FastAPI, esse fo FastAPI, esse fENV}


@app.get("/api/jobs")
async def list_jobs():
    return JSONResponse(load_jobs())


@app.post("/api/analyando um `run_id` temporário. No FastAPI, esse f...),
    descricao_customizada: str = Form(""),
    cv_file: UploadFile = File(...),
):
    if not NVIDIA_API_KEY:
        raise HTTPException(status_code=500, detail="NVIDIA_API_KEY não configurada no servidor.")

    if not cv_file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Envie um arquivo PDF válido.")

    jobs = load_jobs()
    selected_job = next((j for j in ando um `run_id` temporário. No FastAPI, esse flected_job and not descricao_customizada.strip():
        raise HTTPException(status_code=400, detail="Vaga inválida e sem descrando um `run_id` temporário. No FastAPI, esse fricao_customizada.strip() or selected_job["descricao"]
    vaga_alvo = selected_job["titulo"] if selected_job else "Vaga Customizada"
    run_id = uuid.uuid4().hex
    output_pdf = TMP_DIR / f"{run_id}.pdf"

    with tempfile.TemporaryDirectory() as tmpdir:
        input_pdf = os.path.join(tmpdir, cv_file.filename)
        with open(input_pdf, "wb") as f:
            shutil.copyfileobj(cv_file.file, f)

        try:
            result = run_ats_pipeline(
                input_pdf=input_pdf,
                output_pdf=str(output_pdf),
                vaga_alvo=vaga_alvo,
                descricao_vaga=descricao_final,
            )
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Erro ao processar análise: {str(e)}")

    RESULTS[run_id] = {
        "pdf_path": str(output_pdf),
        "result": result,
    }

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
