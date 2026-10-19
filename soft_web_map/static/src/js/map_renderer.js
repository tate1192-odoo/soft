/** @odoo-module **/

import { Component, onMounted, onWillUnmount, useRef, useState } from "@odoo/owl";

import { session } from "@web/session";
import { _t } from "@web/core/l10n/translation";
import { useBus, useService } from "@web/core/utils/hooks";

const DEFAULT_TILE_URL = "https://tile.openstreetmap.org/{z}/{x}/{y}.png";
const DEFAULT_ATTRIBUTION = "© OpenStreetMap contributors";
const DEFAULT_CENTER = [39.0, 35.0];
const DEFAULT_ZOOM = 6;
const MIN_ZOOM = 2;
const MAX_ZOOM = 18;
const CLUSTER_THRESHOLD = 100;
const ERROR_TILE =
    "data:image/svg+xml;charset=utf-8," +
    encodeURIComponent(
        '<svg xmlns="http://www.w3.org/2000/svg" width="256" height="256">' +
            '<rect width="256" height="256" fill="#f1f3f5"/>' +
            '<path d="M0 128h256M128 0v256" stroke="#dee2e6" stroke-width="2"/>' +
            "</svg>"
    );

export class MapRenderer extends Component {
    static template = "soft_web_map.MapCanvas";
    static props = ["model", "onMarkerClick?"];

    setup() {
        this.notification = useService("notification");
        this.mapRef = useRef("mapContainer");

        this.state = useState({
            selectedId: null,
            panelOpen: false,
            loading: true,
            error: false,
        });

        this.map = null;
        this.markers = new Map();
        this.clusterLayer = null;
        this.tileLayer = null;
        this.tileErrorNotified = false;
        this.resizeObserver = null;
        this.resizeFrame = null;

        useBus(this.props.model.bus, "update", () => {
            if (this.map) {
                this.renderMarkers();
            }
        });

        onMounted(() => this.initializeMap());
        onWillUnmount(() => this.destroyMap());
    }

    // ------------------------------------------------------------------
    // Data helpers
    // ------------------------------------------------------------------

    get metaData() {
        return this.props.model?.metaData || {};
    }

    get records() {
        return this.props.model?.data?.records || [];
    }

    get totalCount() {
        return this.props.model?.data?.count ?? this.records.length;
    }

    get locatedRecords() {
        return this.records.filter((record) => this.coordinates(record) !== null);
    }

    get locatedCount() {
        return this.locatedRecords.length;
    }

    get panelTitle() {
        return this.metaData.panelTitle || _t("Map View");
    }

    get mapHeight() {
        return this.metaData.mapHeight || null;
    }

    get hideTitle() {
        return Boolean(this.metaData.hideTitle);
    }

    get hideName() {
        return Boolean(this.metaData.hideName);
    }

    get hideAddress() {
        return Boolean(this.metaData.hideAddress);
    }

    get tileUrl() {
        return (
            this.metaData.customTileUrl ||
            session["soft_web_map.tile_url"] ||
            session["leaflet.tile_url"] ||
            DEFAULT_TILE_URL
        );
    }

    get attribution() {
        return (
            session["soft_web_map.copyright"] ||
            session["leaflet.copyright"] ||
            DEFAULT_ATTRIBUTION
        );
    }

    get googleDirectionsUrl() {
        const points = this.locatedRecords
            .map((record) => this.coordinates(record))
            .filter(Boolean)
            .map((coords) => `${coords.lat},${coords.lng}`);
        const params = new URLSearchParams({ api: "1" });
        if (points.length) {
            if (points.length > 1) {
                params.set("waypoints", points.slice(0, -1).join("|"));
            }
            params.set("destination", points.at(-1));
        }
        return `https://www.google.com/maps/dir/?${params.toString()}`;
    }

    /**
     * Return the coordinates of a record, or null when the record has no
     * usable geolocation.
     */
    coordinates(record) {
        if (!record) {
            return null;
        }
        const latField = this.metaData.latitudeField || "partner_latitude";
        const lngField = this.metaData.longitudeField || "partner_longitude";
        const lat = Number(record[latField]);
        const lng = Number(record[lngField]);
        if (!Number.isFinite(lat) || !Number.isFinite(lng)) {
            return null;
        }
        if (lat < -90 || lat > 90 || lng < -180 || lng > 180) {
            return null;
        }
        // (0, 0) is the default value of the Odoo geolocation fields.
        if (lat === 0 && lng === 0) {
            return null;
        }
        return { lat, lng };
    }

    hasCoordinates(record) {
        return this.coordinates(record) !== null;
    }

    recordName(record) {
        return record.display_name || record.name || _t("No Name");
    }

    coordinateLabel(record) {
        const coords = this.coordinates(record);
        return coords ? `${coords.lat.toFixed(5)}, ${coords.lng.toFixed(5)}` : "";
    }

