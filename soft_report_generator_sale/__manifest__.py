# -*- coding: utf-8 -*-
{
    'name': 'Soft Report Generator - Sales',
    'version': '19.0.1.0.0',
    'category': 'Productivity',
    'summary': 'Sales-order helpers for Soft Report Generator: '
               'has_discount / has_tax flags and the Print menu entry',
    'description': """
Sales-order binding for Soft Report Generator
=============================================

The core module (``soft_report_generator``) is model-agnostic: it renders a
``.docx`` template for any Odoo model. This bridge adds everything that is
specific to ``sale.order``:

* ``has_discount`` / ``has_tax`` computed booleans, usable as
  ``{{#if has_discount}}`` in a template;
* "Print Quotation (Soft Report)" in the *Print* menu, which picks the template
  by domain and asks with a wizard when several templates match.

It is ``auto_install``: on a database that has both the core module and
``sale`` it is installed by itself, so keeping the previous behaviour needs no
manual step.
""",
    'author': 'Softteknik Bilişim',
    'website': 'https://softteknik.com',
    'license': 'AGPL-3',
    'depends': ['soft_report_generator', 'sale'],
    'data': [
        'data/print_actions.xml',
    ],
    'installable': True,
    'application': False,
    'auto_install': True,
}
