import { patch } from "@web/core/utils/patch";
import { ReceiptScreen } from "@point_of_sale/app/screens/receipt_screen/receipt_screen";
import { AlvinaDocumentDialog } from "./document_dialog";

patch(ReceiptScreen.prototype, {
    alvinaOpenDocument() {
        this.dialog.add(AlvinaDocumentDialog, {
            order: this.currentOrder,
            data: this.pos.data,
        });
    },
});
