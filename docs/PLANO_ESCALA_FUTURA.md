# Plano de Escala Futura — Autenticação, Observabilidade e Defesa Estrutural

> Data: 2026-08-12
> Escopo: roadmap para quando o tráfego/risco do CV-Matcher justificar investimento além do que o
> Plano Pareto (`PLANO_FRAGILIDADE_PARETO.md`, Tiers 1-2) já cobre.
> **Não é para implementar agora.** Cada fase tem um gatilho explícito de "quando fazer" — o
> princípio Pareto que guiou o resto do plano de segurança continua valendo: não investir esforço
> em robustez que o projeto no tamanho atual não precisa.

---

## Contexto

Com o Tier 1 e Tier 2 (incluindo a extensão in-depth anti-prompt-injection) implementados, o
security score do projeto subiu de 6/10 para 7.5/10. Os itens que ainda faltam para aproximar de
9-10 são estruturais, não pontuais — cada um exige desenho de arquitetura, não só um patch:

1. Ausência de autenticação (defesa hoje é toda perimetral, não de identidade)
2. Detecções geram log, não alerta ativo (visibilidade passiva, depende de revisão manual)
3. Defesa anti-prompt-injection é de "primeira linha" (delimitação + validação de formato), não
   estrutural (sem separação de privilégio entre o texto do usuário e o modelo que decide)

---

## Fase A — Autenticação leve

**Gatilho:** quando o rate limit anônimo (5/min global) virar gargalo de uso legítimo, ou quando
for necessário histórico por usuário em vez de apenas por `run_id` anônimo.

### A.1 — Magic link por e-mail

Mais barato que login tradicional, sem gerenciar senhas:

```python
import itsdangerous

serializer = itsdangerous.URLSafeTimedSerializer(settings.SECRET_KEY)

def generate_magic_link_token(email: str) -> str:
    return serializer.dumps(email, salt="magic-link")

def verify_magic_link_token(token: str, max_age: int = 900) -> str | None:
    try:
        return serializer.loads(token, salt="magic-link", max_age=max_age)
    except itsdangerous.BadSignature:
        return None
```

- Sessão via cookie assinado (`itsdangerous` ou JWT de vida curta), não token permanente.
- Rate limit por e-mail além de por IP — fecha o gap de IP rotation identificado no Tier 1.

**Esforço:** ~2 dias (envio de e-mail via Resend/SendGrid, fluxo de sessão, migração de `run_id`
anônimo para `user_id` vinculado).

### A.2 — Diferenciação de limites por usuário autenticado vs anônimo

```python
RATE_LIMIT_ANONIMO = "3/minute"       # mais restrito
RATE_LIMIT_AUTENTICADO = "10/minute"  # usuário com e-mail verificado ganha mais margem
```

Dá incentivo natural para autenticação sem forçar login obrigatório de imediato.

**Não fazer:** OAuth completo (Google/GitHub) nem sistema de senha própria neste estágio —
over-engineering para o volume atual. Reavaliar só se o produto crescer para ter conta persistente
com histórico, billing, etc.

---

## Fase B — Observabilidade e alertas ativos

**Gatilho:** assim que a Fase A entrar em produção, ou antes, se o volume de tentativas de
injection já logadas (tabela `injection_attempts`) mostrar padrão recorrente.

### B.1 — Alerta via webhook (Discord/Slack)

```python
async def send_security_alert(event_type: str, details: dict):
    if not settings.SECURITY_WEBHOOK_URL:
        return
    async with httpx.AsyncClient(timeout=5.0) as client:
        await client.post(settings.SECURITY_WEBHOOK_URL, json={
            "content": f"🚨 **{event_type}**\n```{json.dumps(details, indent=2, ensure_ascii=False)}```"
        })
```

Disparar em:
- 3+ tentativas de injection do mesmo IP (já bloqueado por 429 — agora também notifica)
- Circuit breaker diário atingido
- Falhas repetidas de Turnstile do mesmo IP em curto período
- `validar_saida_llm()` rejeitando saída (possível injeção bem-sucedida no nível de output)

