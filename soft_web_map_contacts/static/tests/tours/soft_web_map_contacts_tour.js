/** @odoo-module **/

import { registry } from "@web/core/registry";

registry.category("web_tour.tours").add("soft_web_map_contacts_tour", {
    url: "/odoo/action-contacts.action_contacts",
    steps: () => [
        {
            trigger: ".o_list_view",
        },
        {
            trigger: ".o_cp_switch_buttons button.o_leaflet_map",
            run: "click",
        },
        {
            trigger: ".o_swm_map",
        },
        {
            trigger: ".o_swm_record",
            run: "click",
        },
        {
            trigger: ".o_swm_popup .o_swm_open_record",
            run: "click",
        },
        {
            trigger: ".o_form_view",
        },
    ],
});
