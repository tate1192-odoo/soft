{
    "name": "Soft Web Map — Contacts",
    "summary": "Adds the Leaflet map view to the Contacts application.",
    "version": "19.0.1.0.0",
    "author": "Softteknik Bilişim",
    "website": "https://softteknik.com",
    "license": "LGPL-3",
    "category": "Tools/Map",
    "depends": [
        "soft_web_map",
        "contacts",
        "base_geolocalize",
    ],
    "data": [
        "views/contact_views.xml",
    ],
    "assets": {
        "web.assets_tests": [
            "soft_web_map_contacts/static/tests/tours/**/*",
        ],
    },
    "installable": True,
    "application": False,
    "auto_install": False,
}