    /**
     * Return the display name of a many2one value (tuple or string).
     */
    many2oneLabel(value) {
        if (Array.isArray(value)) {
            return value[1] || "";
        }
        if (value && typeof value === "object") {
            return value.display_name || "";
        }
        if (typeof value === "string" || typeof value === "number") {
            return String(value);
        }
        return "";
    }

    addressLabel(record) {
        const parts = [
            record.street,
            record.street2,
            record.city,
            this.many2oneLabel(record.state_id),
            this.many2oneLabel(record.country_id),
        ].filter(Boolean);
        return parts.join(", ");
    }

    // ------------------------------------------------------------------
    // Leaflet lifecycle
    // ------------------------------------------------------------------

    initializeMap() {
        if (typeof L === "undefined") {
            this.failMap(
                _t("Failed to load the map library. Please refresh the page.")
            );
            return;
        }
        if (!this.mapRef.el) {
            this.failMap(_t("Failed to initialize the map container."));
            return;
        }

        try {
            this.map = L.map(this.mapRef.el, {
                zoomControl: this.metaData.showControls !== false,
                // Do not steal the page scroll; use the +/- controls or
                // keyboard navigation instead.
                scrollWheelZoom: false,
                doubleClickZoom: true,
                closePopupOnClick: true,
                attributionControl: true,
                minZoom: MIN_ZOOM,
                maxZoom: MAX_ZOOM,
            });

            this.map.attributionControl.setPrefix(
                '<a href="https://leafletjs.com" title="A JavaScript library for interactive maps">Leaflet</a>'
            );
            this.map.attributionControl.setPosition("bottomleft");

            this.map.setView(
                DEFAULT_CENTER,
                this.metaData.zoomLevel || DEFAULT_ZOOM
            );

            this.tileLayer = L.tileLayer(this.tileUrl, {
                attribution: this.attribution,
                minZoom: MIN_ZOOM,
                maxZoom: MAX_ZOOM,
                errorTileUrl: ERROR_TILE,
            });
            this.tileLayer.on("tileerror", () => this.notifyTileError());
            this.tileLayer.on("tileload", () => {
                this.tileErrorNotified = false;
            });
            this.tileLayer.addTo(this.map);

            this.map.on("popupopen", (event) => this.bindPopupButton(event.popup));

            if (typeof ResizeObserver !== "undefined") {
                this.resizeObserver = new ResizeObserver(() => {
                    if (this.resizeFrame) {
                        cancelAnimationFrame(this.resizeFrame);
                    }
                    this.resizeFrame = requestAnimationFrame(() => {
                        this.resizeFrame = null;
                        if (this.map) {
                            this.map.invalidateSize();
                        }
                    });
                });
                this.resizeObserver.observe(this.mapRef.el);
            }

            this.state.loading = false;
            this.renderMarkers();
        } catch (error) {
            console.error("soft_web_map: map initialization failed", error);
            this.failMap(
                _t("Failed to initialize the map. Please try refreshing the page.")
            );
        }
    }

    destroyMap() {
        this.resizeObserver?.disconnect();
        this.resizeObserver = null;
        if (this.resizeFrame) {
            cancelAnimationFrame(this.resizeFrame);
            this.resizeFrame = null;
        }
        this.clearMarkerLayers();
        if (this.tileLayer && this.map) {
            this.map.removeLayer(this.tileLayer);
            this.tileLayer = null;
        }
        if (this.map) {
            this.map.off();
            this.map.remove();
            this.map = null;
        }
    }

    failMap(message) {
        this.state.error = true;
        this.state.loading = false;
        this.notification.add(message, { type: "danger" });
    }

    notifyTileError() {
        if (this.tileErrorNotified) {
            return;
        }
        this.tileErrorNotified = true;
        this.notification.add(
            _t("Some map tiles failed to load. Check your internet connection."),
            { type: "warning" }
        );
    }

    // ------------------------------------------------------------------
    // Markers and popups
    // ------------------------------------------------------------------

    renderMarkers() {
        if (!this.map) {
            return;
        }

        this.clearMarkerLayers();
        const records = this.locatedRecords;
        if (!records.some((record) => record.id === this.state.selectedId)) {
            this.state.selectedId = null;
        }

        if (!records.length) {
            this.fitMarkers();
            return;
        }

        const useClustering =
            Boolean(this.metaData.clustering) || this.totalCount > CLUSTER_THRESHOLD;
        if (useClustering && typeof L.markerClusterGroup === "function") {
            this.clusterLayer = L.markerClusterGroup({
                maxClusterRadius: this.metaData.clusteringRadius || 50,
                showCoverageOnHover: false,
            }).addTo(this.map);
        }

        const markers = [];
        for (const record of records) {
            const marker = this.createMarker(record);
            if (marker) {
                this.markers.set(record.id, marker);
                markers.push(marker);
            }
        }

        if (this.clusterLayer) {
            this.clusterLayer.addLayers(markers);
        } else {
            for (const marker of markers) {
                marker.addTo(this.map);
            }
        }

        this.fitMarkers();
    }

