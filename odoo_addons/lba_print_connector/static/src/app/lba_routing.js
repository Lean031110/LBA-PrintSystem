/**
 * Routing guards shared by the POS patch and its standalone Node tests.
 * A timeout/exception or any other refusal is ambiguous or unrelated to the
 * printer, so it must never cause a duplicate attempt on a second destination.
 */
export function canFailoverPrinter(result, hasMorePrinters) {
    return Boolean(
        hasMorePrinters &&
        result?.state === "error" &&
        result?.code === "printer_unavailable" &&
        !result?.job?.uuid
    );
}
