import pytest
from fastapi.testclient import TestClient
from app.main import app
from app.config import settings

@pytest.fixture
def client():
    # Garantir que a chave de API esteja configurada para evitar 500 no check inicial
    settings.NVIDIA_API_KEY = "test_key_valid"
    with TestClient(app) as c:
        yield c

def test_health_check(client):
    response = client.get("/api/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert "nvidia_api_key_present" in data

def test_list_jobs(client):
    response = client.get("/api/jobs")
    assert response.status_code == 200
    jobs = response.json()
    assert isinstance(jobs, list)
    assert len(jobs) > 0
    for job in jobs:
        assert "id" in job
        assert "titulo" in job
        assert "categoria" in job

def test_analyze_invalid_file(client):
    # Testar envio de arquivo não-PDF
    response = client.post(
        "/api/analyze",
        data={"descricao_vaga": "FastAPI, Docker"},
        files={"cv_file": ("teste.txt", b"conteudo invalido", "text/plain")}
    )
    assert response.status_code == 400
    assert "PDF" in response.json()["detail"]

def test_analyze_valid_pdf(client):
    # Testar envio de arquivo PDF com magic bytes %PDF corretos
    response = client.post(
        "/api/analyze",
        data={"descricao_vaga": "Engenheiro de IA, Python, PyTorch"},
        files={"cv_file": ("curriculo.pdf", b"%PDF-1.4... conteudo simulado de pdf", "application/pdf")}
    )
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "processing"
    assert "run_id" in data
