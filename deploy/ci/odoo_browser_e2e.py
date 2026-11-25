#!/usr/bin/env python3
"""E2E de navegador: Odoo 19 → addon LBA → servidor LBA → impresora virtual.

Acciones reales en Chromium (Playwright):

1. login en Odoo como administrador;
2. abrir la lista de impresoras sincronizadas del addon;
3. "Probar conexión" contra el servidor LBA y comprobar la notificación;
4. "Sincronizar impresoras";
5. abrir una plantilla, "Impresión de prueba" → "Enviar a la impresora";
6. esperar a que la cola marque ``sent`` y a que la impresora virtual escriba
   el documento en disco (papel virtual: .escpos.bin + .txt).

Uso:
    python deploy/ci/odoo_browser_e2e.py \
        --odoo-url http://127.0.0.1:8069 \
        --lba-url http://127.0.0.1:18000 \
        --documents-dir "$RUNNER_TEMP/printer-documents" \
        --screenshots-dir "$RUNNER_TEMP/screenshots"

Requiere ``LBA_E2E_TOKEN`` en el entorno. Sale con código 1 y genera captura
si algo falla.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import sys
import time
import urllib.error
import urllib.request

from playwright.sync_api import Page, expect, sync_playwright

TOKEN = os.environ.get("LBA_E2E_TOKEN", "")


def api_get(url: str) -> dict:
    request = urllib.request.Request(url)
    request.add_header("Authorization", f"Bearer {TOKEN}")
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.load(response)


def jobs_sent(base: str) -> list[dict]:
    payload = api_get(f"{base}/api/v1/jobs?status=sent&limit=200")
    return payload.get("items", [])


def documents(directory: Path) -> list[Path]:
    if not directory.is_dir():
        return []
    return sorted(directory.glob("*.escpos.bin"))


def goto_action(page: Page, odoo: str, action: str) -> None:
    """Abre una acción por xmlid; tolera la ruta nueva /odoo y la histórica /web#."""
    errors: list[Exception] = []
    for url in (
        f"{odoo}/odoo/action-lba_print_connector.{action}",
        f"{odoo}/web#action=lba_print_connector.{action}",
    ):
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=90_000)
            page.wait_for_selector(".o_list_view, .o_form_view", timeout=90_000)
            page.wait_for_timeout(500)
            return
        except Exception as exc:  # probar la siguiente ruta
            errors.append(exc)
    raise RuntimeError(f"no se pudo abrir {action}: {errors[-1]}")


def click_button(page: Page, name: str, label: str, root=None) -> None:
    scope = root or page
    locator = scope.locator(f"button[name='{name}']")
    if locator.count() == 0:
        locator = scope.get_by_role("button", name=label)
    expect(locator.first).to_be_visible(timeout=45_000)
    locator.first.click()


