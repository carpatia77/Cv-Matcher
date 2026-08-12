#!/usr/bin/env python3
"""
Script de backup automatizado para o banco SQLite do CV-Matcher.
Executa backup online seguro (.backup) e mantém retenção configurada (padrão: 7 dias).
"""
import sqlite3
import time
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
DB_PATH = DATA_DIR / "ats.db"
BACKUP_DIR = BASE_DIR / "backups"
RETENTION_DAYS = 7

def run_backup():
    if not DB_PATH.exists():
        print(f"[ERROR] Banco de dados não encontrado em {DB_PATH}")
        return

    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    today_str = time.strftime("%Y-%m-%d_%H%M%S")
    backup_file = BACKUP_DIR / f"ats_backup_{today_str}.db"

    print(f"[INFO] Iniciando backup online de {DB_PATH} para {backup_file}...")
    src_conn = sqlite3.connect(DB_PATH)
    dst_conn = sqlite3.connect(backup_file)
    with dst_conn:
        src_conn.backup(dst_conn)
    src_conn.close()
    dst_conn.close()
    print(f"[SUCCESS] Backup concluído com sucesso: {backup_file} ({backup_file.stat().st_size} bytes)")

    # Rotacionar backups mais antigos que RETENTION_DAYS
    cutoff_time = time.time() - (RETENTION_DAYS * 86400)
    for f in BACKUP_DIR.glob("ats_backup_*.db"):
        if f.stat().st_mtime < cutoff_time:
            try:
                f.unlink()
                print(f"[INFO] Backup antigo removido: {f.name}")
            except Exception as e:
                print(f"[WARNING] Erro ao remover backup antigo {f.name}: {e}")

if __name__ == "__main__":
    run_backup()
