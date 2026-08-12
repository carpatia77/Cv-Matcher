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

---

## 🛡️ Configuração de Segurança Adicional (Fail2ban no SSH)

Como o SSH está escutando na porta **443** na VM Oracle Linux (baseada em RHEL), configure o `fail2ban` apontando explicitamente para o arquivo de log `/var/log/secure`:

1. Crie o arquivo `/etc/fail2ban/jail.local`:
   ```ini
   [sshd]
   enabled  = true
   port     = 443
   logpath  = /var/log/secure
   maxretry = 5
   bantime  = 3600
   ```

2. Reinicie e habilite o serviço:
   ```bash
   sudo systemctl enable --now fail2ban
   sudo fail2ban-client status sshd
   ```

---

## 🔍 Checklist de Validação Pós-Deploy

- [ ] `curl -s https://cv-matcher.duckdns.org:8443/api/health` retorna `{"status":"ok", ...}`.
- [ ] O certificado SSL emitido pela Let's Encrypt está ativo e válido.
- [ ] O cabeçalho `Content-Security-Policy: frame-ancestors https://blackpill.unaux.com 'self';` está presente na resposta do Caddy.
- [ ] Ao acessar o site no ProFreeHost (`https://blackpill.unaux.com`), a interface é renderizada no `iframe` sem erros de *Mixed Content* nem alertas de XSS.
