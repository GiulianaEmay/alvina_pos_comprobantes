import { Component, onWillStart, useState } from "@odoo/owl";
import { Dialog } from "@web/core/dialog/dialog";
import { useService } from "@web/core/utils/hooks";

export class AlvinaDocumentDialog extends Component {
    static template = "alvina_pos_comprobantes.DocumentDialog";
    static components = { Dialog };
    static props = { close: Function, order: Object, data: Object };

    setup() {
        this.action = useService("action");
        this.state = useState({
            kind: "boleta", number: "", preview: null, status: null,
            busy: false, error: "", ready: false,
        });
        onWillStart(() => this.run(async () => {
            if (!this.props.order.isSynced || !Number.isInteger(this.props.order.id)) {
                throw new Error("Sincronice el pedido con el servidor antes de solicitar un comprobante.");
            }
            await this.refresh();
        }));
    }

    async rpc(method, args = []) {
        return this.props.data.call("pos.order", method, [[this.props.order.id], ...args]);
    }

    async run(callback) {
        if (this.state.busy) {
            return;
        }
        this.state.busy = true;
        this.state.error = "";
        try {
            await callback();
        } catch (error) {
            this.state.error = error.data?.message || error.message || "No se pudo completar la operación.";
        } finally {
            this.state.busy = false;
        }
    }

    async refresh() {
        this.state.status = await this.rpc("alvina_document_status");
        this.state.ready = true;
        if (["pending", "processed", "failed"].includes(this.state.status.state)) {
            await this.reloadOrder();
        }
    }

    async reloadOrder() {
        // Official relational loader refreshes the original order and missing partner.
        await this.props.data.callRelated(
            "pos.order", "read_pos_orders", [[["id", "=", this.props.order.id]]],
            {}, false, true
        );
    }

    get locked() {
        return !this.state.ready || this.state.status?.state !== "none";
    }

    get validNumber() {
        return new RegExp(this.state.kind === "boleta" ? "^[0-9]{8}$" : "^[0-9]{11}$").test(this.state.number);
    }

    invalidatePreview() {
        this.state.preview = null;
        this.state.error = "";
    }

    lookup() {
        this.state.preview = null;
        return this.run(async () => {
            this.state.preview = await this.rpc("alvina_lookup_identity", [this.state.kind, this.state.number]);
        });
    }

    confirm() {
        return this.run(async () => {
            const preview = this.state.preview;
            if (!preview || preview.kind !== this.state.kind || preview.number !== this.state.number) {
                throw new Error("Consulte y revise los datos antes de confirmar.");
            }
            this.state.status = await this.rpc("alvina_submit_document", [preview.identity_id]);
            this.state.preview = null;
            await this.reloadOrder();
        });
    }

    printDocument() {
        return this.run(async () => {
            const action = await this.rpc("alvina_print_document");
            await this.action.doAction(action);
        });
    }

    retry() {
        return this.run(async () => {
            this.state.status = await this.rpc("alvina_retry_document");
        });
    }
}
