# SECURITY — Seguridad (Fase 6)

## 1. Modelo de amenazas (LAN de un restaurante/comercio)

| Amenaza | Vector | Mitigación implementada |
|---|---|---|
| Exposición a Internet | puerto 8000 | LXC solo en bridge LAN; sin reenvío de puertos; firewall perimetral; allowlist de IPs en la propia app |
| Abuso de la API | cliente no autorizado en LAN | token Bearer obligatorio (excepto `/health` sin datos); 403 por IP fuera de allowlist |
| Robo de token | almacenamiento | tokens aleatorios `secrets.token_urlsafe(32)`; en BD solo hash SHA-256 + prefijo (el valor completo se muestra UNA vez al crear); nunca en código ni en el repo (`.gitignore` cubre `data/`, `.env`) |
| Fuerza bruta de login | panel | PBKDF2-HMAC-SHA256 260 000 iteraciones + salt; rate limit 8/min por IP en `/login`; cookie de sesión firmada (itsdangerous, TTL 8 h) |
| SSRF | `POST /printers`, `POST /jobs`, `discovery` | IPs validadas contra rangos privados (RFC1918 + loopback + link-local); **169.254.169.254 y 100.64.0.0/10 bloqueados**; IPs públicas rechazadas salvo configuración explícita `allow_public_printer_ips` (default false) |
| Payload malicioso | `POST /jobs` | Pydantic con unión discriminada, límites de tamaño/longitud (≤200 bloques, base64 ≤ 300 KB, total ≤ 1 MB); `image` solo `logo` registrado o base64 (nunca rutas de archivo) |
| Escalada en el LXC | contenedor | **LXC no privilegiado** (`--unprivileged 1`), usuario de servicio sin shell (`lba`), archivos propiedad del usuario |
| DoS interno | ráfagas | rate limit 120/min por IP en `/api/v1` (in-memory); timeouts en sockets (5 s) |
| Abuso silencioso | operaciones admin | **audit log** persistente: login OK/fallo, creación/rotación de tokens, altas/bajas de impresoras, cambios de configuración, reintentos manuales, backups |
| Fuga en el repo | credenciales en git | `.gitignore` estricto (`data/`, `.env*`, `*.db`); el instalador genera todo en el CT; nothing committed |

## 2. Credenciales (ciclo de vida)

1. **Instalación**: `install.sh` genera (a) contraseña `admin` aleatoria y (b) token API inicial; ambas se muestran una sola vez y quedan en `/var/lib/lba/initial_credentials.txt` con permisos 0600 root:lba — el administrador debe guardarlas y borrar el archivo.
2. **Rotación de token**: Panel → Seguridad → "Nuevo token" (muestra valor una vez) → actualizarlo en Odoo (`lba.print.server.api_token`) → revocar el viejo.
3. **Cambio de contraseña**: Panel → Seguridad (verifica la actual; PBKDF2).
4. La sesión del panel es una cookie firmada (HMAC con llave secreta del servidor, `/var/lib/lba/secret_key`); no hay sesión de servidor con estado.

## 3. Permisos y aislamiento

- El usuario `lba` del CT no tiene shell ni root; el systemd usa `User=lba`, `NoNewPrivileges`, `PrivateTmp`, `ProtectSystem=strict` + `ReadWritePaths=/var/lib/lba`.
- En Odoo, el token LBA se guarda en `lba.print.server.api_token` con `groups="base.group_system"` (lectura solo administradores; el modelo rechaza `read` del campo para no-admin en la vista).
- Ninguna impresora ni la API necesitan credenciales propias: ESC/POS raw 9100 es autenticación-cero por diseño de fabricante (razón de más para no exponer la LAN).

## 4. Operación

- Sin Internet en operación normal (HTMX vendorizado, sin CDN/fonts externas).
- `GET /health` no expone datos (solo versión/estado/uptime).
- Log de auditoría exportable (Panel → Seguridad) para revisiones.
- Copias: ver `PROXMOX_INSTALLATION.md` §4.

## 5. Pendiente / recomendaciones

1. HTTPS interno en LAN (proxy inverso con cert autofirmado) — no implementado v1 (LAN aislada); documentado en ROADMAP.
2. Fail2ban-like: hoy es rate-limit; si se requiere, ban temporal por IP (ROADMAP).
3. Confirmación física de impresión (DLE EOT status) — ROADMAP (mejoraría "sent"→"printed" real).
