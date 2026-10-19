"""Expose the Leaflet configuration to the web client session."""

from odoo import models

CONFIG_KEY_MAP = {
    "soft_web_map.tile_url": "leaflet.tile_url",
    "soft_web_map.copyright": "leaflet.copyright",
}


class IrHttp(models.AbstractModel):
    _inherit = "ir.http"

    def session_info(self):
        """Add the tile URL and copyright to the session information."""
        info = super().session_info()
        parameters = self.env["ir.config_parameter"].sudo()
        for key, legacy_key in CONFIG_KEY_MAP.items():
            # Read the namespaced key first; fall back to the historical
            # generic key so existing databases keep working.
            info[key] = parameters.get_param(key) or parameters.get_param(
                legacy_key, default=""
            )
        return info
