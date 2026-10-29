import { Component, onWillUnmount, useState } from "@odoo/owl";
import { Dialog } from "@web/core/dialog/dialog";

export class AlvinaCustomerDialog extends Component {
    static template = "alvina_pos_comprobantes.CustomerDialog";
    static components = { Dialog };
    static props = { close: Function, pos: Object, order: Object, onConfirmed: Function };

    setup() {
        this.state = useState({ kind: this.props.order.alvina_document_kind || "boleta", number: "", preview: null, busy: false, error: "" });
        onWillUnmount(() => clearTimeout(this.lookupTimer));
    }

    get validNumber() {
        return new RegExp(this.state.kind === "boleta" ? "^[0-9]{8}$" : "^[0-9]{11}$").test(this.state.number);
    }

    changeNumber(event) {
        this.state.number = event.target.value;
        this.state.preview = null;
        this.state.error = "";
        clearTimeout(this.lookupTimer);
        if (this.validNumber) {
            this.lookupTimer = setTimeout(() => this.lookup(), 450);
        }
    }

    changeKind() {
        clearTimeout(this.lookupTimer);
        this.state.number = "";
        this.state.preview = null;
        this.state.error = "";
    }

    async rpc(method, args) {
        return this.props.pos.data.call("pos.session", method, [[this.props.pos.session.id], ...args]);
    }

    async lookup() {
        clearTimeout(this.lookupTimer);
        if (this.state.busy || !this.validNumber) {
            return;
        }
        this.state.busy = true;
        this.state.error = "";
        this.state.preview = null;
        try {
            this.state.preview = await this.rpc("alvina_lookup_customer", [this.state.kind, this.state.number]);
        } catch (error) {
            this.state.error = error.data?.message || error.message || "No se pudo consultar el documento.";
        } finally {
            this.state.busy = false;
        }
    }

    async confirm() {
        const preview = this.state.preview;
        if (this.state.busy || !preview || preview.number !== this.state.number || preview.kind !== this.state.kind) {
            return;
        }
        this.state.busy = true;
        this.state.error = "";
        try {
            const result = await this.rpc("alvina_confirm_customer", [preview.identity_id]);
            await this.props.pos.data.read("res.partner", [result.partner_id]);
            const partner = this.props.pos.models["res.partner"].get(result.partner_id);
            if (!partner) {
                throw new Error("No se pudieron cargar los datos fiscales del cliente.");
            }
            this.props.order.setPartner(partner);
            this.props.order.setToInvoice(true);
            this.props.order.update({ alvina_document_kind: result.kind });
            this.props.close();
            this.props.onConfirmed();
        } catch (error) {
            this.state.error = error.data?.message || error.message || "No se pudieron confirmar los datos.";
        } finally {
            this.state.busy = false;
        }
    }
}
