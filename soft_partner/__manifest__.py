{
    'name': 'Soft Partner',
    'version': '19.0.1.0.0',
    'summary': 'Partner code sequence (partner_code), structured partner '
               'categories (Company, Bronze - Diamond, Supplier) and commercial '
               'weight segments (Key account, Regular, One off, Passive, '
               'Prospect) with bulk assignment actions',
    'author': 'Softteknik Bilişim',
    'website': 'https://softteknik.com',
    'license': 'LGPL-3',
    'category': 'Sales/Sales',
    'depends': [
        'contacts',
        'base_geolocalize',
    ],
    'data': [
        'security/ir.model.access.csv',
        'data/partner_sequence.xml',
        'data/partner_category_data.xml',
        'data/partner_segment_data.xml',
        'views/res_partner_views.xml',
        'views/partner_category_views.xml',
        'views/partner_category_wizard_views.xml',
        'views/partner_segment_views.xml',
        'views/partner_segment_wizard_views.xml',
        'views/partner_code_resequence_view.xml',
    ],
    'application': False,
    'installable': True,
    'auto_install': False,
}
