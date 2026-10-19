{
    "name": "Soft Web Map (Leaflet / OpenStreetMap)",
    "summary": "Enhance your Odoo 19 experience with a custom 'Leaflet Map' view. Display markers "
               "using the powerful Leaflet.js library.",
    "version": "19.0.1.0.0",
    "author": "Softteknik Bilişim",
    "website": "https://softteknik.com",
    "license": "LGPL-3",
    "category": "Tools/Map",
    "depends": [
        "web",
    ],
    "excludes": [
        "web_map",
    ],
    "data": [
        "data/ir_config_parameter.xml",
        "views/res_partner_views.xml",
    ],
    "assets": {
        "web.assets_backend": [
            # 1. Core View Components
            "soft_web_map/static/src/js/map_arch_parser.js",
            "soft_web_map/static/src/js/map_model.js",
            "soft_web_map/static/src/js/map_renderer.js",
            "soft_web_map/static/src/js/map_controller.js",
            "soft_web_map/static/src/js/map_view.js",
            # 2. Templates (XML)
            "soft_web_map/static/src/xml/map_controller.xml",
            "soft_web_map/static/src/xml/map_renderer.xml",
            # 3. CSS/SCSS Files
            "soft_web_map/static/src/scss/map_controller.scss",
            "soft_web_map/static/src/scss/map_renderer.scss",
        ],
        # Lazy bundle: MapController loads it with loadBundle().
        # The order below is preserved by the asset system, so leaflet.js
        # always executes before its plugins (markercluster needs global `L`).
        "soft_web_map.assets_leaflet": [
            "soft_web_map/static/lib/leaflet/leaflet.css",
            "soft_web_map/static/lib/leaflet/MarkerCluster.css",
            "soft_web_map/static/lib/leaflet/MarkerCluster.Default.css",
            "soft_web_map/static/lib/leaflet/leaflet.js",
            "soft_web_map/static/lib/leaflet/leaflet.markercluster.js",
        ],
        # Dark color scheme: Odoo loads this bundle when the `color_scheme`
        # cookie is "dark" (see web/views/webclient_templates.xml).
        "web.assets_web_dark": [
            "soft_web_map/static/src/scss/map_renderer.dark.scss",
        ],
    },
    "installable": True,
    "application": False,
    "auto_install": False,
    "uninstall_hook": "uninstall_hook",
}
