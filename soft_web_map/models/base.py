"""Fallback architecture for the ``leaflet_map`` view type."""

from lxml.builder import E
from odoo import api, models


class Base(models.AbstractModel):
    _inherit = "base"

    @api.model
    def _get_default_leaflet_map_view(self):
        """Return a minimal map view when the model has no stored one.

        The web client may request ``leaflet_map`` for a model that has no
        dedicated view record (for example from a generic action).  In that
        case the map still gets a title based on the model description.
        """
        return E.leaflet_map(string=self._description)
