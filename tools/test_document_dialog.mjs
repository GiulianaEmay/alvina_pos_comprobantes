/**
 * Logic tests for the actual DocumentDialog source with simulated OWL/services.
 * These tests do not mount a browser, run Odoo, call JSON.PE or send to SUNAT.
 * Run: node --test tools/test_document_dialog.mjs
 */
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const source = readFileSync(
    new URL("../alvina_pos_comprobantes/static/src/js/document_dialog.js", import.meta.url),
    "utf8"
).replace(/^import .*;\r?\n/gm, "").replace(/\bexport class\b/, "class");

const prepared = () => ({ state: "to_send", can_send: true, can_print: false });
const sent = () => ({ state: "sent", can_send: false, can_print: true, invoice_name: "B001-TEST" });
const pdfAction = () => ({ type: "ir.actions.act_url", target: "download", url: "/existing-invoice.pdf" });

async function makeDialog({ status = { state: "none" }, handlers = {}, failReload = false } = {}) {
    const starts = [];
    const events = [];
    const calls = [];
    const downloads = [];
    const action = {
        async doAction(value) {
            events.push("download");
            downloads.push(value);
        },
    };
    class MockComponent {
        constructor(props) {
            this.props = props;
        }
    }
    const DialogClass = new Function(
        "Component", "Dialog", "useState", "useService", "onWillStart", "onWillUnmount",
        source + "\nreturn AlvinaDocumentDialog;"
    )(
        MockComponent,
        class {},
        (value) => value,
        (name) => {
            assert.equal(name, "action");
            return action;
        },
        (callback) => starts.push(callback),
        () => {}
    );
    const defaults = {
        alvina_document_status: () => ({ ...status }),
        alvina_submit_document: prepared,
        alvina_send_document: sent,
        alvina_print_document: pdfAction,
    };
    const dialog = new DialogClass({
        close() {},
        order: { id: 42, isSynced: true },
        data: {
            async call(model, method, args) {
                assert.equal(model, "pos.order");
                assert.deepEqual(args[0], [42], "Every fiscal RPC must address the original order");
                calls.push(method);
                events.push(method);
                const handler = handlers[method] || defaults[method];
                assert.equal(typeof handler, "function", `Unexpected RPC: ${method}`);
                return handler(args);
            },
            async callRelated(model, method, args, kwargs, queue, loadMissing) {
                assert.equal(model, "pos.order");
                assert.equal(method, "read_pos_orders");
                assert.deepEqual(args, [[["id", "=", 42]]]);
                assert.deepEqual(kwargs, {});
                assert.equal(queue, false);
                assert.equal(loadMissing, true);
                events.push("reload");
                if (failReload) {
                    throw new Error("Simulated ticket view/cache failure");
                }
                return { "pos.order": [] };
            },
        },
    });
    dialog.setup();
    for (const callback of starts) {
        await callback();
    }
    return { dialog, calls, events, downloads };
}

function setPreview(dialog) {
    dialog.state.kind = "boleta";
    dialog.state.number = "12345678";
    dialog.state.preview = {
        identity_id: 7, kind: "boleta", number: "12345678", name: "CLIENTE DE PRUEBA",
    };
}

function count(calls, method) {
    return calls.filter((value) => value === method).length;
}

test("one confirmation submits, sends and downloads before refreshing the ticket", async () => {
    const { dialog, calls, events, downloads } = await makeDialog();
    events.length = 0;
    setPreview(dialog);
    await dialog.confirm();
    assert.deepEqual(events, [
        "alvina_submit_document", "alvina_send_document", "alvina_print_document", "download", "reload",
    ]);
    assert.equal(count(calls, "alvina_submit_document"), 1);
    assert.equal(count(calls, "alvina_send_document"), 1);
    assert.equal(downloads.length, 1);
    assert.equal(dialog.state.status.state, "sent");
    assert.equal(dialog.state.busy, false);
});

