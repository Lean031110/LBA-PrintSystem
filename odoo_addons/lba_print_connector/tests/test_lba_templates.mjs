import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { fileURLToPath } from "node:url";

const modulePath = fileURLToPath(new URL(
    "../static/src/app/lba_templates.js",
    import.meta.url
));
const source = await readFile(modulePath, "utf8");
const moduleUrl = `data:text/javascript;base64,${Buffer.from(source).toString("base64")}`;
const {
    buildKitchenEventId,
    buildIdempotencyOpId,
    kitchenTemplateData,
    receiptTemplateData,
    templateToDocument,
} = await import(moduleUrl);

const ticket = templateToDocument({
    blocks: [
        { block_type: "field", field_key: "order.ref", align: "center", bold: true },
        { block_type: "field", field_key: "arbitrary.code", align: "left" },
        { block_type: "table", table_key: "lines.cancelled" },
        { block_type: "conditional", condition_key: "order.has_note", children: [
            { block_type: "text", value_text: "NOTA" },
        ] },
    ],
}, {
    order: { ref: "POS/001", has_note: true },
    lines: { cancelled: [{ qty: 1, name: "Café", note: "sin azúcar" }] },
});
assert.equal(ticket.type, "ticket");
assert.equal(ticket.blocks[0].value, "POS/001");
assert.equal(ticket.blocks[1].value, "");
assert.equal(ticket.blocks[2].value, "1 x Café");
assert.equal(ticket.blocks[3].value, "   » sin azúcar");
assert.equal(ticket.blocks[4].value, "NOTA");
assert.throws(() => templateToDocument({ blocks: [] }, {}), /no produce bloques/);
const spacing = templateToDocument({ blocks: [
    { block_type: "spacer", spacer_lines: 4, feed_lines: 2 },
    { block_type: "feed", spacer_lines: 4, feed_lines: 2 },
] }, {});
assert.deepEqual(spacing.blocks, [
    { type: "feed", lines: 4 },
    { type: "feed", lines: 2 },
]);

const order = {
    uuid: "order-0001",
    company: { name: "LBA" },
    lines: [{ quantity: 2, name: "Pizza" }],
    paymentlines: [{ name: "Efectivo", amount: 20 }],
    getName: () => "Ticket 1",
};
const receipt = receiptTemplateData(order);
assert.equal(receipt.order.ref, "Ticket 1");
assert.equal(receipt.lines.all[0].qty, 2);
assert.equal(receipt.payments[0].name, "Efectivo");

const kitchen = kitchenTemplateData(order, { pos_reference: "K-1" }, {
    new: [{ quantity: 1, name: "Pizza" }],
    cancelled: [{ quantity: 1, name: "Refresco" }],
    noteUpdate: [{ quantity: 1, name: "Pizza", note: "sin queso" }],
});
assert.equal(kitchen.order.ref, "K-1");
assert.equal(kitchen.lines.new.length, 1);
assert.equal(kitchen.lines.cancelled.length, 1);
assert.equal(kitchen.lines.noteUpdate[0].note, "sin queso");

const keyA = buildIdempotencyOpId("kitchen", order, { eventId: "stable-event", scope: "d1-p2-c0" });
const keyARetry = buildIdempotencyOpId("kitchen", order, { eventId: "stable-event", scope: "d1-p2-c0" });
const keyReprint = buildIdempotencyOpId("reprint", order, { eventId: "intentional-reprint-2", scope: "d1-p2-c0" });
const delta = { new: [{ uuid: "line-1", quantity: 2, name: "Pizza" }] };
const deltaId = buildKitchenEventId(order, delta, "d1-p2-c0");
const deltaRetryId = buildKitchenEventId(order, structuredClone(delta), "d1-p2-c0");
const nextDeltaId = buildKitchenEventId(order, {
    new: [{ uuid: "line-1", quantity: 3, name: "Pizza" }],
}, "d1-p2-c0");
assert.equal(keyA, keyARetry);
assert.notEqual(keyA, keyReprint);
assert.equal(deltaId, deltaRetryId);
assert.notEqual(deltaId, nextDeltaId);
assert.ok(keyA.length <= 200);
assert.match(keyA, /^[A-Za-z0-9_:\-.]+$/);

console.log("OK: serializador, lista blanca, datos POS y claves idempotentes");
