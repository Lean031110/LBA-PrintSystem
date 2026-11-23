/**
 * LBA Print Connector — serializador de plantillas (espejo JS del Python
 * models/lba_template.py::to_blocks).
 *
 * La MISMA estructura de bloques de la plantilla alimenta:
 *  - la vista previa del diseñador (papel térmico, backend Odoo),
 *  - la impresión de prueba,
 *  - la impresión REAL del TPV (esta función).
 *
 * Seguridad: los "campos dinámicos" son una LISTA BLANQUEADA aquí y en el
 * backend; nunca se evalúa JS/Python/Jinja arbitrario del usuario.
 */
const MAX_TEXT = 3000;

export const LBA_FIELD_WHITELIST = [
    "company.name",
    "company.address",
    "order.ref",
    "order.cashier",
    "order.table",
    "order.customer_count",
    "order.datetime",
    "order.subtotal",
    "order.discount",
    "order.total",
    "order.change",
    "order.note",
    "department.name",
];

export const LBA_TABLE_WHITELIST = [
    "lines.new",
    "lines.cancelled",
    "lines.noteUpdate",
    "lines.all",
    "payments.list",
];

export const LBA_CONDITION_WHITELIST = [
    "order.has_table",
    "order.has_note",
    "order.has_change",
    "order.has_payments",
    "order.is_bill",
    "order.is_reprint",
    "order.has_cancelled",
];

function clip(str, max = MAX_TEXT) {
    const s = String(str ?? "");
    return s.length > max ? s.slice(0, max - 1) + "…" : s;
}

function lookup(data, section, key) {
    const node = data?.[section];
    if (node && typeof node === "object" && key in node) {
        const v = node[key];
        return v === undefined || v === null ? "" : v;
    }
    return "";
}

/** Valor de un campo de la lista blanca (nada se evalúa). */
export function fieldValue(fieldKey, data) {
    if (!LBA_FIELD_WHITELIST.includes(fieldKey)) {
        return "";
    }
    const [section, key] = fieldKey.split(".");
    if (section === "company" || section === "order" || section === "department") {
        return String(lookup(data, section, key));
    }
    return "";
}

/** Valor booleano de una condición de la lista blanca. */
export function conditionValue(conditionKey, data) {
    if (!LBA_CONDITION_WHITELIST.includes(conditionKey)) {
        return false;
    }
    const [section, key] = conditionKey.split(".");
    return Boolean(lookup(data, section, key));
}

function textBlock(block, value) {
    return {
        type: "text",
        value: clip(value),
        align: block.align || "left",
        bold: Boolean(block.bold),
        width: block.size_width === 2 ? 2 : 1,
        height: block.size_height === 2 ? 2 : 1,
    };
}

function resolveValue(block, data) {
    if (block.value_origin === "field") {
        return fieldValue(block.field_key, data);
    }
    return block.value_text || "";
}

function tableRows(tableKey, data) {
    const rows = [];
    if (!LBA_TABLE_WHITELIST.includes(tableKey)) {
        return rows;
    }
    if (tableKey === "payments.list") {
        for (const payment of data?.payments || []) {
            rows.push(`${payment?.name || ""}: ${payment?.amount ?? ""}`);
        }
        return rows;
    }
    const section = tableKey.split(".")[1]; // new | cancelled | all
    for (const line of data?.lines?.[section] || []) {
        const qty = line?.qty ?? "";
        const name = line?.name ?? "";
        const price = line?.price ?? "";
        let lineText = qty ? `${qty} x ${name}` : `${name}`;
        if (price) {
            lineText = `${lineText}  ${price}`;
        }
        rows.push(lineText);
        if (line?.note) {
            rows.push(`   » ${line.note}`);
        }
    }
    return rows;
}

/**
 * Serializa una plantilla (estructura devuelta por /lba_print/templates)
 * con los datos del pedido → documento de ticket con SOLO bloques
 * primitivos que LBA Print Server sabe renderizar.
 *
 * @param {Object} template {blocks:[{block_type, ...,
 *   children:[...]}, ...]}
 * @param {Object} data contrato de datos (ticketDataFromOrder…)
 * @returns {{type:"ticket", blocks:Array}}
 */
export function templateToDocument(template, data) {
    const out = [];
    const blocks = template?.blocks || template?.block_ids || [];
    for (const block of blocks) {
        emitBlock(block, data, out);
    }
    if (!out.length) {
        throw new Error("La plantilla no produce bloques");
    }
    return { type: "ticket", blocks: out };
}

function emitBlock(block, data, out) {
    const btype = block.block_type;
    switch (btype) {
        case "text":
            out.push(textBlock(block, block.value_text || ""));
            break;
        case "field":
            out.push(textBlock(block, fieldValue(block.field_key, data)));
            break;
        case "ruler":
            out.push({ type: "ruler", char: (block.ruler_char || "-").slice(0, 1) });
            break;
        case "ruler_double":
            out.push({ type: "ruler", char: "=" });
            break;
        case "spacer":
        case "feed":
            out.push({ type: "feed", lines: Math.max(1, block.feed_lines || block.spacer_lines || 1) });
            break;
        case "cut":
            out.push({ type: "cut", feed_before: Math.max(0, block.cut_feed_before || 0) });
            break;
        case "qr":
            out.push({
                type: "qr",
                value: clip(String(resolveValue(block, data)), 400),
                size: Math.max(3, Math.min(11, block.qr_size || 6)),
            });
            break;
        case "barcode":
            out.push({
                type: "barcode",
                value: clip(String(resolveValue(block, data)), 100),
                symbology: block.symbology || "CODE128",
            });
            break;
        case "image":
            if (block.image) {
                out.push({ type: "image", source: "base64", data: block.image, width: 384 });
            }
            break;
        case "conditional":
            if (conditionValue(block.condition_key, data)) {
                for (const child of block.children || block.child_ids || []) {
                    emitBlock(child, data, out);
                }
            }
            break;
        case "table":
            for (const row of tableRows(block.table_key, data)) {
                out.push({ type: "text", value: row, align: "left", bold: false, width: 1, height: 1 });
            }
            break;
    }
}

