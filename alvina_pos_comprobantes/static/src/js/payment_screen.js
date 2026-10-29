import { patch } from "@web/core/utils/patch";
import { PaymentScreen } from "@point_of_sale/app/screens/payment_screen/payment_screen";
import { AlvinaCustomerDialog } from "./customer_dialog";

patch(PaymentScreen.prototype, {
    alvinaOpenCustomer() {
        this.dialog.add(AlvinaCustomerDialog, {
            pos: this.pos,
            order: this.currentOrder,
            onConfirmed: () => {
                if (this.currentOrder.canBeValidated()) {
                    this.validateOrder();
                }
            },
        });
    },
    async validateOrder(...args) {
        if (this.currentOrder.isToInvoice() && !this.currentOrder.getPartner()) {
            this.alvinaOpenCustomer();
            return;
        }
        return super.validateOrder(...args);
    },
});
