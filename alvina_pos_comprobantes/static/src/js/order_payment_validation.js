import { patch } from "@web/core/utils/patch";
import OrderPaymentValidation from "@point_of_sale/app/utils/order_payment_validation";

export function alvinaReceiptFirst(order) {
    return order.company.country_id?.code === "PE" && order.priceIncl > 0 &&
        !order.isRefund && !order.account_move;
}

patch(OrderPaymentValidation.prototype, {
    get alvinaReceiptFirst() {
        return alvinaReceiptFirst(this.order);
    },
    async validateOrder(...args) {
        if (!this.order.finalized && this.alvinaReceiptFirst) {
            // Both normal and fast payments must produce the attention ticket
            // before asking for fiscal identity or generating an invoice.
            this.order.setToInvoice(false);
        }
        return super.validateOrder(...args);
    },
    shouldDownloadInvoice(...args) {
        // The backend may retain to_invoice for the existing nightly job even
        // though no fiscal invoice has been requested from this receipt yet.
        return this.alvinaReceiptFirst ? false : super.shouldDownloadInvoice(...args);
    },
    get nextPage() {
        if (this.alvinaReceiptFirst && !this.error) {
            // Keep the receipt action available even when skip-screen is enabled.
            return { page: "ReceiptScreen", params: { orderUuid: this.order.uuid } };
        }
        return super.nextPage;
    },
});
