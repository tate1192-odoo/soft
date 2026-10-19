{
    'name': 'Sale Agreement',
    'summary': 'Sale agreement templates on quotations, sale orders and their PDF',
    'category': 'Sales/Sales',
    'author': 'Softteknik Bilişim',
    'website': 'https://softteknik.com',
    'license': 'LGPL-3',
    'sequence': 130,
    'version': '19.0.1.0.0',
    'depends': [
        'sale',
    ],
    'data': [
        'security/ir.model.access.csv',
        'views/agreement_view.xml',
        'views/sale_order_view.xml',
        'views/sale_order_report.xml',
    ],
    'application': True,
    'installable': True,
    'auto_install': False,
}
