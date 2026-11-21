# USER GUIDE — Guía de usuario del LBA Print System

> Para tu restaurante/comercio: cómo usar el panel, conectar Odoo y
> verificar tus impresoras Rongta/Xprinter. Instalación en
> `docs/PROXMOX_INSTALLATION.md`; contrato API en `docs/API_CONTRACT.md`.

## 1. Primeros pasos (5 minutos, sin hardware)

```bash
# en el LXC o tu servidor Debian/Ubuntu:
cd /opt/lba/server
python -m app.drivers.simulator --port 9910 &   # impresora falsa
uvicorn app.main:app --port 8000 &              # API + panel
python -m app.worker &                          # cola de impresión
```

1. Abre `http://<ip>:8000` → login `admin` (contraseña en
   `data/initial_credentials.txt` la primera vez — cámbiala en Seguridad).
2. **Dispositivos → Añadir**: nombre "Cocina", IP `127.0.0.1`, puerto `9910`,
   perfil `simulator`, papel 80mm, encoding `CP850`.
3. **Prueba de impresión → Caracteres**: verás el ticket en la **Cola**
   (estado `sent`) con vista previa reconstruida del ticket.

> `sent` significa **enviado por TCP con éxito**, no "impreso físicamente":
> ninguna API ESC/POS por socket lo garantiza (ver docs/SECURITY.md §5).

## 2. Conectar tus impresoras reales (Rongta / Xprinter)

1. Imprime la autoconfiguración de la impresora (FEED al encender o utilidad
   oficial) para conocer su IP.
2. **Panel → Buscar impresoras**: rango `192.168.1.0/24` (tu LAN) →
   aparecerán los puertos 9100 abiertos.
3. **Dispositivos → Añadir**: fabricante/modelo (p. ej. Rongta RP326 o
   Xprinter XP-N160II), IP, puerto 9100, 80mm, `CP850`.
4. **Prueba de impresión** en orden: `Básico` → `Caracteres` → `Gráficos`
   (QR/barcode/logo) → `Corte`. Si los acentos salen mal, cambia el encoding
   (`CP850 → CP437 → CP852 → Windows-1252`) y repite "Caracteres".
5. Anota qué funciona en las **Notas** del dispositivo (eso alimenta la
   matriz de docs/COMPATIBILITY.md).

## 3. Secciones del panel

| Sección | Qué haces aquí |
|---|---|
| **Panel general** | impresoras accesibles/caídas, cola, errores, últimos trabajos |
| **Dispositivos** | alta/edición (fabricante, modelo, IP, puerto, conexión, papel 58/80mm, protocolo, encoding, notas), activar/desactivar |
| **Buscar impresoras** | escaneo de rango LAN autorizado (solo red privada) |
| **Prueba de impresión** | tickets básico/caracteres/gráficos/corte |
| **Cola** | trabajos en vivo (auto-refresco 3 s): reintentar, cancelar, reimprimir |
| **Historial** | trabajos terminados con bytes y vista previa |
| **Errores** | impresoras caídas + trabajos fallidos con reintento |
| **Configuración** | nombre de empresa, rangos discovery, allowlist IP, rate limit, retención |
| **Seguridad y copias** | tokens (crear/revocar), contraseña admin, auditoría, backup |

## 4. Conectar Odoo 19

1. **Panel → Seguridad → Crear token** (cópialo: solo se muestra una vez).
2. Copia `odoo_addons/lba_print_connector` a tus addons → instalar en Odoo.
3. **LBA Print → Servidor**: URL/puerto/token → **Probar conexión** →
   **Sincronizar impresoras**.
4. **LBA Print → Departamentos**: asigna impresoras a Caja/Cocina/Pizzería/
   Bar/Salón (+ categorías si quieres segmentar).
5. **TPV → Configuración → pestaña "Impresión LBA"**: activa y elige la
   impresora de recibos; en cada *impresora de comanda* elige su **Impresora
   LBA**.
6. Checklist completo de validación (12 pasos, incl. desconectar LBA y
   comprobar que el TPV no se congela): `docs/ODOO_VALIDACION.md`.

## 5. Recetas rápidas

**Reintentar un ticket fallido**: Errores → Reintentar (vuelve a `pending`,
attempts a 0). **Reimprimir**: Cola/Historial → Reimprimir (crea un trabajo
nuevo, mismo payload). **Sin bloquear el TPV**: si LBA está caído, Odoo
encola en `lba.print.job` y el cron reintenta cada minuto con backoff
(5 s→300 s, máx. 5). **Backup**: Seguridad → Descargar backup, o
`deploy/scripts/backup.sh` por cron. **Rotar token**: crea uno nuevo,
actualízalo en Odoo, revoca el viejo (nunca al revés).

## 6. Fallos frecuentes

| Síntoma | Causa probable | Solución |
|---|---|---|
| Acentos impresos como símbolos | codepage del firmware | cambia encoding del dispositivo y repite ticket "Caracteres" |
| Job `sent` pero no sale papel | impresora en pausa/sin papel | papel/cover; el sistema no confirma impresión física (por diseño) |
| 403 "IP no autorizada" | cliente fuera de allowlist | Configuración → allowlist (incluye la IP de Odoo) |
| 401 en Odoo→LBA | token rotado/revocado | pega el token vigoroso en el Servidor de Odoo |
| Job `failed` con "Connection refused" | impresora apagada/IP cambiada | corrige IP en Dispositivos → Reintentar |
| TPV lento al pagar | LBA caído y timeout 3 s | es el máximo bloqueo; revisa el servicio `lba-print-api` |
