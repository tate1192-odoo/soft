# -*- coding: utf-8 -*-
# Copyright (C) 2026 Softteknik Bilişim
# Website: https://softteknik.com
# License: LGPL-3 (https://www.gnu.org/licenses/lgpl-3.0.html)

import base64
import binascii
import io
import logging

from PIL import Image as PILImage

from odoo import api, fields, models

_logger = logging.getLogger(__name__)


class SaleOrderLine(models.Model):
    _inherit = 'sale.order.line'

    order_line_image = fields.Binary(
        string="Image",
        related="product_id.image_128",
        help="Product image shown in the sale order line list.",
    )

    image_for_report = fields.Binary(
        string="Report Image",
        compute="_compute_image_for_report",
        help="Product image converted to JPEG on a white background, so the "
             "PDF report prints it without transparency artefacts.",
    )

    @api.depends('order_line_image')
    def _compute_image_for_report(self):
        """Re-encode the product image as an opaque JPEG for the PDF report."""
        for line in self:
            line.image_for_report = False
            source = line.order_line_image
            if not source:
                continue
            try:
                with PILImage.open(io.BytesIO(base64.b64decode(source))) as image:
                    if image.mode in ('RGBA', 'LA') or (
                            image.mode == 'P' and 'transparency' in image.info):
                        # flatten the alpha channel onto white
                        flat = image.convert('RGBA')
                        background = PILImage.new('RGB', flat.size, (255, 255, 255))
                        background.paste(flat, mask=flat.split()[3])
                        rgb_image = background
                    elif image.mode == 'RGB':
                        rgb_image = image
                    else:
                        rgb_image = image.convert('RGB')

                    output = io.BytesIO()
                    rgb_image.save(output, format='JPEG', quality=95)
                    line.image_for_report = base64.b64encode(output.getvalue())
            except (OSError, ValueError, binascii.Error) as error:
                # unreachable through the ORM (the image fields reject
                # undecodable data); it guards a row corrupted outside Odoo.
                _logger.warning(
                    "Sale order line %s: report image skipped (%s)", line.id, error)
