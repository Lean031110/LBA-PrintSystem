/**
 * LBA Print Connector — puntos de extensión del TPV (parches OWL oficiales).
 *
 * SE PARCHA CON `patch()` de @web/core/utils/patch (patrón idéntico al que
 * usa pos_restaurant sobre PosStore) y SIEMPRE se conserva `super` como
 * respaldo: si LBA no está configurado, el TPV se comporta 100% nativo.
 *
 * Puntos verificados en point_of_sale/static/src/app/services/pos_store.js
 * (rama 19.0, commit 0a722221e6):
 *   - printReceipt({...}) L1969-2005  → recibo tras pago / bill (nb_print).
 *   - printChanges(order, orderChange, reprint, printers) L2255-2320
 *     → comandas por impresora (generateOrderChange + lastPrints).
 * Los deltas de modificación/cancelación NO se re-implementan: se consumen
 * tal cual los produce el core (changes.new / changes.cancelled /
 * changes.noteUpdate).
 */
import { patch } from "@web/core/utils/patch";
import { rpc } from "@web/core/network/rpc";
import { _t } from "@web/core/l10n/translation";
import { PosStore } from "@point_of_sale/app/services/pos_store";
import { buildReceiptDocument, buildKitchenDocument } from "./lba_payload";

function notifyError(pos, printerName, message) {
    const msg = `${printerName || "LBA"}: ${message || _t("sin conexión (queda en cola)")}`;
    // PosStore tiene el servicio notification (patrón del core:
    // order_payment_validation.js L352 this.pos.notification.add)
    if (pos?.notification?.add) {
        pos.notification.add(msg, { type: "danger", sticky: false });
    }
}

patch(PosStore.prototype, {
    /**
     * RECIBO tras validar el pago (y bill pre-pago).
     * Si la TPV no tiene LBA activo → camino nativo exacto (super).
     */
    async printReceipt({
        basic = false,
        order = this.getOrder(),
        printBillActionTriggered = false,
    } = {}) {
        const cfg = this.config || {};
        if (!(cfg.lba_active && cfg.lba_receipt_printer_id && order)) {
            return super.printReceipt({ basic, order, printBillActionTriggered });
        }
        let ok = false;
        try {
            const document = buildReceiptDocument(order, {
                basic,
                bill: printBillActionTriggered,
            });
            const res = await rpc("/lba_print/jobs", {
                printer_id: cfg.lba_receipt_printer_id,
                kind: "receipt",
                order_ref: order.getName?.() || order.uuid || "",
                order_uuid: order.uuid,
                document,
            });
            if (res && res.state === "sent") {
                ok = true;
            } else if (res && res.state === "pending") {
                ok = true; // encolado en Odoo: se imprimirá al reconectar LBA
                notifyError(this, res.error || _t("LBA no disponible"));
            } else {
                notifyError(this, (res && res.error) || _t("error"));
            }
        } catch (err) {
            notifyError(this, err?.message || err);
        }
        // Misma semántica de nb_print que el método nativo (L1984-1997):
        if (!printBillActionTriggered) {
            if (ok) {
                const count = order.nb_print ? order.nb_print + 1 : 1;
                if (order.isSynced) {
                    const wasDirty = order.isDirty();
                    await this.data.write("pos.order", [order.id], {
                        nb_print: count,
                    });
                    if (!wasDirty) {
                        order._dirty = false;
                    }
                } else {
                    order.nb_print = count;
                }
            }
        } else if (!order.nb_print) {
            order.nb_print = 0;
        }
        return ok;
    },

    /**
     * COMANDAS al enviar el pedido ("Order"), reimpresiones y deltas de
     * modificación/cancelación. Cada pos.printer con lba_printer_id va por
     * LBA; el resto conserva el camino nativo (super con sub-lista).
     */
    async printChanges(order, orderChange, reprint = false, printers = this.unwatched.printers) {
        const list = printers || [];
        const lbaPrinters = list.filter((p) => p && p.config && p.config.lba_printer_id);
        const others = list.filter((p) => !(p && p.config && p.config.lba_printer_id));

        let isPrinted = false;
        for (const printer of lbaPrinters) {
            for (const change of orderChange || []) {
                const { orderData, changes } = this.generateOrderChange(
                    order,
                    change,
                    printer.config.product_categories_ids,
                    reprint
                );
                const document = buildKitchenDocument(order, orderData, changes, {
                    reprint,
                    departmentName: printer.config.name,
                });
                try {
                    const res = await rpc("/lba_print/jobs", {
                        printer_id: printer.config.lba_printer_id,
                        kind: reprint ? "reprint" : "kitchen",
                        order_ref: orderData?.pos_reference || order?.uuid || "",
                        order_uuid: order?.uuid,
                        document,
                    });
                    if (res && (res.state === "sent" || res.state === "pending")) {
                        isPrinted = true;
                        if (res.state === "pending") {
                            notifyError(this, printer.config.name, res.error);
                        }
                    } else {
                        notifyError(this, printer.config.name, res?.error);
                    }
                } catch (err) {
                    notifyError(this, printer.config.name, err?.message || err);
                }
            }
        }

        if (others.length) {
            const othersPrinted = await super.printChanges(
                order, orderChange, reprint, others
            );
            // el super ya gestiona lastPrints/RetryPrintPopup para las nativas
            isPrinted = isPrinted || othersPrinted;
        } else if (!reprint && isPrinted && (orderChange || []).length) {
            // mismo contrato nativo (L2291): registrar el cambio impreso
            order.uiState.lastPrints.push(orderChange[0]);
        }
        return isPrinted;
    },
});
