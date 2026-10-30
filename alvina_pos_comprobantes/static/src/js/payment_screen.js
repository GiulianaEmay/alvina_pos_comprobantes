import { patch } from "@web/core/utils/patch";
import { PaymentScreen } from "@point_of_sale/app/screens/payment_screen/payment_screen";
import { alvinaReceiptFirst } from "./order_payment_validation";

patch(PaymentScreen.prototype, {
    setup() {
        super.setup(...arguments);
        if (!this.currentOrder.finalized && alvinaReceiptFirst(this.currentOrder)) {
            // Also enable the native Validate button when an earlier setting
            // marked the order for invoicing without having selected a customer.
            this.currentOrder.setToInvoice(false);
        }
    },
});
