/**
 * Integración POS LBA: la configuración de departamentos es la única fuente
 * de ruteo LBA; las impresoras Odoo nativas siguen pasando por `super`.
 */
import { patch } from "@web/core/utils/patch";
import { rpc } from "@web/core/network/rpc";
import { _t } from "@web/core/l10n/translation";
import { PosStore } from "@point_of_sale/app/services/pos_store";
import { buildKitchenDocument, buildReceiptDocument } from "./lba_payload";
import { canFailoverPrinter } from "./lba_routing";
import {
    buildKitchenEventId,
    buildIdempotencyOpId,
    kitchenTemplateData,
    newOperationId,
    receiptTemplateData,
    templateToDocument,
} from "./lba_templates";

const receiptOperations = new WeakMap();
const changeOperations = new WeakMap();

function notifyError(pos, printerName, message) {
    const msg = `${printerName || "LBA"}: ${message || _t("no se pudo encolar el trabajo")}`;
    if (pos?.notification?.add) {
        pos.notification.add(msg, { type: "danger", sticky: false });
    }
}

function recordId(record) {
    if (typeof record === "number") {
        return record;
    }
    return record?.id || false;
}

function relationRows(value) {
    if (Array.isArray(value)) {
        return value;
    }
    if (value?.getIterator) {
        return [...value.getIterator()];
    }
    return value ? [value] : [];
}

function recordsFor(store, model) {
    return store.models?.[model]?.getAll?.() || [];
}

function stableOperationId(map, object, slot, makeId = newOperationId) {
    if (!object || typeof object !== "object") {
        return newOperationId();
    }
    let slots = map.get(object);
    if (!slots) {
        slots = new Map();
        map.set(object, slots);
    }
    if (!slots.has(slot)) {
        slots.set(slot, makeId());
    }
    return slots.get(slot);
}

function clearOperationId(map, object, slot) {
    const slots = object && map.get(object);
    slots?.delete(slot);
}

function billOperationId(order) {
    return stableOperationId(receiptOperations, order, "bill", () => {
        const storageKey = `lba-print-bill:${order.uuid}`;
        try {
            const existing = globalThis.localStorage?.getItem(storageKey);
            if (existing) return existing;
            const created = newOperationId();
            globalThis.localStorage?.setItem(storageKey, created);
            return created;
        } catch {
            return newOperationId();
        }
    });
}

function clearBillOperationId(order) {
    clearOperationId(receiptOperations, order, "bill");
    try {
        globalThis.localStorage?.removeItem(`lba-print-bill:${order.uuid}`);
    } catch {
        // localStorage puede estar deshabilitado; la cola del servidor persiste.
    }
}

function isAccepted(result) {
    return ["pending", "queued", "sent"].includes(result?.state);
}

function resolveBlocks(store, template) {
    const model = store.models?.["lba.print.template.block"];
    const rows = model?.getAll?.() || [];
    const byId = new Map(rows.map((row) => [row.id, row]));
    const getBlock = (value) => {
        if (value && typeof value === "object" && value.block_type) {
            return value;
        }
        return byId.get(recordId(value));
    };
    const materialize = (value) => {
        const block = getBlock(value);
        if (!block) {
            return null;
        }
        const children = relationRows(block.child_ids)
            .map(materialize)
            .filter(Boolean);
        return { ...block, children };
    };
    return relationRows(template.block_ids).map(materialize).filter(Boolean);
}

function selectTemplate(store, templateType, departmentId, printerId) {
    const templates = recordsFor(store, "lba.print.template");
    const candidates = templates.map((template) => {
        const printer = recordId(template.printer_id);
        const department = recordId(template.department_id);
        let scope = 0;
        if (printerId && printer === printerId) {
            scope = 3;
        } else if (!printer && departmentId && department === departmentId) {
            scope = 2;
        } else if (!printer && !department) {
            scope = 1;
        }
        return { template, scope };
    }).filter(({ template, scope }) =>
        template.template_type === templateType && scope > 0
    );
    candidates.sort((a, b) =>
        b.scope - a.scope ||
        (a.template.priority || 0) - (b.template.priority || 0) ||
        (a.template.sequence || 0) - (b.template.sequence || 0) ||
        a.template.id - b.template.id
    );
    if (!candidates.length) {
        return null;
    }
    return {
        ...candidates[0].template,
        blocks: resolveBlocks(store, candidates[0].template),
    };
}

function templateDocument(store, type, department, printer, data, fallback) {
    const template = selectTemplate(
        store,
        type,
        recordId(department),
        recordId(printer)
    );
    return template ? templateToDocument(template, data) : fallback();
}

function lineCategoryIds(store, line) {
    const product = store.models?.["product.product"]?.get(recordId(line?.product_id));
    const ids = product?.parentPosCategIds || [];
    return ids.map(recordId).filter(Boolean);
}

