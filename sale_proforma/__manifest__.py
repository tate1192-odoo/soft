{
    'name': 'Sale Proforma',
    'summary': 'Proforma invoice block on quotations, sale orders and their PDF',
    'category': 'Sales/Sales',
    'author': 'Softteknik Bilişim',
    'website': 'https://softteknik.com',
    'license': 'LGPL-3',
    'sequence': 140,
    'version': '19.0.1.0.0',
    'depends': [
        'sale',
    ],
    'data': [
        'data/proforma_data.xml',
        'security/ir.model.access.csv',
        'views/proforma_view.xml',
        'views/sale_order_view.xml',
        'views/sale_order_report.xml',
    ],
    'application': True,
    'installable': True,
    'auto_install': False,
}