def wait_notification(page: Page, text: str) -> None:
    notification = page.locator(".o_notification").filter(has_text=text)
    expect(notification.first).to_be_visible(timeout=45_000)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--odoo-url", default="http://127.0.0.1:8069")
    parser.add_argument("--lba-url", default="http://127.0.0.1:18000")
    parser.add_argument("--documents-dir", required=True)
    parser.add_argument("--screenshots-dir", required=True)
    parser.add_argument("--timeout", type=float, default=120.0)
    args = parser.parse_args()
    odoo = args.odoo_url.rstrip("/")
    lba = args.lba_url.rstrip("/")
    doc_dir = Path(args.documents_dir)
    shots = Path(args.screenshots_dir)
    shots.mkdir(parents=True, exist_ok=True)
    if not TOKEN:
        raise SystemExit("LBA_E2E_TOKEN no está definido")

    before_jobs = {job["id"] for job in jobs_sent(lba)}
    before_docs = {path.name for path in documents(doc_dir)}

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 1000})
        page.set_default_timeout(60_000)
        page_errors: list[str] = []
        page.on("pageerror", lambda error: page_errors.append(str(error)))

        def screenshot(name: str) -> None:
            page.screenshot(path=str(shots / f"{name}.png"), full_page=True)

        try:
            print("· login en Odoo")
            page.goto(f"{odoo}/web/login?db=lba_e2e",
                      wait_until="domcontentloaded", timeout=90_000)
            page.fill("input[name='login']", "admin")
            page.fill("input[name='password']", "admin")
            page.click("button[type='submit']")
            page.wait_for_selector(".o_main_navbar", timeout=90_000)
            screenshot("01-login")

            print("· lista de impresoras del addon")
            goto_action(page, odoo, "action_lba_printer")
            expect(page.locator(".o_data_row").filter(
                has_text="Cocina E2E").first).to_be_visible(timeout=60_000)
            screenshot("02-impresoras")

            print("· servidor LBA: Probar conexión + Sincronizar")
            goto_action(page, odoo, "action_lba_server")
            expect(page.locator(".o_data_row").first).to_be_visible(timeout=60_000)
            page.locator(".o_data_row").first.click()
            page.wait_for_selector(".o_form_view", timeout=60_000)
            click_button(page, "action_test_connection", "Probar conexión")
            wait_notification(page, "Conexión verificada")
            screenshot("03-conexion")
            click_button(page, "action_sync_printers", "Sincronizar impresoras")
            wait_notification(page, "Sincroniz")
            screenshot("04-sincronizacion")

            print("· plantilla: Impresión de prueba en la impresora virtual")
            goto_action(page, odoo, "action_lba_template")
            expect(page.locator(".o_data_row").first).to_be_visible(timeout=60_000)
            page.locator(".o_data_row").first.click()
            page.wait_for_selector(".o_form_view", timeout=60_000)
            click_button(page, "action_test_print", "Impresión de prueba")
            modal = page.locator(".modal").filter(
                has_text="Impresión de prueba").first
            expect(modal).to_be_visible(timeout=60_000)
            screenshot("05-asistente")
            click_button(page, "action_send_test_print", "Enviar a la impresora",
                         root=modal)
            wait_notification(page, "Prueba en cola")
            screenshot("06-enviado")

            print("· esperando bytes en la impresora virtual y estado sent")
            deadline = time.time() + args.timeout
            new_job = None
            while time.time() < deadline:
                new_jobs = [job for job in jobs_sent(lba)
                            if job["id"] not in before_jobs]
                new_docs = [path for path in documents(doc_dir)
                            if path.name not in before_docs]
                if new_jobs and new_docs:
                    new_job = new_jobs[0]
                    break
                time.sleep(1)
            if not new_job:
                raise RuntimeError(
                    "no apareció un trabajo sent + documento en la impresora virtual")
            print(f"  job {new_job['id']} → {new_job['status']}, "
                  f"{new_job['bytes_len']} bytes")

            new_docs = [path for path in documents(doc_dir)
                        if path.name not in before_docs]
            text_file = new_docs[-1].with_suffix("").with_suffix(".txt")
            text = text_file.read_text(encoding="utf-8", errors="replace")
            assert len(text.strip()) >= 20, f"documento vacío: {text_file}"
            print(f"  documento: {new_docs[-1].name} ({len(text)} chars de texto)")
            screenshot("07-documento-impreso")

            job = api_get(f"{lba}/api/v1/jobs/{new_job['id']}")
            assert job["status"] == "sent" and job["bytes_len"] > 0, job
            if page_errors:
                raise RuntimeError(f"errores JavaScript en Odoo: {page_errors}")
            print("BROWSER E2E OK")
            return 0
        except Exception:
            screenshot("99-error")
            print("página actual:", page.url, file=sys.stderr)
            print("errores JS:", page_errors, file=sys.stderr)
            raise
        finally:
            browser.close()


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"FALLO: {type(exc).__name__}: {exc}", file=sys.stderr)
        raise SystemExit(1)
