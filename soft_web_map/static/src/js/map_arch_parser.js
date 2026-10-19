/** @odoo-module **/

import { exprToBoolean } from "@web/core/utils/strings";
import { stringToOrderBy } from "@web/search/utils/order_by";

const DEFAULT_LIMIT = 80;
const MAX_LIMIT = 1000;
const DEFAULT_ZOOM = 6;
const MIN_ZOOM = 1;
const MAX_ZOOM = 18;
const DEFAULT_CLUSTER_RADIUS = 50;
const MAX_CLUSTER_RADIUS = 500;

/**
 * Parse the `<leaflet_map>` architecture.
 *
 * The parser keeps the raw field list because the model needs it for
 * `search_read`.  Popup contents are built by the renderer from the fields
 * that are fetched here.
 */
export class MapArchParser {
    parse(arch, fields = {}) {
        const documentRoot = arch?.documentElement || arch;
        const root =
            arch?.tagName === "leaflet_map"
                ? arch
                : documentRoot?.tagName === "leaflet_map"
                  ? documentRoot
                  : documentRoot?.querySelector?.("leaflet_map");

        const config = {
            fieldNames: [],
            latitudeField: "partner_latitude",
            longitudeField: "partner_longitude",
            defaultOrder: null,
            limit: DEFAULT_LIMIT,
            hideTitle: false,
            hideAddress: false,
            hideName: false,
            panelTitle: null,
            mapHeight: null,
            zoomLevel: DEFAULT_ZOOM,
            showControls: true,
            clustering: false,
            clusteringRadius: DEFAULT_CLUSTER_RADIUS,
            customTileUrl: null,
        };

        if (!root) {
            return config;
        }

        this.readRoot(root, config, fields);
        this.readFields(root, config, fields);
        this.readOptions(root, config);
        this.addImplicitFields(config, fields, root);
        this.normalize(config);
        return config;
    }

    /**
     * Read the attributes of the root node.
     */
    readRoot(root, config, fields) {
        const text = (name) => (root.hasAttribute(name) ? root.getAttribute(name) : null);
        const bool = (name) => (root.hasAttribute(name) ? exprToBoolean(root.getAttribute(name)) : null);
        const integer = (name) => {
            const value = parseInt(root.getAttribute(name), 10);
            return Number.isFinite(value) ? value : null;
        };

        const panelTitle = text("panel_title") ?? text("string");
        if (panelTitle !== null) {
            config.panelTitle = panelTitle;
        }

        const limit = integer("limit");
        if (limit !== null) {
            config.limit = limit;
        }
        const zoom = integer("zoom");
        if (zoom !== null) {
            config.zoomLevel = zoom;
        }
        const clusterRadius = integer("clustering_radius");
        if (clusterRadius !== null) {
            config.clusteringRadius = clusterRadius;
        }

        for (const name of [
            "hide_title",
            "hide_address",
            "hide_name",
            "clustering",
            "show_controls",
        ]) {
            const value = bool(name);
            if (value !== null) {
                config[this.attributeToKey(name)] = value;
            }
        }

        config.latitudeField = this.readCoordinateField(
            root,
            "latitude",
            config.latitudeField,
            fields
        );
        config.longitudeField = this.readCoordinateField(
            root,
            "longitude",
            config.longitudeField,
            fields
        );

        if (root.hasAttribute("default_order")) {
            config.defaultOrder = stringToOrderBy(root.getAttribute("default_order") || null);
        }
        if (root.hasAttribute("map_height")) {
            config.mapHeight = root.getAttribute("map_height");
        }
        if (root.hasAttribute("tile_url")) {
            config.customTileUrl = root.getAttribute("tile_url");
        }
    }

    /**
     * Read direct `<field>` children of the root node.
     */
    readFields(root, config, fields) {
        for (const node of Array.from(root.children || [])) {
            if (node.tagName !== "field") {
                continue;
            }
            const fieldName = node.getAttribute("name");
            if (!fieldName) {
                continue;
            }
            if (fields && !fields[fieldName]) {
                console.warn(
                    `soft_web_map: unknown field "${fieldName}" in a leaflet_map view; ignored.`
                );
                continue;
            }

            if (!config.fieldNames.includes(fieldName)) {
                config.fieldNames.push(fieldName);
            }
        }
    }

    /**
     * Read the optional `<options>` block.
     */
    readOptions(root, config) {
        const options = root.querySelector("options");
        if (!options) {
            return;
        }
        for (const option of Array.from(options.children || [])) {
            if (option.tagName === "tile_layer") {
                const url = option.getAttribute("url");
                if (url) {
                    config.customTileUrl = url;
                }
            } else if (option.tagName === "clustering") {
                if (option.hasAttribute("enabled")) {
                    config.clustering = exprToBoolean(option.getAttribute("enabled"));
                }
                const radius = parseInt(option.getAttribute("radius"), 10);
                if (Number.isFinite(radius)) {
                    config.clusteringRadius = radius;
                }
            }
        }
    }

    /**
     * Add the fields required by the built-in marker popup and by the
     * coordinates lookup.  Only fields that exist on the model are added.
     */
    addImplicitFields(config, fields, root) {
        const add = (name) => {
            if (!name || (fields && !fields[name])) {
                return;
            }
            if (!config.fieldNames.includes(name)) {
                config.fieldNames.push(name);
            }
        };

        if (!config.hideName) {
            add("display_name");
        }
        add(config.latitudeField);
        add(config.longitudeField);

        if (!config.hideAddress) {
            for (const name of ["street", "street2", "city", "state_id", "country_id", "zip"]) {
                add(name);
            }
        }

        // The built-in popup knows how to resolve these many2one values.
        for (const name of ["country_id", "state_id", "company_id"]) {
            add(name);
        }
        for (const name of ["email", "phone", "mobile"]) {
            add(name);
        }

        if (!root.hasAttribute("latitude")) {
            add("partner_latitude");
        }
        if (!root.hasAttribute("longitude")) {
            add("partner_longitude");
        }
    }

    /**
     * Clamp numeric values and keep the stored configuration predictable.
     */
    normalize(config) {
        if (!Number.isFinite(config.limit) || config.limit < 1) {
            config.limit = DEFAULT_LIMIT;
        } else if (config.limit > MAX_LIMIT) {
            config.limit = MAX_LIMIT;
        }

        if (!Number.isFinite(config.zoomLevel)) {
            config.zoomLevel = DEFAULT_ZOOM;
        } else {
            config.zoomLevel = Math.min(MAX_ZOOM, Math.max(MIN_ZOOM, config.zoomLevel));
        }

        if (!Number.isFinite(config.clusteringRadius) || config.clusteringRadius < 1) {
            config.clusteringRadius = DEFAULT_CLUSTER_RADIUS;
        } else if (config.clusteringRadius > MAX_CLUSTER_RADIUS) {
            config.clusteringRadius = MAX_CLUSTER_RADIUS;
        }
    }

    /**
     * Read a coordinate attribute and fall back when the field is unknown.
     */
    readCoordinateField(root, attribute, fallback, fields) {
        const fieldName = root.getAttribute(attribute);
        if (!fieldName) {
            return fallback;
        }
        if (fields && !fields[fieldName]) {
            console.warn(
                `soft_web_map: unknown ${attribute} field "${fieldName}" in a leaflet_map view; ` +
                    `falling back to "${fallback}".`
            );
            return fallback;
        }
        return fieldName;
    }

    /**
     * Map snake_case architecture attributes to parser keys.
     */
    attributeToKey(attribute) {
        return attribute.replace(/_([a-z])/g, (_, letter) => letter.toUpperCase());
    }
}
