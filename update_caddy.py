pristine_caddyfile = """{
    auto_https off
}

http://datakonsig.duckdns.org:8443 {
    reverse_proxy localhost:8000
}

http://btc-flow-monitor.duckdns.org:8443 {
    reverse_proxy localhost:8080 {
        header_up Host {host}
        header_up X-Real-IP {remote}
        header_down X-Accel-Buffering "no"
        flush_interval -1
    }
}

https://cv-matcher.duckdns.org:8443 {
    tls /etc/caddy/fullchain.pem /etc/caddy/privkey.pem
    reverse_proxy 127.0.0.1:8055 {
        header_up Host {host}
        header_up X-Real-IP {remote}
        header_down X-Accel-Buffering "no"
        header_down -X-Frame-Options
        flush_interval -1
    }

    header Content-Security-Policy "frame-ancestors https://blackpill.unaux.com 'self';"
    header X-Content-Type-Options "nosniff"
    header Referrer-Policy "strict-origin-when-cross-origin"
}"""

with open('/etc/caddy/Caddyfile', 'w') as f:
    f.write(pristine_caddyfile)

print("=== PRISTINE CADDYFILE WRITTEN WITH /ETC/CADDY PEM PATHS ===")
