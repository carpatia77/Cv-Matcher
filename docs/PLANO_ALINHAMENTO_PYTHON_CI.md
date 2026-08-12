# Plano — Alinhamento de Versão Python entre CI e VM de Produção

> Data: 2026-08-12
> Para: engenheiro executor
> Prioridade: alta — gap descoberto na prática, não teórico (ver "Como foi descoberto" abaixo)

---

## Problema

O CI (`.github/workflows/ci.yml`) roda **Python 3.12**. A VM Oracle de produção roda **Python
3.9**. O CI não é um espelho fiel do ambiente onde o código realmente executa.

### Como foi descoberto

Durante a implementação da extensão anti-prompt-injection (Tier 2, commit `cacf5f6`), foi
introduzida a assinatura:

```python
def record_injection_attempt(ip: str, run_id: str | None = None, source: str = "unknown") -> None:
```

A sintaxe `str | None` (PEP 604) só é válida a partir do Python 3.10. O CI, rodando 3.12,
**aprovou o código sem erro**. O bug só foi identificado manualmente pelo executor antes do
deploy e corrigido no commit `225dd6c` (`Optional[str]`). Não houve incidente em produção porque
a verificação foi feita antes do `git pull` na VM — mas o CI não teria pego isso sozinho.

**Consequência:** qualquer sintaxe nova do Python (union types, `match/case`, `tomllib`, etc.)
pode passar no CI e quebrar silenciosamente só ao chegar na VM.

---

## Objetivo

Fechar esse gap de forma que o CI só aprove código que realmente roda na versão de Python da VM.

---

## Opção recomendada: alinhar o CI à versão real da VM

Mais barato que atualizar a VM agora, e resolve o problema pela raiz — o CI passa a ser um
espelho fiel do ambiente de produção.

### Passo 1 — Confirmar a versão exata do Python na VM

```bash
ssh -p 443 opc@<vm> "python3 --version"
# e também a versão usada de fato pelo venv do serviço:
ssh -p 443 opc@<vm> "/home/opc/Cv-Matcher/venv/bin/python --version"
```

### Passo 2 — Atualizar o CI para essa versão exata

```yaml
# .github/workflows/ci.yml
- uses: actions/setup-python@v5
  with:
    python-version: "3.9"  # ajustar para o valor exato confirmado no Passo 1
    cache: "pip"
```

### Passo 3 — Rodar a suíte completa localmente com a versão da VM antes do próximo merge

```bash
# Se disponível via pyenv/deadsnakes:
python3.9 -m venv venv39
source venv39/bin/activate
pip install -r requirements.txt -r requirements-dev.txt
ruff check .
pytest -v
```

Prestar atenção especial a:
- Sintaxe de union types (`X | Y`) → trocar por `Union[X, Y]` ou `Optional[X]`
- `match/case` (3.10+) — não usado hoje, mas vigiar em código futuro
- `tomllib` (3.11+) — não usado hoje
- `list[X]`/`dict[X, Y]` como *type hints em runtime* (ex: `isinstance` checks) — genéricos de
  builtins como type hints funcionam desde o 3.9 apenas em anotações, não em todos os contextos

### Passo 4 (opcional, recomendado a médio prazo) — Considerar atualizar a VM em vez do CI

Python 3.9 está próximo do fim do ciclo de suporte de segurança ativo da PSF. Se o ambiente
Oracle permitir, migrar a VM para 3.11 ou 3.12 é o caminho mais sustentável a médio prazo — nesse
caso o Passo 2 se inverte: atualizar o CI para acompanhar a VM já modernizada, em vez de
rebaixá-lo. Avaliar com o time qual das duas direções é mais viável dado o ambiente atual antes de
decidir entre "rebaixar CI" vs. "atualizar VM".

---

## Resumo de execução

| # | Ação | Esforço |
|---|---|---|
| 1 | Confirmar versão exata do Python na VM (`python3 --version` e do venv do serviço) | 5min |
| 2 | Alinhar `python-version` do CI a essa versão (ou decidir atualizar a VM primeiro) | 15min |
| 3 | Rodar suíte completa localmente na versão da VM antes do próximo merge | 30min |
| 4 | Documentar a versão-alvo no `README.md` e/ou `.env.example` para não divergir de novo | 15min |

Sem esse alinhamento, o CI continua dando falso sinal verde para código que pode quebrar apenas em
produção — o mesmo padrão de risco que motivou o restante do Plano Pareto de segurança.
