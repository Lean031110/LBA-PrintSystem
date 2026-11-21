# COMPATIBILITY — Matriz de compatibilidad (Fase 0)

> Leyenda: **[V]** verificado en fuente primaria (web oficial del fabricante, PyPI, código Odoo clonado, manual oficial).
> **[HW]** requiere comprobación con hardware físico (guía §5). **[—]** fuera de alcance v1.

## 1. Plataformas

| Componente | Requisito | Origen |
|---|---|---|
| LBA Print Server | Python 3.12 (3.10+ tolerado), Debian 12/Ubuntu en LXC | [V] entorno de desarrollo |
| FastAPI / SQLAlchemy / Jinja2 / HTMX 2.0.4 (vendorizado) | — | [V] `server/requirements.txt` |
| python-escpos | **3.1** (2023-12-17, MIT), Python 3.8–3.12 | [V] https://pypi.org/project/python-escpos/ |
| Odoo 19 Community | Python **≥ 3.10** (`setup.py`, `MIN_PY_VERSION=(3,10)`), recomendado 3.11/3.12 | [V] clon rama 19.0; guías de instalación 2026 |
| OWL del TPV | @odoo/owl **2.8.4** vendida en el core | [V] `addons/web/static/lib/owl/owl.js` |
| Proxmox VE | LXC no privilegiado Debian 12; 1 vCPU, 1 GB RAM, 8 GB disco | [V] diseño de instalación (Fase 7) |

## 2. Impresoras — matriz

| Marca/Modelo | Papel | Interfaces [V] | ESC/POS | TCP 9100 | Perfil LBA | Estado |
|---|---|---|---|---|---|---|
| **Rongta RP326** | 80 mm (48 col) | USB + LAN + Serie, 250 mm/s | Sí (manual oficial) | [HW] | `generic` | Candidato prioritario |
| **Rongta RP325/327/328** | 80 mm | Ethernet (manual oficial de la serie) | Sí | [HW] | `generic` | Candidato |
| **Rongta RP331/RP350/RP337** | 80 mm | según ficha oficial | [V] catálogo | [HW] | `generic` | Pendiente ficha técnica concreta de red |
| **Rongta RP582/RP58A/RP58E/RP58B** | 58 mm (32 col) | según ficha oficial | [V] catálogo | [HW] | `generic` | Pendiente confirmar Ethernet por modelo |
| **Xprinter XP-N160II** | 80 mm (48 col) | USB + **Ethernet** + Wi-Fi + BT, 160 mm/s | Sí (SDK oficial ESC/POS, DIP de fuente) | [HW] | `generic` | Candidato prioritario |
| **Xprinter XP-N160** | 80 mm | USB + Ethernet | Sí (misma familia) | [HW] | `generic` | Candidato |
| Xprinter XP-58 (USB/BT) | 58 mm | sin LAN | Sí | — | — | [—] sin red: fuera de v1 |
| Epson TM-T88V… | 80 mm | Ethernet | Sí | Sí | `generic`/perfil escpos-db | Compatible (no es objetivo de compra) |
| **LBA Simulator** (incluido) | virtual | TCP local | emulado | Sí (puerto libre) | `simulator` | [V] usado en pruebas y demo |

Notas:
- Ningún fabricante "clon" publica en la ficha el literal "puerto 9100": el **estándar de facto** de la interfaz Ethernet ESC/POS es raw 9100 y así lo usan sus utilidades de IP. Aun así, LBA **no lo afirma como verificado por modelo** hasta la comprobación §5 (regla nº 11 del encargo).
- Cualquier impresora de red compatible ESC/POS que acepte raw 9100 funciona con el perfil `generic`; los perfiles específicos de escpos-printer-db se pueden seleccionar por dispositivo en la configuración.

## 3. Características por dispositivo (configurables por impresora)

| Característica | Opciones | Verificación |
|---|---|---|
| Ancho de papel | 58 mm (≈32 columnas) / 80 mm (≈48 columnas) | [V] calculado por servidor |
| Codificación de caracteres | `CP437`, `CP850`, `CP852`, `Windows-1252` (por defecto `CP850` para español) | [HW] ticket de prueba con "áéíóúñ ¿¡ €" |
| Alineación | izq / centro / dcha (ESC a) | [V] escpos 3.1 |
| Negrita / tamaño | ESC E y GS ! (ancho/alto 1–8) | [V] escpos 3.1 |
| Densidad | comando GS `!` / configuración de perfil | [HW] |
| Corte | total (`GS V 0/1`) / parcial (`GS V 66 m`) / feed antes de cortar | [HW] modo soportado por firmware |
| QR | GS ( k (module/box, EC) | [HW] tamaño máximo aceptado |
| Código de barras | EAN13/EAN8/UPC-A/UPC-E/CODE128/CODE39/ITF (python-barcode) | [HW] HRI y alturas |
| Logo/imágenes | raster ESC * (Pillow) | [HW] umbral de dithering |

## 4. Encodings para español

| Codepage | acentos á/é/í/ó/ú | ñ | ¿ ¡ | € | Notas |
|---|---|---|---|---|---|
| CP437 | sí (comoá etc. en posiciones raras de "raro" — usar prueba) | sí | sí | no | la histórica; en clones suele estar activa por DIP |
| CP850 | sí | sí | sí | sí | **default LBA**; buena cobertura latina-1 |
| CP852 | sí (Europa central/este) | sí | sí | no | alternativa si el firmware la soporta |
| Windows-1252 | sí | sí | sí | sí | algunos firmwares modernos |

El servidor aplica el encoding por bloque de texto al generar los bytes; el panel ofrece ticket de prueba específico de caracteres.

## 5. Guía de verificación con hardware físico (Rongta / Xprinter)

1. **Conectar** la impresora a la LAN por Ethernet, imprimir la autoconfiguración (botón FEED al encender en la mayoría de modelos; o vía utilidad oficial: Xprinter "configure IP address for Ethernet port printers", Rongta Tool Download oficial) para conocer IP/máscara/puerto.
2. **Ping** a la IP desde el LXC.
3. **Panel → Buscar impresoras**: escanear el rango LAN autorizado → debe aparecer el puerto 9100 abierto (y opcionalmente 515/631).
4. **Registrar** la impresora (fabricante/modelo/ancho 58|80/encoding).
5. **Prueba de impresión → ticket "Caracteres"**: valida acentos con la codepage elegida; si salen símbolos raros, cambia el encoding y repite (CP437↔CP850↔CP852↔W-1252).
6. **Ticket "Gráficos"**: QR + código de barras + logo; registrar qué funciona (y qué falla) en la ficha de la impresora (campo Notas).
7. **Ticket "Corte"**: validar corte total vs parcial.
8. **Someter carga**: enviar 20 tickets seguidos y observar cola/errores (buffer de impresora).
9. Documentar resultados por modelo en la sección "Notas" del dispositivo y en este archivo (PR al `COMPATIBILITY.md`).

## 6. Recursos externos para probar sin hardware

- Emuladores comunitarios: `sangatsharma/escpos-printer-emulator` (raw TCP), `danielmeza/CrossEscPosEmulator` (Win/mac/Linux/browser), `mertizci/thermal-printer-simulator` (macOS).
- `python-escpos` clase `Dummy` (usada en los tests de rendering de este repo).
- **LBA Simulator** incluido (`python -m app.drivers.simulator`): además de aceptar bytes, el panel reconstruye el texto del ticket a partir de los bytes enviados.
