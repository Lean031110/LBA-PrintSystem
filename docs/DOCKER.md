# DOCKER — imagen lista para instalar

La imagen incluye el servidor LBA (API + panel), el worker de la cola, las
dependencias fijadas y la posibilidad de ejecutar la impresora virtual. No
incluye Odoo: el addon se instala en tu instancia de Odoo 19 Community.

| Dato | Valor |
|---|---|
| Imagen publicada | `ghcr.io/lean031110/lba-print-system` |
| Tags | `1.0.0`, `sha-<12>`, `latest` (solo releases estables) |
| Base | `python:3.12-slim-bookworm` (Debian 12) |
| Usuario | `lba`, uid **10001**, sin shell |
| Puertos | `8000` API/panel, `9910` impresora virtual (solo si se habilita) |
| Datos | volumen `/data` (SQLite, `secret_key`, credenciales iniciales) |
| Licencia | MIT |

## 1. Arranque rápido

```bash
docker volume create lba-data
docker run -d --name lba-print \
  --restart unless-stopped \
  -p 8000:8000 \
  -v lba-data:/data \
  ghcr.io/lean031110/lba-print-system:1.0.0
```

El modo por defecto (`LBA_ROLE=all`) arranca API y worker en el mismo
contenedor. Las credenciales iniciales se generan en el primer arranque:

```bash
docker exec lba-print cat /data/initial_credentials.txt
```

Abre `http://<ip-del-servidor>:8000/`, entra con el usuario `admin` y esa
contraseña, y cambia la contraseña en **Seguridad** si vas a usarlo en producción.

Para fijar credenciales conocidas (por ejemplo en un despliegue automatizado):

```bash
docker run -d --name lba-print -p 8000:8000 -v lba-data:/data \
  -e LBA_ADMIN_PASSWORD='<contraseña-larga>' \
  -e LBA_API_TOKEN='<token-de-32+-caracteres>' \
  ghcr.io/lean031110/lba-print-system:1.0.0
```

No escribas secretos en el repositorio: usa variables de entorno del orquestador
o Docker secrets.

## 2. Docker Compose (API + worker separados)

```bash
cd docker
cp lba.env.example .env        # opcional: fija credenciales
docker compose up -d
docker compose ps
```

El compose levanta `api` y `worker` sobre el mismo volumen `lba-data` y espera a
que la API esté sana antes de arrancar el worker. Para incluir la impresora
virtual (útil sin hardware):

```bash
docker compose --profile simulator up -d
```

En ese caso registra una impresora con IP `simulator` (nombre del servicio) y
puerto `9910`; los documentos recibidos quedan en el volumen, en
`/data/simulated-printer/` (`*.escpos.bin`, `*.txt`, `documents.jsonl`).

Para construir la imagen localmente en lugar de descargarla:

```bash
LBA_IMAGE=lba-print-system:local docker compose up -d --build
```

## 3. Variables de entorno

| Variable | Default | Descripción |
|---|---|---|
| `LBA_ROLE` | `all` | `all`, `api`, `worker` o `simulator` |
| `LBA_DATA_DIR` | `/data` | Directorio de datos persistente |
| `LBA_DB_PATH` | `/data/lba.db` | Ruta de SQLite (debe estar en el volumen) |
| `LBA_HOST` | `0.0.0.0` | Interfaz de la API |
| `LBA_PORT` | `8000` | Puerto de la API |
| `LBA_SIM_PORT` | `9910` | Puerto de la impresora virtual |
| `LBA_SIM_SAVE_DIR` | `/data/simulated-printer` | Papel virtual en disco |
| `LBA_SIM_ENABLED` | `0` | `1` arranca también el simulador con `LBA_ROLE=all` |
| `LBA_ADMIN_PASSWORD` | aleatoria | Contraseña inicial del panel |
| `LBA_API_TOKEN` | aleatorio | Token inicial de la API |

## 4. Operación

- **Persistencia:** todo lo importante vive en `/data`. Sin volumen, los datos
  desaparecen al recrear el contenedor.
- **Copia de seguridad:** `docker run --rm -v lba-data:/data -v "$PWD:/backup"
  ghcr.io/lean031110/lba-print-system:1.0.0 sh -c 'sqlite3 /data/lba.db ".backup /backup/lba.db"'`
  y copia también `/data/secret_key` y `/data/initial_credentials.txt`.
- **Actualización:** descarga el tag nuevo, `docker compose pull` (o
  `docker pull`) y recrea los contenedores. El esquema se migra solo al arrancar.
- **Escalado:** un solo contenedor de worker y una sola base SQLite por volumen.
  No ejecutes dos instancias de la API sobre el mismo `lba.db` en hosts distintos.
- **Red:** la API debe estar en la LAN del servidor LBA y de Odoo. No la publiques
  en Internet; si necesitas HTTPS, pon un reverse proxy delante y mantén la
  cookie de sesión en el mismo origen.
- **Bind mounts:** si montas una carpeta del host, debe pertenecer al uid 10001:
  `sudo chown -R 10001:10001 /ruta/datos`.

## 5. Verificación de la imagen en CI

`.github/workflows/ci-docker.yml` construye la imagen y ejecuta
`deploy/ci/docker_smoke_test.sh`, que comprueba en contenedores reales:

1. el proceso corre con uid 10001 (no root);
2. `/api/v1/health` responde 200;
3. una impresora virtual en otro contenedor recibe una impresión de prueba;
4. el trabajo queda en `sent` y el documento aparece en `documents.jsonl`;
5. el trabajo persiste tras reiniciar el contenedor de la API;
6. `docker compose config` valida el compose del repositorio.

## 6. Límites

- La imagen es solo `linux/amd64`.
- No incluye TLS ni autenticación de proxy: usa un reverse proxy para HTTPS.
- `sent` significa bytes aceptados por el socket, no papel impreso. La impresora
  virtual guarda el documento como evidencia, no simula el firmware térmico.
- La imagen no está firmada criptográficamente; verifica el SHA-256 del
  `MANIFEST.txt` de la release y el digest de la imagen si tu política lo exige.
- El paquete GHCR puede ser privado según la configuración de la cuenta: si
  `docker pull` devuelve `denied`, inicia sesión con `docker login ghcr.io` o
  haz público el paquete en GitHub → Packages.