function lineData(line) {
    return {
        qty: line?.quantity ?? line?.getQuantity?.() ?? "",
        name: line?.getFullProductName?.() || line?.full_product_name ||
            line?.product_id?.display_name || line?.product_id?.name || line?.name || "",
        price: line?.currencyDisplayPriceIncl ?? "",
        note: line?.customer_note || line?.note || "",
    };
}

/** Contrato común del diseñador, relleno con un pedido POS real. */
export function receiptTemplateData(order, options = {}) {
    const lines = order?.lines || order?.orderlines || [];
    const payments = order?.paymentlines || [];
    const table = order?.table_id?.name || "";
    const note = order?.general_customer_note || "";
    const change = order?.change ?? "";
    return {
        company: {
            name: order?.company?.name || "",
            address: order?.company?.contact_address || order?.company?.street || "",
        },
        order: {
            ref: order?.getName?.() || order?.preparationName || order?.uuid || "",
            cashier: order?.getCashierName?.() || "",
            table,
            customer_count: order?.customer_count || "",
            datetime: order?.date_order || "",
            subtotal: order?.getTotalWithoutTax?.() ?? "",
            discount: order?.getTotalDiscount?.() ?? "",
            total: order?.currencyDisplayPriceIncl ?? order?.getTotalWithTax?.() ?? "",
            change,
            note,
            has_table: Boolean(table),
            has_note: Boolean(note),
            has_change: Boolean(change && Number(change) !== 0),
            has_payments: payments.length > 0,
            is_bill: Boolean(options.bill),
            is_reprint: Boolean(options.reprint),
            has_cancelled: false,
        },
        department: { name: options.departmentName || "" },
        payments: payments.map((payment) => ({
            name: payment?.payment_method_id?.name || payment?.name || "",
            amount: payment?.currencyDisplayAmountIncl ?? payment?.amount ?? "",
        })),
        lines: { all: lines.map(lineData), new: [], cancelled: [] },
    };
}

/** Datos del delta producido por generateOrderChange del core Odoo. */
export function kitchenTemplateData(order, orderData, changes, options = {}) {
    const data = receiptTemplateData(order, options);
    const newLines = (changes?.new || []).map(lineData);
    const cancelled = (changes?.cancelled || []).map((line) => {
        const item = lineData(line);
        return { ...item, qty: Math.abs(Number(item.qty) || 0) };
    });
    const noteUpdate = (changes?.noteUpdate || []).map(lineData);
    data.order.ref = orderData?.pos_reference || data.order.ref;
    data.order.cashier = orderData?.employee_name || data.order.cashier;
    data.order.datetime = orderData?.time || data.order.datetime;
    data.order.note = orderData?.general_customer_note || data.order.note;
    data.order.has_note = Boolean(data.order.note || orderData?.internal_note);
    data.order.has_cancelled = cancelled.length > 0;
    data.lines = {
        new: newLines,
        cancelled,
        noteUpdate,
        all: [...newLines, ...cancelled, ...noteUpdate],
    };
    return data;
}

let operationFallbackSequence = 0;

export function newOperationId() {
    if (globalThis.crypto?.randomUUID) {
        return globalThis.crypto.randomUUID();
    }
    operationFallbackSequence += 1;
    return `${Date.now().toString(36)}-${operationFallbackSequence.toString(36)}`;
}

function stableHash(value) {
    let a = 2166136261;
    let b = 2246822519;
    for (let i = 0; i < value.length; i++) {
        const code = value.charCodeAt(i);
        a = Math.imul(a ^ code, 16777619);
        b = Math.imul(b ^ (code + i), 3266489917);
    }
    return `${(a >>> 0).toString(36)}${(b >>> 0).toString(36)}`;
}

/** ID determinista para el mismo delta; el alcance separa destino/evento. */
export function buildKitchenEventId(order, change, slot) {
    const lineSignature = (lines) => (lines || []).map((line) => [
        line?.uuid || line?.preparationKey || line?.product_id?.id || line?.name || "",
        line?.quantity ?? line?.qty ?? "",
        line?.note || "",
        line?.customer_note || "",
    ]);
    const source = JSON.stringify({
        base: order?.last_order_preparation_change?.metadata?.serverDate || "initial",
        slot,
        new: lineSignature(change?.new),
        cancelled: lineSignature(change?.cancelled),
        noteUpdate: lineSignature(change?.noteUpdate),
        internal: change?.internal_note || "",
        general: change?.general_customer_note || "",
    });
    return `evt-${stableHash(source)}`;
}

/** La misma operationId se reutiliza en retries; la reimpresión recibe otra. */
export function buildIdempotencyOpId(kind, order, options = {}) {
    const orderId = String(order?.uuid || "na").slice(0, 96);
    const eventId = String(options.eventId || newOperationId()).slice(0, 72);
    const scope = options.scope ? `:${String(options.scope).slice(0, 24)}` : "";
    return `lba:${orderId}:${kind}:${eventId}${scope}`.slice(0, 200);
}
