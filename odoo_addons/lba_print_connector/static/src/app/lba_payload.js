/**
 * LBA Print Connector — constructores de payload estructurado (JSON).
 *
 * Odoo NUNCA genera bytes ESC/POS: solo documentos declarativos con bloques
 * (text/qr/barcode/image/feed/cut) que el LBA Print Server renderiza con
 * python-escpos (docs/API_CONTRACT.md).
 *
 * Campos usados verificados en el código real de Odoo 19:
 *  - Order: getCashierName() (pos_order.js L210), getName(), company,
 *    currencyDisplayPriceIncl, paymentlines, change, getTotalDiscount(),
 *    table_id/customer_count (pos_restaurant), general_customer_note.
 *  - Deltas: generateOrderChange() → {orderData, changes{new,cancelled,
 *    noteUpdate}} (pos_store.js L2170-2254).
 */
import { _t } from "@web/core/l10n/translation";

const MAX_TEXT = 3000; // margen bajo el límite del servidor (4000)

function clip(str, max = 200) {
    const s = String(str ?? "");
    return s.length > max ? s.slice(0, max - 1) + "…" : s;
}

function text(value, opts = {}) {
    return { type: "text", value: clip(String(value ?? ""), MAX_TEXT), ...opts };
}
function ruler(char = "-") {
    return { type: "ruler", char };
}
function feed(lines) {
    return { type: "feed", lines };
}
function cut(feedBefore = 3) {
    return { type: "cut", feed_before: feedBefore };
}

function lineQty(line) {
    return line.quantity ?? line.getQuantity?.() ?? 0;
}

function lineName(line) {
    return clip(
        line.getFullProductName?.() || line.full_product_name ||
        line.name || line.product_id?.display_name || "", 120);
}

function lineVariants(line) {
    const av = line.attribute_value_names || line.attribute_value_ids || [];
    if (Array.isArray(av) && av.length) {
        const names = av
            .map((a) => (typeof a === "string" ? a : a?.name))
            .filter(Boolean);
        return names.length ? names.join("/") : "";
    }
    return "";
}

/** Recibo de cliente tras validar el pago (o bill pre-pago). */
export function buildReceiptDocument(order, options = {}) {
    const config = order.config || {};
    const blocks = [];

    blocks.push(text(order.company?.name || "", { align: "center", bold: true, width: 2, height: 1 }));
    if (config.receipt_header) {
        blocks.push(text(config.receipt_header, { align: "center" }));
    }
    blocks.push(text(order.getName?.() ? `Ticket ${order.getName()}` : _t("Receipt"), { align: "center" }));
    blocks.push(text(`${_t("Camarero")}: ${order.getCashierName?.() || ""}`, { align: "left" }));
    if (order.table_id?.name) {
        blocks.push(text(`${_t("Mesa")}: ${order.table_id.name} · ${_t("Comensales")}: ${order.customer_count || 1}`, { align: "left" }));
    }
    blocks.push(ruler("="));

    const lines = order.lines || order.orderlines || [];
    for (const line of lines) {
        const qty = lineQty(line);
        const name = lineName(line);
        const variants = lineVariants(line);
        const label = `${qty} x ${name}${variants ? ` (${variants})` : ""}`;
        const price = line.currencyDisplayPriceIncl ?? "";
        blocks.push(text(`${label}${price ? `  ${price}` : ""}`, { align: "left" }));
        if (line.customer_note || line.note) {
            const note = line.customer_note || line.note;
            blocks.push(text(`   » ${note}`, { align: "left" }));
        }
    }
    blocks.push(ruler("="));
    blocks.push(text(`${_t("TOTAL")}: ${order.currencyDisplayPriceIncl ?? ""}`, { bold: true, align: "right" }));

    const paymentlines = order.paymentlines || [];
    for (const pl of paymentlines) {
        const name = pl.payment_method_id?.name || pl.name || "";
        const amount = pl.currencyDisplayAmountIncl ?? pl.amount ?? "";
        blocks.push(text(`${name}: ${amount}`, { align: "left" }));
    }
    if (order.change) {
        blocks.push(text(`${_t("Cambio")}: ${order.change}`, { align: "left" }));
    }
    if (!options.basic && config.receipt_footer) {
        blocks.push(text(config.receipt_footer, { align: "center" }));
    }
    blocks.push(feed(options.bill ? 2 : 3));
    blocks.push(cut(options.bill ? 2 : 3));
    return { type: "ticket", blocks };
}

/** Comanda de cocina a partir del {orderData, changes} del core. */
export function buildKitchenDocument(order, orderData, changes, options = {}) {
    const blocks = [];

    blocks.push(text(`${_t("COMANDA")}${options.reprint ? ` (${_t("REIMPRESIÓN")})` : ""}`, { align: "center", bold: true, width: 2, height: 1 }));
    if (options.departmentName) {
        blocks.push(text(options.departmentName, { align: "center", bold: true }));
    }
    blocks.push(text(orderData?.pos_reference || order?.getName?.() || "", { align: "left", bold: true }));
    blocks.push(text(`${_t("Camarero")}: ${orderData?.employee_name || ""}`, { align: "left" }));
    if (order?.table_id?.name) {
        blocks.push(text(`${_t("Mesa")}: ${order.table_id.name} · ${_t("Comensales")}: ${order.customer_count || 1}`, { align: "left" }));
    }
    if (orderData?.tracking_number) {
        blocks.push(text(`${_t("Seguimiento")}: ${orderData.tracking_number}`, { align: "left" }));
    }
    if (orderData?.time) {
        blocks.push(text(`${_t("Hora")}: ${orderData.time}`, { align: "left" }));
    }
    if (orderData?.general_customer_note) {
        blocks.push(text(`${_t("Nota del pedido")}: ${orderData.general_customer_note}`, { align: "left" }));
    }
    if (orderData?.internal_note) {
        blocks.push(text(`${_t("Nota interna")}: ${orderData.internal_note}`, { align: "left" }));
    }
    blocks.push(ruler("="));

    const emitLines = (items, title, sign) => {
        if (!items || !items.length) {
            return;
        }
        blocks.push(text(title, { bold: true }));
        for (const item of items) {
            const qty = Math.abs(lineQty(item));
            const name = lineName(item);
            const variants = lineVariants(item);
            const prefix = sign === "-" ? "-" : "";
            blocks.push(text(`${prefix}${qty} x ${name}${variants ? ` (${variants})` : ""}`, { align: "left" }));
            if (item.customer_note) {
                blocks.push(text(`   » ${item.customer_note}`, { align: "left" }));
            }
            if (item.note) {
                blocks.push(text(`   * ${item.note}`, { align: "left" }));
            }
        }
        blocks.push(ruler("-"));
    };

    emitLines(changes?.new, _t("NUEVOS"), "+");
    emitLines(changes?.cancelled, _t("CANCELADOS"), "-");
    if (changes?.noteUpdate?.length) {
        blocks.push(text(_t("NOTAS MODIFICADAS"), { bold: true }));
        for (const item of changes.noteUpdate) {
            blocks.push(text(`${lineName(item)}`, { align: "left" }));
            if (item.note || item.customer_note) {
                blocks.push(text(`   » ${item.note || item.customer_note}`, { align: "left" }));
            }
        }
        blocks.push(ruler("-"));
    }
    blocks.push(feed(2));
    blocks.push(cut(2));
    return { type: "ticket", blocks };
}