test("failed ticket refresh cannot interrupt emission or printing and shows a warning", async () => {
    const { dialog, calls, downloads } = await makeDialog({ failReload: true });
    setPreview(dialog);
    await dialog.confirm();
    assert.equal(count(calls, "alvina_send_document"), 1);
    assert.equal(count(calls, "alvina_print_document"), 1);
    assert.equal(downloads.length, 1);
    assert.equal(dialog.state.status.state, "sent");
    assert.equal(dialog.state.error, "");
    assert.match(dialog.state.warning, /actualizar la vista del ticket/);
    assert.equal(dialog.state.busy, false);
});

test("an EDI error preserves the result and never requests a printable PDF", async () => {
    const { dialog, calls, events, downloads } = await makeDialog({
        handlers: {
            alvina_send_document: () => ({
                state: "edi_error", can_send: false, can_print: false, message: "Rechazo simulado",
            }),
        },
    });
    setPreview(dialog);
    await dialog.confirm();
    assert.equal(dialog.state.status.state, "edi_error");
    assert.equal(dialog.state.status.message, "Rechazo simulado");
    assert.equal(count(calls, "alvina_send_document"), 1);
    assert.equal(count(calls, "alvina_print_document"), 0);
    assert.equal(downloads.length, 0);
    assert.equal(events.at(-1), "reload");
});

test("PDF generation failure retains sent state and printing again never reissues", async () => {
    let firstPrint = true;
    const { dialog, calls, events, downloads } = await makeDialog({
        handlers: {
            alvina_print_document: () => {
                if (firstPrint) {
                    firstPrint = false;
                    throw new Error("PDF simulado no disponible");
                }
                return pdfAction();
            },
        },
    });
    setPreview(dialog);
    await dialog.confirm();
    assert.equal(dialog.state.status.state, "sent");
    assert.match(dialog.state.error, /PDF simulado/);
    assert.equal(events.at(-1), "reload", "Even failed PDF generation must not skip a best-effort view refresh");
    await dialog.printDocument();
    assert.equal(count(calls, "alvina_submit_document"), 1);
    assert.equal(count(calls, "alvina_send_document"), 1);
    assert.equal(count(calls, "alvina_print_document"), 2);
    assert.equal(downloads.length, 1);
    assert.equal(dialog.state.error, "");
});

test("busy state rejects a second confirmation while the first is preparing", async () => {
    let finishSubmit;
    const pending = new Promise((resolve) => { finishSubmit = resolve; });
    const { dialog, calls, downloads } = await makeDialog({
        handlers: { alvina_submit_document: () => pending },
    });
    setPreview(dialog);
    const first = dialog.confirm();
    assert.equal(dialog.state.busy, true);
    await dialog.confirm();
    assert.equal(count(calls, "alvina_submit_document"), 1);
    finishSubmit(prepared());
    await first;
    assert.equal(count(calls, "alvina_submit_document"), 1);
    assert.equal(count(calls, "alvina_send_document"), 1);
    assert.equal(downloads.length, 1);
});

test("opening an existing fiscal document only reads its status and refreshes the ticket", async () => {
    const { dialog, calls, events, downloads } = await makeDialog({ status: sent() });
    assert.equal(dialog.locked, true);
    assert.deepEqual(calls, ["alvina_document_status"]);
    assert.deepEqual(events, ["alvina_document_status", "reload"]);
    assert.equal(downloads.length, 0);
    assert.equal(dialog.state.status.state, "sent");
});

test("opening an existing document still shows status when the ticket refresh fails", async () => {
    const { dialog, calls } = await makeDialog({ status: sent(), failReload: true });
    assert.equal(dialog.state.status.state, "sent");
    assert.equal(dialog.state.ready, true);
    assert.equal(dialog.state.error, "");
    assert.match(dialog.state.warning, /actualizar la vista del ticket/);
    assert.deepEqual(calls, ["alvina_document_status"]);
});