    clearMarkerLayers() {
        if (this.clusterLayer) {
            this.clusterLayer.clearLayers();
            if (this.map) {
                this.map.removeLayer(this.clusterLayer);
            }
            this.clusterLayer = null;
        } else if (this.map) {
            for (const marker of this.markers.values()) {
                this.map.removeLayer(marker);
            }
        }
        this.markers.clear();
    }

    createMarker(record) {
        const coords = this.coordinates(record);
        if (!coords) {
            return null;
        }

        const marker = L.marker([coords.lat, coords.lng], {
            icon: this.markerIcon(record.id === this.state.selectedId),
            title: this.hideName ? this.coordinateLabel(record) : this.recordName(record),
        });
        marker.bindPopup(this.popupContent(record));
        marker.on("click", () => {
            this.state.selectedId = record.id;
            this.refreshMarkerIcons();
        });
        return marker;
    }

    markerIcon(active) {
        return L.divIcon({
            className: active ? "o_swm_marker o_swm_marker--active" : "o_swm_marker",
            html: '<span class="o_swm_marker_dot"></span>',
            iconSize: [20, 20],
            iconAnchor: [10, 10],
        });
    }

    refreshMarkerIcons() {
        for (const [recordId, marker] of this.markers) {
            marker.setIcon(this.markerIcon(recordId === this.state.selectedId));
        }
    }

    popupContent(record) {
        const nameHtml = this.hideName
            ? ""
            : `<div class="o_swm_popup_name">${this.escapeHtml(this.recordName(record))}</div>`;
        const address = this.hideAddress ? "" : this.addressLabel(record);
        const addressHtml = address
            ? `<div class="o_swm_popup_address">${this.escapeHtml(address)}</div>`
            : "";
        const emailHtml = record.email
            ? `<div class="o_swm_popup_meta"><i class="fa fa-envelope"></i> ${this.escapeHtml(
                  record.email
              )}</div>`
            : "";
        const phoneHtml = record.phone
            ? `<div class="o_swm_popup_meta"><i class="fa fa-phone"></i> ${this.escapeHtml(
                  record.phone
              )}</div>`
            : "";

        return `
            <div class="o_swm_popup">
                ${nameHtml}
                ${addressHtml}
                ${emailHtml}
                ${phoneHtml}
                <button type="button"
                        class="btn btn-sm btn-primary o_swm_open_record"
                        data-record-id="${record.id}">
                    <i class="fa fa-eye"></i> ${this.escapeHtml(_t("View Details"))}
                </button>
            </div>
        `;
    }

    bindPopupButton(popup) {
        const button = popup?.getElement?.()?.querySelector?.(".o_swm_open_record");
        if (!button) {
            return;
        }
        button.addEventListener("click", (event) => {
            event.preventDefault();
            const recordId = Number(button.dataset.recordId);
            if (Number.isInteger(recordId)) {
                this.props.onMarkerClick?.(recordId);
            }
        });
    }

    // ------------------------------------------------------------------
    // User interactions
    // ------------------------------------------------------------------

    onRecordClick(event) {
        const recordId = Number(event.currentTarget.dataset.recordId);
        const record = this.locatedRecords.find((item) => item.id === recordId);
        if (record) {
            this.selectRecord(record);
        }
    }

    toggleSidebar() {
        this.state.panelOpen = !this.state.panelOpen;
    }

    selectRecord(record) {
        const coords = this.coordinates(record);
        if (!coords || !this.map) {
            return;
        }

        this.state.selectedId = record.id;
        if (this.env.isSmall) {
            this.state.panelOpen = false;
        }
        this.refreshMarkerIcons();
        this.map.setView([coords.lat, coords.lng], 15);

        const marker = this.markers.get(record.id);
        if (!marker) {
            return;
        }
        if (this.clusterLayer) {
            this.clusterLayer.zoomToShowLayer(marker, () => marker.openPopup());
        } else {
            marker.openPopup();
        }
    }

    fitMarkers() {
        if (!this.map) {
            return;
        }

        let bounds = null;
        if (this.clusterLayer) {
            bounds = this.clusterLayer.getBounds();
        } else if (this.markers.size) {
            bounds = L.featureGroup([...this.markers.values()]).getBounds();
        }

        if (bounds?.isValid()) {
            this.map.fitBounds(bounds, { padding: [30, 30], maxZoom: 15 });
        } else {
            this.map.setView(DEFAULT_CENTER, this.metaData.zoomLevel || DEFAULT_ZOOM);
        }
    }

    redraw() {
        this.renderMarkers();
    }

    // ------------------------------------------------------------------
    // Utilities
    // ------------------------------------------------------------------

    escapeHtml(value) {
        if (value === null || value === undefined) {
            return "";
        }
        return String(value)
            .replace(/&/g, "&amp;")
            .replace(/</g, "&lt;")
            .replace(/>/g, "&gt;")
            .replace(/"/g, "&quot;")
            .replace(/'/g, "&#039;");
    }
}
