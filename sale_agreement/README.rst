Sale Agreement
==============

Adds a reusable **Agreement** block to quotations, sale orders and the standard
sale order PDF.

The agreement is stored on the order as HTML, so its wording can be adapted per
customer and it is printed after the order totals.

Templates
---------

Go to ``Sales > Configuration > Agreement Templates`` and create templates:

* **Name** - template name shown in the order form.
* **Priority** - mark one template per company as ``High``; it is used when a
  confirmed order has no agreement content yet.
* **Company** - required; a template belongs to one company and is only offered
  on orders of that company.
* **Agreement Content** - translatable HTML content.

Behaviour
---------

* The **Agreement** page is available on quotations and sale orders and hidden
  only for cancelled orders.
* Selecting a template in the form loads its content through an onchange;
  clearing the template clears the content.
* Confirming an order whose ``sale_agreement`` is empty seeds it from the
  high-priority template of the order's company.
* Existing agreement content is never overwritten.
* Archived templates are not used.
* The agreement is printed on ``sale.report_saleorder`` after the order totals.
* Salespeople can create, edit and read templates; deleting a template is
  restricted to the Sales Manager group.

Installation
------------

Install ``sale_agreement``; the ``sale`` module is installed automatically.

Tests
-----

``tests/test_sale_agreement.py`` covers template selection on confirm, explicit
content preservation, archived and company-specific templates, the onchange,
page visibility, print rendering and delete permissions.

License
-------

LGPL-3.

Credits
-------

Softteknik Bilişim.
