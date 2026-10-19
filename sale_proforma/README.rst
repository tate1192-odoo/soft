Sale Proforma
=============

Adds a reusable **Proforma** block to quotations, sale orders and the standard
sale order PDF.

The proforma is stored on the order as HTML, so its wording can be adapted per
customer and it is printed after the order totals.

Templates
---------

Go to ``Sales > Configuration > Proforma Document`` and create templates:

* **Name** - template name shown in the order form.
* **Priority** - mark one template per company as ``High``; it is used when a
  confirmed order has no proforma content yet.
* **Company** - templates are company-specific. A template without a company is
  a global fallback used when the order company has no own high-priority
  template.
* **Proforma Content** - translatable HTML content.

The module ships one example leasing proforma. It is a normal data record: edit,
deactivate or replace it.

Behaviour
---------

* The **Proforma** page is available on quotations and sale orders and hidden
  only for cancelled orders.
* Selecting a template in the form loads its content through an onchange.
* Confirming an order whose ``sale_proforma`` is empty seeds it from the
  high-priority template of the order's company (or the global fallback).
* Existing proforma content is never overwritten.
* Archived templates are not used.
* The proforma is printed on ``sale.report_saleorder`` after the order totals.
* Salespeople can create, edit and read templates; deleting a template is
  restricted to the Sales Manager group.

Installation
------------

Install ``sale_proforma``; the ``sale`` module is installed automatically.

Tests
-----

``tests/test_sale_proforma.py`` covers template selection on confirm, explicit
content preservation, archived and company-specific templates, the global
fallback, the onchange, print rendering and delete permissions.

License
-------

LGPL-3.

Credits
-------

Softteknik Bilişim.
