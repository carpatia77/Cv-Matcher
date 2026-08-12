# 🚀 Guia de Implantação e Checklist (Oracle Cloud VM)

Este guia documenta o passo a passo completo para aplicar as configurações de infraestrutura HTTPS e resolver definitivamente o problema de **Mixed Content** ao incorporar o aplicativo via `iframe` no ProFreeHost.

---

## 📋 Pré-requisitos & Portas de Rede

Para que o Caddy consiga gerar e renovar certificados **Let's Encrypt** automaticamente via protocolo ACME HTTP-01 e servir a aplicação com suporte SSL completo, as seguintes portas devem estar liberadas:

1. **Oracle Cloud Infrastructure (OCI) - Security List:**
   - **Porta 80 (HTTP):** Necessária para o ACME Challenge do Let's Encrypt e redirecionamento automático para HTTPS.
   - **Porta 443 (HTTPS):** Necessária para tráfego seguro SSL/TLS da aplicação.

2. **Firewall do Sistema Operacional (Ubuntu / Oracle Linux):**
   - Garantir que as regras de `iptables`, `firewalld` ou `ufw` permitam conexões de entrada nas portas 80 e 443.

---

## 🛠️ Passo a Passo de Execução na VM Oracle

Execute os comandos abaixo no terminal da sua instância Oracle VM:

### 1. Atualizar o Repositório Local
```bash
cd ~/Cv-Matcher
git pull origin main
```

### 2. Copiar a Configuração do Caddy
```bash
sudo cp caddy_cvmatcher.conf /etc/caddy/Caddyfile
```

### 3. Validar a Sintaxe do Caddyfile
```bash
sudo caddy validate --config /etc/caddy/Caddyfile
```
> **Resultado esperado:** `Valid configuration`

### 4. Recarregar o Serviço do Caddy
```bash
sudo systemctl reload caddy
```
*(Caso o serviço não esteja rodando, inicie com `sudo systemctl restart caddy`)*

### 5. Verificar o Status do Serviço
```bash
sudo systemctl status caddy --no-pager
```

---

## 🌐 Publicação no ProFreeHost

1. Acesse o **File Manager** do seu painel no ProFreeHost.
2. Navegue até o diretório raiz do seu site (`htdocs`).
3. Faça o upload do arquivo `profreehost_index.html` atualizado, renomeando-o para `index.html`.

---

## 🔍 Checklist de Validação Pós-Deploy

- [ ] `curl -I https://cv-matcher.duckdns.org/` retorna status `HTTP/2 200` ou `HTTP/1.1 200`.
- [ ] O certificado SSL emitido pelo Let's Encrypt está ativo e válido.
- [ ] Ao acessar o site no ProFreeHost (`https://...`), a interface do ATS Predictor Neural é renderizada diretamente dentro do `iframe` sem avisos de *Mixed Content* no Console de Desenvolvedor (F12).
