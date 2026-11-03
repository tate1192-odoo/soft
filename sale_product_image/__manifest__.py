# -*- coding: utf-8 -*-
# Copyright (C) 2026 Softteknik Bilişim
# Website: https://softteknik.com
# License: LGPL-3 (https://www.gnu.org/licenses/lgpl-3.0.html)

{
    'name': 'Sale Product Images',
    'version': '19.0.1.0.0',
    'category': 'Sales/Sales',
    'summary': 'Product thumbnails in sale order lines and in the printed '
               'quotation PDF.',
    'description': """
Sale Product Images
===================
Product image thumbnails inside the sale order line table and inside the
printed Quotation / Sale Order PDF report.

Features
--------
* Thumbnail column on the sale order form line list, on by default and per
  user: the column carries optional="show", so anyone hides or shows it from
  the list header.
* One switch in Sales > Configuration > Settings adds the product image column
  to the Quotation and Sale Order PDF reports; the column is dropped when no
  line carries an image.
* Report images are re-encoded to JPEG (white background, no alpha channel) so
  wide picture formats print without black or transparent artefacts.
* Community edition only needs what Odoo already ships (Pillow is a core
  dependency, nothing to install).
""",
    'author': 'Softteknik Bilişim',
    'website': 'https://softteknik.com',
    'support': 'softteknik@softteknik.com',
    'depends': [
        'sale_management',
    ],
    'data': [
        'views/sale_order_line_views.xml',
        'views/res_config_settings_views.xml',
        'report/sale_order_report.xml',
    ],
    'images': [
        'static/description/cover.png',
        'static/description/screenshots/quotation.png',
    ],

    'installable': True,
    'auto_install': False,
    'application': False,
    'license': 'LGPL-3',
}
