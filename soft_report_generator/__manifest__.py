# -*- coding: utf-8 -*-
{
    'name': 'Soft Report Generator - Word Template Engine',
    'version': '19.0.1.0.1',
    'category': 'Productivity',
    'summary': 'Word (.docx) templates -> PDF via LibreOffice; '
               'placeholder mapping, table loops, conditions, HTML fields',
    'description': """
Generic Word template engine for Odoo 19
========================================

Upload a .docx, map its ``{{placeholders}}`` to fields of any Odoo model and
print the result as docx, PDF (converted by LibreOffice), HTML, ODT or RTF.

This is the model-agnostic core. Model-specific helpers live in add-on
modules (e.g. ``soft_report_generator_sale``).
model technical names (``soft.report.template`` and friends) are unchanged.
""",
    'author': 'Softteknik Bilişim',
    'website': 'https://softteknik.com',
    'license': 'AGPL-3',
    'depends': ['base', 'mail'],
    'data': [
        'security/security.xml',
        'security/ir.model.access.csv',
        'wizard/report_template_wizard_views.xml',
        'views/report_template_views.xml',
        'views/menu.xml',
    ],
    'installable': True,
    'application': True,
    'auto_install': False,
}
