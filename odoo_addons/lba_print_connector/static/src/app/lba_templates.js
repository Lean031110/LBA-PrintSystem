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
    const blocks = template?.blocks || [];
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
                for (const child of block.children || []) {
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

/**
 * Clave de idempotencia del TPV (espejo del controlador
 * controllers/main.py::_build_key): op_id SEMÁNTICO por tipo de acción.
 */
export function buildIdempotencyOpId(kind, order, options = {}) {
    switch (kind) {
        case "receipt":
            return `${order?.uuid || "na"}:${options.bill ? "bill" : "payment"}`;
        case "kitchen":
        case "delta": {
            const seq = options.changeSeq || 0;
            return `${order?.uuid || "na"}:change:${seq}`;
        }
        case "reprint":
        case "test":
            return crypto.randomUUID?.() || `${Date.now()}-${Math.random()}`;
        default:
            return `${order?.uuid || "na"}:${kind}`;
    }
}
