"""Relax NG validation for the ``leaflet_map`` view type.

When Odoo provides the public ``view_validation`` API, the validator is
registered so that ``ir.ui.view`` rejects malformed architectures at
install/write time.  The import is guarded for future Odoo versions.
"""

import logging
import os
from functools import lru_cache

from lxml import etree

from odoo.tools import misc

try:
    from odoo.tools import view_validation
except ImportError:  # pragma: no cover - future Odoo versions may drop the API
    view_validation = None

_logger = logging.getLogger(__name__)

_RNG_FILE = os.path.join("soft_web_map", "views", "leaflet_map.rng")


@lru_cache(maxsize=1)
def _leaflet_map_validator():
    """Load and cache the Relax NG schema for ``leaflet_map`` views."""
    with misc.file_open(_RNG_FILE) as schema_file:
        return etree.RelaxNG(etree.parse(schema_file))


if view_validation is not None:

    @view_validation.validate("leaflet_map")
    def validate_leaflet_map_view(arch, **kwargs):
        """Return ``True`` when ``arch`` matches the ``leaflet_map`` schema."""
        validator = _leaflet_map_validator()
        if validator.validate(arch):
            return True
        for error in validator.error_log:
            _logger.error("Invalid leaflet_map view architecture: %s", error)
        return False
