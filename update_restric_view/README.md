Sale and Purchase Quick-Create Disabler
=======================================

Removes the quick-create and create/edit actions from selected many2one fields in
Sale Order and Purchase Order forms.

This is a UI-only module: it does not change access rights or record rules, and
users can still create partners, products or other records from their own menus.

Covered fields
--------------

* ``sale.order``: ``partner_id``, ``partner_invoice_id``, ``partner_shipping_id``
* ``sale.order.line``: ``product_id``, ``product_template_id``
* ``purchase.order.line``: ``product_id``

The invoice and shipping partner fields are only visible to users in the
``account.group_delivery_invoice_address`` group.

The module sets ``no_create``, ``no_quick_create`` and ``no_create_edit`` on the
many2one options. It keeps the core ``show_label_warning`` option on product
fields.

Installation
------------

Install ``update_restric_view``; ``sale`` and ``purchase`` are installed
automatically.

Tests
-----

``tests/test_update_restric_view.py`` checks the combined form views:

* sale partner field options;
* sale product and product-template options;
* purchase product options;
* preservation of the core ``show_label_warning`` option.

License
-------

LGPL-3.
