EKAP Tender Tracking
====================

EKAP tender outcome tracking on top of the **Soft EKAP Tender** engine.

This is a separate add-on: it does not duplicate the tender, bid or calculation
models. It depends on ``soft_ekap_tender`` and keeps the old module installable.

What it adds
------------

- **Our rank** in the result notice.
- **Winning bid** amount (the winner's bid, separate from the contract price).
- **Result date**.
- **Loss reason** (price, technical score, document/qualification, disqualified,
  cancelled, other).
- **Gap to winning bid**, in money and percent: positive means our best bid was
  lower than the winner's, negative means it was higher.
- **Notes for the next bid**: the lesson to carry into the next tender.

The fields are available on the tender form under the **Tracking** page, in the
tender list, and as search filters/group-by on the loss reason.

Installation
------------

Install ``ekap_tender_tracking``; ``soft_ekap_tender`` is installed
automatically.

Tests
-----

``tests/test_tracking.py`` covers the positive/negative gap, the empty case and
the presence of the tracking fields on the form.

License
-------

LGPL-3.

Credits
-------

Softteknik Bilişim.
