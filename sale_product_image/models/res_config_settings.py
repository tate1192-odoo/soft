# -*- coding: utf-8 -*-
# Copyright (C) 2026 Softteknik Bilişim
# Website: https://softteknik.com
# License: LGPL-3 (https://www.gnu.org/licenses/lgpl-3.0.html)

from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    show_image_in_report = fields.Boolean(
        string="Show Product Image in PDF Reports",
        config_parameter='sale_product_image.show_image_in_report',
        help="Print a product image column in the quotation and sale order "
             "reports. The column is left out when no line carries an image.",
    )
