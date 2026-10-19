"""Register the ``leaflet_map`` view type on ``ir.ui.view``."""

from odoo import fields, models

LEAFLET_MAP_VIEW = "leaflet_map"


class IrUiView(models.Model):
    _inherit = "ir.ui.view"

    type = fields.Selection(
        selection_add=[(LEAFLET_MAP_VIEW, "Leaflet Map")],
        ondelete={LEAFLET_MAP_VIEW: "cascade"},
    )

    def _get_view_info(self):
        info = super()._get_view_info()
        info[LEAFLET_MAP_VIEW] = {"icon": "fa fa-map-marker"}
        return info
