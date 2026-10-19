{
    "name": "Sale and Purchase Quick-Create Disabler",
    "version": "19.0.1.0.0",
    "category": "Sales/Sales",
    "summary": "Remove quick-create and create/edit links in Sale and Purchase forms",
    "author": "Softteknik Bilişim",
    "website": "https://softteknik.com",
    "license": "LGPL-3",
    "sequence": 100,
    "depends": [
        "sale",
        "purchase",
    ],
    "data": [
        "views/sale_views.xml",
        "views/purchase_order.xml",
    ],
    "installable": True,
    "auto_install": False,
    "application": False,
}
