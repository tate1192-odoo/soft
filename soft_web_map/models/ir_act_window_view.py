"""Allow the ``leaflet_map`` mode in window-action view definitions."""

from odoo import fields, models

from .ir_ui_view import LEAFLET_MAP_VIEW


class IrActionsActWindowView(models.Model):
    _inherit = "ir.actions.act_window.view"

    view_mode = fields.Selection(
        selection_add=[(LEAFLET_MAP_VIEW, "Leaflet Map")],
        ondelete={LEAFLET_MAP_VIEW: "cascade"},
    )
