/** @odoo-module **/

import { _t } from "@web/core/l10n/translation";
import { registry } from "@web/core/registry";

import { MapArchParser } from "./map_arch_parser";
import { MapController } from "./map_controller";
import { MapModel } from "./map_model";
import { MapRenderer } from "./map_renderer";

const DEFAULT_LIMIT = 80;

/**
 * Build the parameters passed to the map model.
 *
 * When the view is restored, Odoo provides a `state` object containing the
 * previously exported model metadata; in that case it is reused as-is.
 */
function getModelParams(genericProps, view, config) {
    if (genericProps.state) {
        return genericProps.state;
    }

    const { arch, resModel, fields, context, limit } = genericProps;
    const archInfo = new view.ArchParser().parse(arch, fields);
    const availableViewTypes = (config.views || []).map(([, viewType]) => viewType);

    return {
        ...archInfo,
        context,
        fields,
        hasFormView: availableViewTypes.includes("form"),
        limit: archInfo.limit || limit || DEFAULT_LIMIT,
        offset: 0,
        panelTitle:
            archInfo.panelTitle || config.getDisplayName?.() || _t("Items"),
        resModel,
    };
}

export const mapView = {
    type: "leaflet_map",
    display_name: "Leaflet Map",
    icon: "fa fa-map-marker",
    multiRecord: true,

    Controller: MapController,
    Renderer: MapRenderer,
    Model: MapModel,
    ArchParser: MapArchParser,
    buttonTemplate: "soft_web_map.MapButtons",
    searchMenuTypes: ["filter", "favorite"],

    props: (genericProps, view, config) => {
        const modelParams = getModelParams(genericProps, view, config);
        return {
            ...genericProps,
            Model: view.Model,
            Renderer: view.Renderer,
            modelParams,
            buttonTemplate: view.buttonTemplate,
        };
    },
};

registry.category("views").add("leaflet_map", mapView);