function changeLines(change) {
    return [
        ...(change?.new || []),
        ...(change?.cancelled || []),
        ...(change?.noteUpdate || []),
    ];
}

function filterFallbackChanges(store, changes, assignedDepartments) {
    const assigned = new Set();
    for (const department of assignedDepartments) {
        for (const category of relationRows(department.category_ids)) {
            const id = recordId(category);
            if (id) assigned.add(id);
        }
    }
    const isUnassigned = (line) => {
        const categories = lineCategoryIds(store, line);
        return categories.length > 0 && !categories.some((id) => assigned.has(id));
    };
    return {
        ...changes,
        new: (changes.new || []).filter(isUnassigned),
        cancelled: (changes.cancelled || []).filter(isUnassigned),
        noteUpdate: (changes.noteUpdate || []).filter(isUnassigned),
    };
}

function removeEmptyChangeItems(changes) {
    return {
        ...changes,
        new: changes?.new || [],
        cancelled: changes?.cancelled || [],
        noteUpdate: changes?.noteUpdate || [],
    };
}

function hasPrintableDelta(changes, sourceChange) {
    return Boolean(
        changes.new.length || changes.cancelled.length || changes.noteUpdate.length ||
        sourceChange?.internal_note || sourceChange?.general_customer_note
    );
}

