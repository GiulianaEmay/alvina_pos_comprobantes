import { patch } from "@web/core/utils/patch";
import { PartnerList } from "@point_of_sale/app/screens/partner_list/partner_list";

patch(PartnerList.prototype, {
    getPartners(partners) {
        // Internal fiscal identities may be loaded to display their paid order,
        // but must not become entries in the regular customer selector.
        return super.getPartners(partners.filter((partner) => !partner.alvina_pos_is_internal));
    },
});
