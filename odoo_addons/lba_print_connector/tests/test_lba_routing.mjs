import assert from "node:assert/strict";
import { canFailoverPrinter } from "../static/src/app/lba_routing.js";

assert.equal(canFailoverPrinter({
    state: "error", code: "printer_unavailable", error: "Impresora LBA no encontrada/inactiva",
}, true), true);
assert.equal(canFailoverPrinter({
    state: "error", code: "printer_unavailable",
}, false), false);
assert.equal(canFailoverPrinter({
    state: "pending", job: { uuid: "job-1" },
}, true), false);
assert.equal(canFailoverPrinter({
    state: "error", error: "Payload inválido",
}, true), false);
assert.equal(canFailoverPrinter(null, true), false); // RPC rejection/timeout

console.log("OK: el failover requiere rechazo explícito de impresora antes de encolar");
