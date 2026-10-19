Soft Partner
============

Partner code, structured categories and commercial segments in one add-on.

Partner code sequence
---------------------

The ``partner_code`` field is taken from the ``res.partner`` sequence (prefix
``P/``, 5 digits) on creation and on copy. It is assigned to commercial
partners only and is a commercial field, so it is written on the parent company
and propagated to its contacts. The standard Odoo ``Reference`` (``ref``) field
is left untouched.

Partner categories
------------------

Structured classification of customers and vendors with predefined categories
(Company, Bronze, Silver, Gold, Platinum, Diamond, Supplier; editable by the
administrator):

* Category field on the contact form (Geolocation page) and as a column in the
  contacts list.
* Filter and group by on the base partner search view, so partners can be
  grouped and filtered by category in Contacts and any app that selects
  partners.
* Bulk assignment from the contacts list: select partners and use
  ``Action > Assign Partner Category``, or remove the category in one call.
  Selected contacts are assigned through their company.
* Category screen with the partner counter and a filtered partner list.

The category is a commercial field: it is written on the company and propagated
to its contacts. The field is read-only on contacts; edit the company to change
the classification of the commercial partner.

Partner segments
----------------

Second, independent classification axis: how much commercial weight the partner
carries, measured from the invoice history. Predefined segments (editable by the
administrator) and their value bands - the seed values below are EXAMPLES, edit
or deactivate the records to match your own scale:

* ``Key Account`` - example band: last 24 months net revenue >= 100.000 TRY or
  >= 5 invoices.
* ``Regular`` - example band: net revenue 20.000 - 100.000 TRY or 2-4 invoices.
* ``One Off`` - example band: single invoice below 20.000 TRY.
* ``Passive`` - example band: last invoice older than 24 months.
* ``Prospect`` - example band: no invoice yet, but an order, task or CRM trace.
* ``Warm Lead``, ``Reachable Lead``, ``Address Only Lead`` - lead follow-up
  bands for records without business history.
* ``Vendor`` - supplier bill or ``supplier_rank > 0`` without a sales trace.
* ``Junk`` - no invoice, no trace and no usable contact information, kept aside
  for data hygiene.

The segment uses the same mechanism as the category: commercial field propagated
to the contacts, form field, list column, filter and group by, and bulk
assignment in one call (``Action > Assign Partner Segment``). Selected contacts
are assigned through their company. Both classifications and their seed records
are DATA: rename, edit, deactivate or add records without touching the code.

Partner code resequence
-----------------------

Wizard bound to the contacts list (``Action > Resequence Partner Codes``): it
renumbers every commercial partner from the ``res.partner`` sequence in
chronological order (create date), fixing incorrect or missing codes in one
call. Contacts follow the code of their company. The action is restricted to the
Settings group.

Configuration
-------------

* Categories: ``Contacts > Configuration > Partner Categories`` (Settings
  group).
* Segments: ``Contacts > Configuration > Partner Segments`` (Settings group).
* Sequence: Settings > Technical > Sequences, code ``res.partner``.

Tests
-----

``tests/test_partner_ref.py`` and ``tests/test_partner_segment.py`` cover the
sequence, propagation, copy, bulk assignment, resequence and uniqueness
behaviour.

License
-------

LGPL-3.

Credits
-------

Softteknik Bilişim - partner code, category, segment, wizard and view layers.
