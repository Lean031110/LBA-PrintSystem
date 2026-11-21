# API_CONTRACT — Contrato REST /api/v1 (Fase 3)

> Base: `http://<lba-host>:8000/api/v1` · OpenAPI interactiva autogenerada: `http://<lba-host>:8000/docs` (Swagger) y `/redoc`.
> Autenticación: `Authorization: Bearer <token>` (o cabecera `X-API-Token`). Ver `SECURITY.md` (tokens de un solo uso visual, almacenados con hash, IP allowlist, rate limit).

## 1. Endpoints

| Método | Ruta | Descripción | Auth |
|---|---|---|---|
| GET | `/health` | Estado del servidor (versión, BD, cola, uptime) | no |
| GET | `/stats` | Contadores de cola/historial/errores | token |
| GET | `/printers` | Listado de impresoras | token |
| POST | `/printers` | Alta manual de impresora (IP/puerto) | token |
| GET | `/printers/{id}` | Detalle (incl. último estado/error) | token |
| PUT | `/printers/{id}` | Modificar configuración | token |
| DELETE | `/printers/{id}` | Eliminar | token |
| POST | `/printers/discover` | Escanear rango LAN autorizado | token |
| POST | `/printers/{id}/test` | Encola ticket de prueba (devuelve job) | token |
| GET | `/printers/{id}/preview/{job_id}` | Vista previa textual del trabajo enviado | token |
| POST | `/jobs` | Añadir trabajo (payload estructurado) | token |
| GET | `/jobs` | Lista con filtros `status`, `printer_id`, `limit` | token |
| GET | `/jobs/{id}` | Detalle + eventos | token |
| POST | `/jobs/{id}/retry` | Reintentar (`failed`→`pending`) | token |
| POST | `/jobs/{id}/reprint` | Reimprimir (nuevo job, mismo payload) | token |
| POST | `/jobs/{id}/cancel` | Cancelar si está pendiente | token |

Errores estándar: `400` payload inválido · `401` sin token · `403` IP no autorizada / token inválido · `404` no existe · `409` `idempotency_key` duplicada (devuelve el job existente) · `413` payload demasiado grande · `429` rate limit.

## 2. Objeto `Printer`

```json
{
  "id": "b7e2…uuid…",
  "name": "Cocina",
  "manufacturer": "Rongta",
  "model": "RP326",
  "profile": "generic",          // generic | simulator
  "connection_type": "network",
  "protocol": "escpos_raw_tcp",
  "ip": "192.168.1.61",
  "port": 9100,
  "paper_width_mm": 80,
  "columns": 48,
  "encoding": "CP850",
  "status": "online",            // unknown | online | offline
  "last_seen_at": "2026-11-21T04:55:12Z",
  "last_error": null,
  "notes": "",
  "active": true,
  "settings": { "cut": true, "density": null, "logo": false }
}
```

## 3. Trabajos — payload estructurado

`POST /jobs`:

```json
{
  "printer_id": "b7e2…uuid…",
  "idempotency_key": "odoo:pos.order:uuid…:delta:7f3c:printer:12",
  "origin": "odoo",
  "metadata": { "order_ref": "Order 00042-001-0023", "kind": "kitchen" },
  "document": {
    "type": "ticket",
    "blocks": [
      { "type": "text", "value": "PIZZERÍA LA BOMBA", "align": "center", "bold": true,
        "width": 1, "height": 1 },
      { "type": "text", "value": "Ticket 00042   Camarero: Yanet", "align": "left" },
      { "type": "ruler" },
      { "type": "text", "value": "2 x Pizza Especial", "align": "left" },
      { "type": "text", "value": "   » sin cebolla (nota cliente)", "align": "left" },
      { "type": "qr", "value": "https://lba.local/t/00042", "size": 6 },
      { "type": "barcode", "value": "00042001", "symbology": "CODE128", "height": 60 },
      { "type": "image", "source": "logo" },
      { "type": "feed", "lines": 2 },
      { "type": "cut", "feed_before": 3 }
    ]
  }
}
```

**Bloques válidos** (unión discriminada por `type`; todo validado con Pydantic):

| type | campos | límites |
|---|---|---|
| `text` | `value`, `align?` (left/center/right), `bold?`, `width?` 1–8, `height?` 1–8, `font?` a/b | value ≤ 4000 chars; ≤ 200 bloques |
| `ruler` | `char?` (default `-`) | — |
| `feed` | `lines` 0–20 | — |
| `cut` | `feed_before?` 0–20 | — |
| `qr` | `value`, `size?` 1–16 | value ≤ 1000 chars |
| `barcode` | `value`, `symbology` (EAN13, EAN8, UPC-A, UPC-E, CODE128, CODE39, ITF), `height?` 1–255 | value ≤ 100 |
| `image` | `source` = `logo` \| `base64`, `data?`, `width?` | base64 ≤ 300 KB |

Respuesta `202` (encolado):

```json
{
  "job": {
    "id": "9f0c…uuid…",
    "printer_id": "b7e2…",
    "status": "pending",
    "attempts": 0,
    "idempotency_key": "odoo:…",
    "duplicate": false
  }
}
```

Con `idempotency_key` repetida: `409` + cuerpo del job existente con `"duplicate": true` (no se encola nada nuevo).

## 4. Estados y semántica

| status | significado |
|---|---|
| `pending` | en cola (por primera vez o esperando reintento) |
| `processing` | el worker lo ha reclamado (ventana corta) |
| `sent` | bytes enviados y aceptados por el socket TCP — **no implica impresión física** |
| `failed` | agotados `max_attempts` (default 5) tras backoff exponencial 5 s→300 s |
| `cancelled` | cancelado manualmente |

`GET /jobs/{id}` incluye `events[]` (auditoría de transiciones) y, si `sent`, `bytes_len` y `preview` (reconstrucción textual).

## 5. Rate limits y guardas

- 120 peticiones/min por IP en `/api/v1` (configurable); 8/min en `/login`.
- `POST /printers` y `POST /jobs` validan IP de destino contra rangos privados (anti-SSRF; bloqueo explícito de 169.254.169.254 y metadatos).
- `discovery` solo acepta CIDR dentro de rangos autorizados en configuración.
- Payload máx. 1 MB (límite global de FastAPI).

## 6. Consumidor de referencia (Odoo)

El addon `lba_print_connector` usa exclusivamente: `GET /health`, `GET /printers`, `POST /jobs`, `GET /jobs/{id}`. Ver `ODOO_INTEGRATION.md`.
