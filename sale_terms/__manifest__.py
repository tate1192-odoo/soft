{
    'name': 'Sale Terms',
    'summary': 'Reusable up-line and down-line terms on quotations and sale orders',
    'category': 'Sales/Sales',
    'author': 'Softteknik Bilişim',
    'website': 'https://softteknik.com',
    'license': 'LGPL-3',
    'sequence': 120,
    'version': '19.0.1.0.0',
    'depends': [
        'sale',
    ],
    'data': [
        'data/sale_terms_data.xml',
        'data/sale_terms_cleanup.xml',
        'security/ir.model.access.csv',
        'views/terms_view.xml',
        'views/sale_order_view.xml',
        'views/sale_order_report.xml',
    ],
    'application': True,
    'installable': True,
    'auto_install': False,
}