**Esforço:** ~3h (webhook simples, sem infra nova).

### B.2 — Dashboard mínimo de métricas

```python
@app.get("/api/admin/metrics")
async def admin_metrics(request: Request):
    # proteger com token de admin simples, ou IP allowlist da própria VM
    return {
        "calls_today": get_daily_call_count(),
        "injection_attempts_24h": count_injection_attempts_last_24h(),
        "top_offender_ips": get_top_injection_ips(limit=5),
    }
```

**Esforço:** ~4h (reaproveita dados já persistidos, só falta agregação e uma rota protegida).

### B.3 — Log estruturado em JSON

Verificar se `app/logger.py` já produz JSON em produção — se sim, considerar enviar para um
serviço gratuito de agregação (Better Stack free tier, Grafana Cloud free tier) só quando o
volume de log justificar não depender de SSH + `tail -f`.

**Não fazer agora:** stack completa de observabilidade (Prometheus/Grafana self-hosted) —
desproporcional ao tamanho do projeto.

---

## Fase C — Defesa estrutural contra prompt injection

**Gatilho:** se o log da Fase B mostrar tentativas sofisticadas passando pelas Camadas 1-2 já
implementadas (delimitação + validação de formato), ou se o projeto ganhar tração pública real.

### C.1 — Padrão dual-LLM

Separar o pipeline em dois papéis:
- **Modelo "processador"**: só vê o PDF bruto extraído, temperatura baixa, produz uma versão
  estruturada e resumida do CV — sem executar julgamento, só extração.
- **Modelo "avaliador"**: nunca vê o texto bruto do usuário, só a versão já estruturada pelo
  processador — reduz a superfície de ataque porque o modelo que decide nunca processa texto
  livre não confiável diretamente.

```python
# Estágio 1: extração estruturada (baixo privilégio, sem decisão)
cv_estruturado = await extrair_estrutura_cv(cv_text_raw)  # -> JSON: {nome, experiencias: [...], skills: [...]}

# Estágio 2: avaliação (só vê dados já estruturados, não texto livre)
score = await avaliar_aderencia(cv_estruturado, vaga_estruturada)
```

**Esforço:** ~2-3 dias (redesenho do pipeline; mais uma chamada de LLM por análise = mais custo de
API — avaliar trade-off contra o teto de 40 rpm da conta NVIDIA).

### C.2 — Validação semântica da saída (além do formato)

```python
def validar_plausibilidade_score(s_tech: int, s_senior: int, penalidade: int) -> bool:
    # Scores em 0 ou 100 exatos, ou padrões idênticos repetidos, são sinal de possível manipulação
    if s_tech == s_senior == 100 and penalidade == 0:
        return False
    return True
```

**Esforço:** ~2h (heurística simples, complementa C.1, não substitui).

### C.3 — Rate limit de tokens de prompt, não só de requisições

Limitar o tamanho efetivo do que entra no prompt de forma mais precisa que o truncamento atual
(`[:10000]`), com contagem real de tokens (`tiktoken` ou equivalente), reduzindo o espaço de
manobra de payloads longos de injeção.

**Esforço:** ~3h.

**Não fazer agora:** treinar um classificador próprio de prompt injection (caro, precisa de
dataset, manutenção contínua) — heurísticas + dual-LLM cobrem a maior parte do valor por uma
fração do custo.

---

## Resumo de gatilhos

| Fase | Gatilho concreto |
|---|---|
| A — Autenticação | Rate limit anônimo virar gargalo de uso legítimo, ou necessidade de histórico por usuário |
| B — Observabilidade | Antes ou junto da Fase A — é barata e dá visibilidade pra decidir o resto |
| C — Defesa estrutural | Log da Fase B mostrar tentativas sofisticadas passando das camadas atuais |

Nenhuma fase deve ser iniciada preventivamente. Reavaliar este documento quando o gatilho
correspondente for observado na prática, não por calendário.
