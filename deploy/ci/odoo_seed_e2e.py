# -*- coding: utf-8 -*-
# Ejecutar con: odoo-bin shell --no-http --database=lba_e2e < odoo_seed_e2e.py
# Prepara el usuario admin, el servidor LBA, sincroniza la impresora virtual y
# asigna esa impresora a las plantillas para que la prueba de navegador imprima.
import os

BASE_URL = os.environ["LBA_E2E_BASE_URL"].rstrip("/")
PORT = int(os.environ["LBA_E2E_PORT"])
TOKEN = os.environ["LBA_E2E_TOKEN"]

admin = env.ref("base.user_admin")
admin.write({"login": "admin", "password": "admin"})

server = env["lba.print.server"].search([("name", "=", "LBA E2E")], limit=1)
if not server:
    server = env["lba.print.server"].create({
        "name": "LBA E2E",
        "base_url": BASE_URL,
        "port": PORT,
        "api_token": TOKEN,
    })
else:
    server.write({"base_url": BASE_URL, "port": PORT, "api_token": TOKEN})

server.action_test_connection()
print("conexión:", server.state, server.last_message)
assert server.state == "online", f"servidor LBA offline: {server.last_message}"

server.action_sync_printers()
print("sincronización:", server.last_message)
printers = env["lba.print.printer"].search([])
print("impresoras:", printers.mapped("name"))
printer = printers.filtered(lambda item: "Cocina E2E" in item.name)[:1]
assert printer, "la impresora virtual no se sincronizó"

templates = env["lba.print.template"].search([])
templates.write({"printer_id": printer.id})
print("plantillas con impresora:", len(templates))

env.cr.commit()
print("SEED OK", server.id, printer.id, printer.external_id)