patch(PosStore.prototype, {
    /** Recibo pagado o pre-cuenta; una repetición intencional obtiene otro ID. */
    async printReceipt({
        basic = false,
        order = this.getOrder(),
        printBillActionTriggered = false,
    } = {}) {
        const cfg = this.config || {};
        const printerId = recordId(cfg.lba_receipt_printer_id);
        if (!(cfg.lba_active && printerId && order)) {
            return super.printReceipt({ basic, order, printBillActionTriggered });
        }

        const slot = printBillActionTriggered ? "bill" : "receipt";
        const operationId = printBillActionTriggered
            ? billOperationId(order)
            : `receipt-${Number(order.nb_print || 0)}`;
        let accepted = false;
        try {
            const printer = this.models?.["lba.print.printer"]?.get(printerId);
            const data = receiptTemplateData(order, { basic, bill: printBillActionTriggered });
            const document = templateDocument(
                this,
                "receipt",
                false,
                printer,
                data,
                () => buildReceiptDocument(order, {
                    basic,
                    bill: printBillActionTriggered,
                })
            );
            const result = await rpc("/lba_print/jobs", {
                config_id: recordId(cfg),
                session_id: recordId(this.session),
                printer_id: printerId,
                kind: "receipt",
                order_ref: order.getName?.() || order.preparationName || order.uuid,
                order_uuid: order.uuid,
                document,
                idempotency_key: buildIdempotencyOpId("receipt", order, {
                    eventId: operationId,
                    scope: String(printerId),
                }),
            });
            if (isAccepted(result)) {
                accepted = true;
                if (printBillActionTriggered) clearBillOperationId(order);
            } else {
                if (printBillActionTriggered) clearBillOperationId(order);
                notifyError(this, printer?.name, result?.error || _t("respuesta de cola inválida"));
            }
        } catch (error) {
            // Conserva el mismo ID para que un retry tras timeout no duplique.
            notifyError(this, "LBA", error?.message || error);
        }

        // Mantener exactamente la semántica de nb_print del core POS.
        if (!printBillActionTriggered) {
            if (accepted) {
                const count = order.nb_print ? order.nb_print + 1 : 1;
                if (order.isSynced) {
                    const wasDirty = order.isDirty();
                    await this.data.write("pos.order", [order.id], { nb_print: count });
                    if (!wasDirty) order._dirty = false;
                } else {
                    order.nb_print = count;
                }
            }
        } else if (!order.nb_print) {
            order.nb_print = 0;
        }
        return accepted;
    },

    /** Comandas/deltas LBA por departamento; impresoras nativas van por super. */
    async printChanges(order, orderChange, reprint = false, printers = this.unwatched.printers) {
        const cfg = this.config || {};
        if (!cfg.lba_active) {
            return super.printChanges(order, orderChange, reprint, printers);
        }

        const departments = recordsFor(this, "lba.print.department")
            .filter((department) => department.active !== false);
        const assignedDepartments = departments.filter((department) =>
            relationRows(department.category_ids).length > 0
        );
        const activePrinters = new Map(
            recordsFor(this, "lba.print.printer")
                .filter((printer) => printer.active !== false)
                .map((printer) => [printer.id, printer])
        );
        const lbaDepartments = departments.filter((department) =>
            relationRows(department.printer_ids).some((printerRef) =>
                activePrinters.has(recordId(printerRef))
            )
        );
        const reprintEventId = reprint ? newOperationId() : null;
        let isPrinted = false;
        let hasLbaJobs = false;
        let allLbaAccepted = true;

        for (const department of lbaDepartments) {
            const printerRefs = relationRows(department.printer_ids);
            const eligiblePrinterRefs = printerRefs.filter((printerRef) =>
                activePrinters.has(recordId(printerRef))
            );
            const categoryIds = relationRows(department.category_ids)
                .map(recordId).filter(Boolean);
            const isFallback = Boolean(department.is_fallback);
            if (!categoryIds.length && !isFallback) {
                continue;
            }

            // printer_ids is ordered by lba.print.printer (_order=name,id):
            // first active printer is primary; later entries are fallbacks.
            const outcomes = new Map();
            for (let printerIndex = 0; printerIndex < eligiblePrinterRefs.length; printerIndex++) {
                const printerRef = eligiblePrinterRefs[printerIndex];
                const printerId = recordId(printerRef);
                const printer = activePrinters.get(printerId);
                const hasMorePrinters = printerIndex + 1 < eligiblePrinterRefs.length;

                for (let changeIndex = 0; changeIndex < (orderChange || []).length; changeIndex++) {
                    const outcome = outcomes.get(changeIndex);
                    if (outcome === "accepted" || outcome === "terminal") continue;
                    const sourceChange = orderChange[changeIndex];
                    const scopedChange = {
                        ...sourceChange,
                        new: [...(sourceChange?.new || [])],
                        cancelled: [...(sourceChange?.cancelled || [])],
                        noteUpdate: [...(sourceChange?.noteUpdate || [])],
                    };
                    let { orderData, changes } = this.generateOrderChange(
                        order,
                        scopedChange,
                        isFallback
                            ? [...new Set(changeLines(scopedChange).flatMap((line) => lineCategoryIds(this, line)))]
                            : categoryIds,
                        reprint
                    );
                    changes = removeEmptyChangeItems(changes);
                    if (isFallback) {
                        changes = filterFallbackChanges(this, changes, assignedDepartments);
                    }
                    if (!hasPrintableDelta(changes, sourceChange)) continue;
                    hasLbaJobs = true;

                    const templateData = kitchenTemplateData(
                        order,
                        orderData,
                        changes,
                        { reprint, departmentName: department.name }
                    );
                    const document = templateDocument(
                        this,
                        "kitchen",
                        department,
                        printer,
                        templateData,
                        () => buildKitchenDocument(order, orderData, changes, {
                            reprint,
                            departmentName: department.name,
                        })
                    );
                    const deltaKind = changes.cancelled.length || changes.noteUpdate.length
                        ? "delta"
                        : "kitchen";
                    const slot = `${department.id}:${printerId}:${changeIndex}`;
                    const eventId = reprint
                        ? reprintEventId
                        : stableOperationId(
                            changeOperations,
                            sourceChange,
                            slot,
                            () => buildKitchenEventId(order, sourceChange, slot)
                        );
                    const idempotencyKey = buildIdempotencyOpId(
                        reprint ? "reprint" : deltaKind,
                        order,
                        { eventId, scope: `d${department.id}-p${printerId}-c${changeIndex}` }
                    );

                    try {
                        const result = await rpc("/lba_print/jobs", {
                            config_id: recordId(cfg),
                            session_id: recordId(this.session),
                            printer_id: printerId,
                            kind: reprint ? "reprint" : deltaKind,
                            order_ref: orderData?.pos_reference || order?.preparationName || order?.uuid,
                            order_uuid: order?.uuid,
                            department_id: department.id,
                            document,
                            idempotency_key: idempotencyKey,
                        });
                        if (isAccepted(result)) {
                            isPrinted = true;
                            outcomes.set(changeIndex, "accepted");
                        } else if (canFailoverPrinter(result, hasMorePrinters)) {
                            // The controller rejected this destination before
                            // creating a job; only this explicit case can fall
                            // through to the next configured printer.
                            outcomes.set(changeIndex, "fallback");
                        } else {
                            outcomes.set(changeIndex, "terminal");
                            allLbaAccepted = false;
                            notifyError(this, printer.name, result?.error || _t("respuesta de cola inválida"));
                        }
                    } catch (error) {
                        // El mismo objeto de cambio conserva su operationId para retry.
                        // A timeout the server may already have accepted the job;
                        // stop here rather than risk a duplicate on a backup.
                        outcomes.set(changeIndex, "terminal");
                        allLbaAccepted = false;
                        notifyError(this, printer.name, error?.message || error);
                    }
                }
            }
        }

        // No se altera el camino normal de impresoras Odoo nativas.
        const nativeResult = await super.printChanges(order, orderChange, reprint, printers || []);
        const nativePrinters = printers || [];
        const allRequiredPrintersAccepted = !hasLbaJobs || (
            allLbaAccepted && (!nativePrinters.length || nativeResult)
        );
        isPrinted = allRequiredPrintersAccepted && (isPrinted || nativeResult || hasLbaJobs);
        if (!reprint && isPrinted && (orderChange || []).length) {
            order.uiState.lastPrints.push(orderChange[0]);
        }
        return isPrinted;
    },
});
