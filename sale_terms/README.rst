Sale Terms
==========

Reusable up-line and down-line terms on quotations and sale orders.

The module adds a **Terms** page to the sale order form with two independent
HTML blocks:

* **Terms Up** - introductory text printed before the order lines (for example
  a quotation cover letter).
* **Terms Down** - conditions printed after the order totals (for example
  delivery, payment or warranty terms).

Both blocks are materialised from templates when the order is created, stored on
the order in the customer language and printed on the standard quotation/sale
order report.

Templates
---------

Go to ``Sales > Configuration > Terms Templates`` and create reusable templates:

* **Position** - ``Up Line`` or ``Down Line``; only templates of the matching
  position can be selected on the corresponding order field.
* **Priority** - mark one template per position/company as ``High``; it becomes
  the default for new orders in that company.
* **Company** - templates are company-specific. A template without a company is
  a global fallback; the default lookup prefers the current company, then the
  global record.
* **Terms Content** - HTML content, translatable.

The module ships two example templates (a CIF terms text and a quotation cover
letter). They are normal data records: edit, deactivate or replace them.

Behaviour
---------

* On order creation the linked template content is copied to ``sale_terms_up`` /
  ``sale_terms_down``; existing content is never overwritten.
* Changing the template in the form fills the matching content field through an
  onchange.
* Archived high-priority templates are not selected.
* The same rules apply to batch-created orders.
* The terms are printed on the standard ``sale.report_saleorder`` report:
  up-line before the order lines, down-line after the totals.
* Deleting a template is restricted to the Sales Manager group; salespeople can
  create, edit and read templates.

Installation
------------

Install ``sale_terms``; the ``sale`` module is installed automatically.

Tests
-----

``tests/test_sale_terms.py`` covers template defaults, company filtering,
archived templates, explicit content preservation, batch creation, onchange,
print rendering and delete permissions.

License
-------

LGPL-3.

Credits
-------

Softteknik Bilişim.
