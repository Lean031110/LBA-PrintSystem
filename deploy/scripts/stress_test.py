#!/usr/bin/env python3
"""Prueba de estrés y concurrencia del LBA Print Server (sin hardware).

Arranca impresoras virtuales (``app.drivers.simulator --save-dir``), la API y
varios workers reales, y mide el comportamiento de la cola bajo carga:

1. Envío concurrente de N trabajos únicos desde C hilos.
2. Ráfaga de idempotencia: la misma clave desde varios hilos a la vez debe
   crear exactamente un trabajo (el resto 409, sin duplicados).
3. Verificación de que cada trabajo terminó en ``sent`` y de que la impresora
   virtual recibió exactamente un documento por trabajo, con hash válido.
4. Integridad de SQLite (``PRAGMA integrity_check``) y unicidad de claves.
5. Informe JSON con latencias, throughput y conteos.

Uso:
    python deploy/scripts/stress_test.py --jobs 200 --concurrency 16 \
        --workers 2 --printers 2 --duplicates 40 --burst 8 \
        --report /tmp/lba-stress.json

Ejecutar con el Python del servidor (requiere fastapi/uvicorn/sqlalchemy).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import random
import socket
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed

ROOT = Path(__file__).resolve().parents[2]
SERVER = ROOT / "server"
TOKEN = "stress-test-token-0123456789abcdef"


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def wait_port(host: str, port: int, timeout: float = 30.0) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        with socket.socket() as sock:
            sock.settimeout(0.5)
            if sock.connect_ex((host, port)) == 0:
                return
        time.sleep(0.1)
    raise RuntimeError(f"el puerto {host}:{port} no abrió a tiempo")


class Api:
    def __init__(self, base: str) -> None:
        self.base = base.rstrip("/")

    def request(self, method: str, path: str, body: dict | None = None,
                timeout: float = 30.0) -> tuple[int, dict]:
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(self.base + path, data=data, method=method)
        req.add_header("Authorization", f"Bearer {TOKEN}")
        if data is not None:
            req.add_header("Content-Type", "application/json")
        try:
            with urllib.request.urlopen(req, timeout=timeout) as response:
                return response.status, json.load(response)
        except urllib.error.HTTPError as exc:
            raw = exc.read()
            try:
                payload = json.loads(raw)
            except ValueError:
                payload = {"raw": raw[:300].decode("utf-8", "replace")}
            return exc.code, payload


class VirtualPrinter:
    def __init__(self, name: str, port: int, save_dir: Path, log_dir: Path) -> None:
        self.name = name
        self.port = port
        self.save_dir = save_dir
        self.log_path = log_dir / f"printer-{port}.log"
        self.process: subprocess.Popen | None = None
        self.external_id = ""

    def start(self, env: dict[str, str]) -> None:
        self.log = self.log_path.open("wb")
        self.process = subprocess.Popen(
            [sys.executable, "-m", "app.drivers.simulator", "--port", str(self.port),
             "--quiet", "--save-dir", str(self.save_dir)],
            cwd=SERVER, env=env, stdout=self.log, stderr=subprocess.STDOUT,
            start_new_session=True,
        )
        wait_port("127.0.0.1", self.port)

    def documents(self) -> list[dict]:
        journal = self.save_dir / "documents.jsonl"
        if not journal.exists():
            return []
        entries = []
        for line in journal.read_text(encoding="utf-8").splitlines():
            if line.strip():
                entries.append(json.loads(line))
        return entries


def stop_all(processes: list[subprocess.Popen], logs: list[Path]) -> str:
    for process in processes:
        if process.poll() is None:
            process.terminate()
    for process in processes:
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
    tail = []
    for path in logs:
        if path.exists():
            content = path.read_text(encoding="utf-8", errors="replace").splitlines()
            if content:
                tail.append(f"--- {path.name} (últimas 40 líneas) ---")
                tail.extend(content[-40:])
    return "\n".join(tail)


def percentile(values: list[float], fraction: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, int(round(fraction * (len(ordered) - 1))))
    return ordered[index]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--jobs", type=int, default=200,
                        help="trabajos únicos concurrentes (default 200)")
    parser.add_argument("--duplicates", type=int, default=40,
                        help="claves reenviadas en ráfaga (default 40)")
    parser.add_argument("--burst", type=int, default=8,
                        help="envíos simultáneos por clave duplicada (default 8)")
    parser.add_argument("--concurrency", type=int, default=16,
                        help="hilos de envío HTTP (default 16)")
    parser.add_argument("--workers", type=int, default=2,
                        help="procesos worker concurrentes (default 2)")
    parser.add_argument("--printers", type=int, default=2,
                        help="impresoras virtuales (default 2)")
    parser.add_argument("--timeout", type=float, default=180.0,
                        help="segundos máximos para drenar la cola")
    parser.add_argument("--report", default="",
                        help="ruta del informe JSON de resultados")
    args = parser.parse_args()
    if args.jobs < 1 or args.duplicates < 1 or args.burst < 2:
        parser.error("--jobs/--duplicates deben ser >0 y --burst >=2")
    expected_jobs = args.jobs + args.duplicates

    work = Path(tempfile.mkdtemp(prefix="lba-stress-"))
    data_dir = work / "data"
    logs = work / "logs"
    logs.mkdir(parents=True)
    env = {
        **os.environ,
        "PYTHONPATH": str(SERVER),
        "LBA_DATA_DIR": str(data_dir),
        "LBA_DB_PATH": str(data_dir / "lba.db"),
        "LBA_API_TOKEN": TOKEN,
        "LBA_ADMIN_PASSWORD": "stress-admin-password",
        "LBA_WORKER_POLL_S": "0.2",
        "PYTHONUNBUFFERED": "1",
    }
    processes: list[subprocess.Popen] = []
    log_paths: list[Path] = []
    api_port = free_port()
    api_base = f"http://127.0.0.1:{api_port}"

    print(f"== Estrés LBA: {expected_jobs} trabajos únicos "
          f"({args.jobs} nuevos + {args.duplicates} claves idempotentes) ==")
    print(f"   concurrencia={args.concurrency} workers={args.workers} "
          f"impresoras={args.printers} workdir={work}")

    try:
        print("· inicializando BD y límites")
        subprocess.run(
            [sys.executable, "-c", (
                "from app.database.db import init_db, get_sessionmaker\n"
                "from app.models import models\n"
                "init_db()\n"
                "s = get_sessionmaker()()\n"
                "models.set_setting(s, 'api_rate_limit', "
                "{'limit': 1000000, 'window_s': 60})\n"
                "s.commit()\n"
            )],
            cwd=SERVER, env=env, check=True, timeout=120,
        )

        printers = []
        for index in range(args.printers):
            printer = VirtualPrinter(
                f"Estrés {index + 1}", free_port(), work / f"paper-{index + 1}", logs)
            printer.start(env)
            printers.append(printer)
            print(f"· impresora virtual {printer.name} en 127.0.0.1:{printer.port}")

        api_log = (logs / "api.log").open("wb")
        log_paths.append(logs / "api.log")
        processes.append(subprocess.Popen(
            [sys.executable, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1",
             "--port", str(api_port), "--log-level", "warning"],
            cwd=SERVER, env=env, stdout=api_log, stderr=subprocess.STDOUT,
            start_new_session=True,
        ))
        wait_port("127.0.0.1", api_port)
        api = Api(api_base)

        for worker_index in range(args.workers):
            path = logs / f"worker-{worker_index + 1}.log"
            log_paths.append(path)
            handle = path.open("wb")
            processes.append(subprocess.Popen(
                [sys.executable, "-m", "app.worker"], cwd=SERVER, env=env,
                stdout=handle, stderr=subprocess.STDOUT, start_new_session=True))
        print(f"· API en {api_base} y {args.workers} worker(s)")

        deadline = time.time() + 45
        while True:
            try:
                status, payload = api.request("GET", "/api/v1/health")
                if status == 200:
                    break
            except OSError:
                pass
            if time.time() > deadline:
                raise RuntimeError("la API no respondió /api/v1/health")
            time.sleep(0.3)

        for index, printer in enumerate(printers):
            status, payload = api.request("POST", "/api/v1/printers", {
                "name": printer.name,
                "ip": "127.0.0.1",
                "port": printer.port,
                "profile": "simulator",
                "paper_width_mm": 80,
                "encoding": "CP850",
                "manufacturer": "LBA",
                "model": f"Virtual-{index + 1}",
            })
            assert status == 201, (status, payload)
            printer.external_id = payload["id"]
        print(f"· {len(printers)} impresoras registradas")

        def document(label: str) -> dict:
            return {"type": "ticket", "blocks": [
                {"type": "text", "value": label, "align": "center", "bold": True},
                {"type": "text", "value": "Prueba de estrés concurrente LBA"},
                {"type": "ruler", "char": "-"},
                {"type": "cut", "feed_before": 3},
            ]}

        def submit(printer: VirtualPrinter, key: str, label: str) -> tuple[int, float]:
            start = time.perf_counter()
            status, _ = api.request("POST", "/api/v1/jobs", {
                "printer_id": printer.external_id,
                "origin": "api",
                "idempotency_key": key,
                "document": document(label),
            })
            elapsed = time.perf_counter() - start
            for _ in range(4):
                if status != 503:
                    break
                time.sleep(0.15)
                start = time.perf_counter()
                status, _ = api.request("POST", "/api/v1/jobs", {
                    "printer_id": printer.external_id,
                    "origin": "api",
                    "idempotency_key": key,
                    "document": document(label),
                })
                elapsed = time.perf_counter() - start
            return status, elapsed

        tasks = []
        for index in range(args.jobs):
            printer = printers[index % len(printers)]
            tasks.append((printer, f"stress:job:{index}", f"STRESS JOB {index}"))
        for index in range(args.duplicates):
            printer = printers[index % len(printers)]
            for _ in range(args.burst):
                tasks.append((printer, f"stress:burst:{index}", f"STRESS BURST {index}"))
        random.Random(1234).shuffle(tasks)

        print(f"· enviando {len(tasks)} peticiones desde {args.concurrency} hilos")
        started = time.perf_counter()
        results: list[tuple[int, float]] = []
        with ThreadPoolExecutor(max_workers=args.concurrency) as pool:
            futures = [pool.submit(submit, printer, key, label)
                       for printer, key, label in tasks]
            for future in as_completed(futures):
                results.append(future.result())
        submit_seconds = time.perf_counter() - started

        statuses: dict[int, int] = {}
        for status, _ in results:
            statuses[status] = statuses.get(status, 0) + 1
        latencies = [elapsed for _, elapsed in results]
        accepted = statuses.get(202, 0)
        conflicts = statuses.get(409, 0)
        unexpected = {code: count for code, count in statuses.items()
                      if code not in (202, 409)}
        print(f"   responsables HTTP: {dict(sorted(statuses.items()))} "
              f"en {submit_seconds:.2f}s "
              f"({len(tasks) / submit_seconds:.0f} req/s)")

        if unexpected:
            raise AssertionError(f"respuestas no esperadas: {unexpected}")
        if accepted != expected_jobs:
            raise AssertionError(
                f"trabajos creados {accepted}, esperados {expected_jobs}")
        if conflicts != len(tasks) - expected_jobs:
            raise AssertionError(
                f"conflictos 409 {conflicts}, esperados {len(tasks) - expected_jobs}")

        print("· esperando a que la cola termine")
        deadline = time.time() + args.timeout
        while True:
            status, stats = api.request("GET", "/api/v1/stats")
            assert status == 200, (status, stats)
            queue = stats["queue"]
            pending = queue["pending"] + queue["processing"]
            if pending == 0:
                break
            if time.time() > deadline:
                raise AssertionError(f"la cola no se vació: {queue}")
            time.sleep(0.3)
        drain_seconds = time.perf_counter() - started

        if queue["sent"] != expected_jobs or queue["failed"] or queue["cancelled"]:
            raise AssertionError(f"estado final inesperado: {queue}")

        all_jobs = []
        offset = 0
        while True:
            status, page = api.request(
                "GET", f"/api/v1/jobs?limit=500&offset={offset}")
            assert status == 200, (status, page)
            all_jobs.extend(page["items"])
            if len(all_jobs) >= page["count"]:
                break
            offset += 500
        keys = [job["idempotency_key"] for job in all_jobs]
        if len(keys) != len(set(keys)):
            raise AssertionError("hay claves idempotentes duplicadas en la BD")
        if {job["status"] for job in all_jobs} != {"sent"}:
            raise AssertionError("algún trabajo no terminó en 'sent'")

        print("· verificando documentos en la impresora virtual")
        documents: list[dict] = []
        for printer in printers:
            documents.extend(printer.documents())
        if len(documents) != expected_jobs:
            raise AssertionError(
                f"la impresora virtual recibió {len(documents)} documentos, "
                f"esperaba {expected_jobs}")
        digests = {entry["sha256"] for entry in documents}
        if len(digests) != expected_jobs:
            raise AssertionError("documentos duplicados o perdidos (hashes repetidos)")
        for printer in printers:
            for entry in printer.documents():
                path = printer.save_dir / entry["bin_file"]
                content = path.read_bytes()
                if hashlib.sha256(content).hexdigest() != entry["sha256"]:
                    raise AssertionError(f"hash no coincide en {path}")
                if len(content) != entry["bytes"]:
                    raise AssertionError(f"tamaño no coincide en {path}")
                text_file = printer.save_dir / entry["text_file"]
                if not text_file.is_file() or not text_file.read_text(
                        encoding="utf-8", errors="replace").strip():
                    raise AssertionError(f"reconstrucción vacía: {text_file}")

        with sqlite3.connect(data_dir / "lba.db") as db:
            integrity = db.execute("PRAGMA integrity_check").fetchone()[0]
            job_rows = db.execute("SELECT COUNT(*) FROM jobs").fetchone()[0]
            duplicate_keys = db.execute(
                "SELECT COUNT(*) FROM (SELECT idempotency_key FROM jobs "
                "GROUP BY idempotency_key HAVING COUNT(*) > 1)"
            ).fetchone()[0]
        if integrity != "ok":
            raise AssertionError(f"SQLite integrity_check: {integrity}")
        if job_rows != expected_jobs:
            raise AssertionError(f"filas jobs={job_rows}, esperadas {expected_jobs}")
        if duplicate_keys:
            raise AssertionError(f"{duplicate_keys} claves duplicadas en SQLite")

        report = {
            "ok": True,
            "jobs_unique": expected_jobs,
            "requests": len(tasks),
            "concurrency": args.concurrency,
            "workers": args.workers,
            "printers": args.printers,
            "http_statuses": {str(k): v for k, v in sorted(statuses.items())},
            "submit_seconds": round(submit_seconds, 3),
            "drain_seconds": round(drain_seconds, 3),
            "requests_per_second": round(len(tasks) / submit_seconds, 1),
            "jobs_per_second": round(expected_jobs / drain_seconds, 1),
            "latency_ms": {
                "p50": round(percentile(latencies, 0.50) * 1000, 1),
                "p95": round(percentile(latencies, 0.95) * 1000, 1),
                "max": round(max(latencies) * 1000, 1),
            },
            "queue": queue,
            "documents": len(documents),
            "sqlite_integrity": integrity,
        }
        if args.report:
            Path(args.report).parent.mkdir(parents=True, exist_ok=True)
            Path(args.report).write_text(json.dumps(report, indent=2) + "\n",
                                         encoding="utf-8")
            print(f"· informe: {args.report}")
        print("ESTRÉS OK — " + json.dumps(
            {k: report[k] for k in ("jobs_unique", "requests_per_second",
                                    "jobs_per_second", "latency_ms", "documents")},
            ensure_ascii=False))
        return 0
    except Exception as exc:
        print(f"FALLO: {type(exc).__name__}: {exc}", file=sys.stderr)
        tail = stop_all(processes, log_paths)
        if tail:
            print(tail, file=sys.stderr)
        return 1
    finally:
        stop_all(processes, log_paths)


if __name__ == "__main__":
    raise SystemExit(main())
