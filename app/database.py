import json
import sqlite3

from app.config import BASE_DIR
from app.logger import logger

DATA_DIR = BASE_DIR / "data"
DB_PATH = DATA_DIR / "ats.db"

def get_db():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with get_db() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS jobs (
                id TEXT PRIMARY KEY,
                titulo TEXT NOT NULL,
                descricao TEXT NOT NULL,
                categoria TEXT NOT NULL
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS runs (
                run_id TEXT PRIMARY KEY,
                status TEXT NOT NULL,
                pdf_path TEXT,
                vaga_alvo TEXT,
                score_final REAL,
                s_tech INTEGER,
                s_senior INTEGER,
                s_nlp REAL,
                penalidade INTEGER,
                headline TEXT,
                detail TEXT,
                audit_model_used TEXT,
                analise_texto TEXT,
                fallbacks_json TEXT,
                reescrita_cv TEXT,
                output_cv_pdf TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS daily_metrics (
                date TEXT PRIMARY KEY,
                call_count INTEGER DEFAULT 0
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS global_calls (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp REAL NOT NULL
            )
        """)
        try:
            conn.execute("ALTER TABLE runs ADD COLUMN reescrita_cv TEXT")
            conn.execute("ALTER TABLE runs ADD COLUMN output_cv_pdf TEXT")
        except sqlite3.OperationalError:
            pass # Colunas já existem
        
        # Verificar se existem vagas cadastradas, caso contrário popular com vagas padrão
        cur = conn.execute("SELECT COUNT(*) FROM jobs")
        if cur.fetchone()[0] == 0:
            default_jobs = [
                ("dev_python", "Desenvolvedor Python Pleno", "Experiência com FastAPI, PostgreSQL, Docker, testes unitários.", "Engenharia de Software"),
                ("data_scientist", "Cientista de Dados", "Machine Learning, Python, SQL, visualização de dados.", "Data & Analytics"),
                ("arquiteto-ia", "Arquiteto de IA", "Experiência em arquitetura de sistemas de IA, LLMs, MLOps, cloud.", "Inteligência Artificial"),
            ]
            conn.executemany("INSERT INTO jobs (id, titulo, descricao, categoria) VALUES (?, ?, ?, ?)", default_jobs)
            logger.info("Banco de dados inicializado com vagas padrão.")
        conn.commit()

def load_jobs_db():
    with get_db() as conn:
        cur = conn.execute("SELECT id, titulo, descricao, categoria FROM jobs")
        return [dict(row) for row in cur.fetchall()]

def get_job_db(job_id: str):
    with get_db() as conn:
        cur = conn.execute("SELECT id, titulo, descricao, categoria FROM jobs WHERE id = ?", (job_id,))
        row = cur.fetchone()
        return dict(row) if row else None

def save_run_db(run_id: str, status: str, result: dict = None, detail: str = None):
    with get_db() as conn:
        if status == "processing":
            conn.execute(
                "INSERT OR REPLACE INTO runs (run_id, status) VALUES (?, ?)",
                (run_id, status)
            )
        elif status == "success" and result:
            fallbacks_json = json.dumps(result.get("fallbacks", {}))
            headline = "Análise concluída com sucesso."
            if result.get("fallbacks", {}).get("audit"):
                headline = f"Análise com fallback (modelo: {result.get('audit_model_used')})."
                
            conn.execute("""
                UPDATE runs SET 
                    status = ?, pdf_path = ?, vaga_alvo = ?, score_final = ?, s_tech = ?, 
                    s_senior = ?, s_nlp = ?, penalidade = ?, headline = ?, detail = ?, 
                    audit_model_used = ?, analise_texto = ?, fallbacks_json = ?, reescrita_cv = ?, output_cv_pdf = ?
                WHERE run_id = ?
            """, (
                status, result.get("output_pdf"), result.get("vaga_alvo"), result.get("score_final"),
                result.get("s_tech"), result.get("s_senior"), result.get("s_nlp"), result.get("penalidade"),
                headline, detail or f"Modelo auditoria: {result.get('audit_model_used')}. PDF pronto para download.",
                result.get("audit_model_used"), result.get("analise_texto"), fallbacks_json,
                result.get("reescrita_cv"), result.get("output_cv_pdf"), run_id
            ))
        elif status == "error":
            conn.execute("UPDATE runs SET status = ?, detail = ? WHERE run_id = ?", (status, detail, run_id))
        conn.commit()

def get_run_db(run_id: str):
    with get_db() as conn:
        cur = conn.execute("SELECT * FROM runs WHERE run_id = ?", (run_id,))
        row = cur.fetchone()
        if not row:
            return None
        d = dict(row)
        if d.get("fallbacks_json"):
            d["fallbacks"] = json.loads(d["fallbacks_json"])
        return d

def cleanup_expired_runs(ttl_seconds: int = 3600):
    import os
    with get_db() as conn:
        cur = conn.execute("SELECT run_id, pdf_path, output_cv_pdf FROM runs WHERE datetime(created_at, ?) < datetime('now')", (f"+{ttl_seconds} seconds",))
        rows = cur.fetchall()
        for row in rows:
            for col in ("pdf_path", "output_cv_pdf"):
                pdf_path = row[col]
                if pdf_path and os.path.exists(pdf_path):
                    try:
                        os.remove(pdf_path)
                        logger.debug(f"Arquivo PDF removido: {pdf_path}")
                    except Exception as e:
                        logger.error(f"Erro ao remover arquivo PDF {pdf_path}: {e}")
        conn.execute("DELETE FROM runs WHERE datetime(created_at, ?) < datetime('now')", (f"+{ttl_seconds} seconds",))
        conn.commit()

def increment_daily_calls() -> int:
    import time
    with get_db() as conn:
        today = time.strftime("%Y-%m-%d")
        conn.execute("""
            INSERT INTO daily_metrics (date, call_count) VALUES (?, 1)
            ON CONFLICT(date) DO UPDATE SET call_count = call_count + 1
        """, (today,))
        conn.commit()
        cur = conn.execute("SELECT call_count FROM daily_metrics WHERE date = ?", (today,))
        row = cur.fetchone()
        return row[0] if row else 1

def get_daily_call_count() -> int:
    import time
    with get_db() as conn:
        today = time.strftime("%Y-%m-%d")
        cur = conn.execute("SELECT call_count FROM daily_metrics WHERE date = ?", (today,))
        row = cur.fetchone()
        return row[0] if row else 0

def record_global_call() -> None:
    import time
    now = time.time()
    cutoff = now - 300.0  # Limpar registros antigos com mais de 5 minutos
    with get_db() as conn:
        conn.execute("INSERT INTO global_calls (timestamp) VALUES (?)", (now,))
        conn.execute("DELETE FROM global_calls WHERE timestamp < ?", (cutoff,))
        conn.commit()

def count_recent_global_calls(window_seconds: float = 60.0) -> int:
    import time
    cutoff = time.time() - window_seconds
    with get_db() as conn:
        cur = conn.execute("SELECT COUNT(id) FROM global_calls WHERE timestamp >= ?", (cutoff,))
        row = cur.fetchone()
        return row[0] if row else 0




