Soft EKAP Tender
================

Tender follow-up and bid pricing for Turkish public tenders (EKAP).

The module records the tenders a company follows, prices the offer and checks it
against the rules of the Public Procurement Law (Law 4734) *before* the
offer is given on EKAP. It does not submit anything to EKAP and does not read the
closed EKAP endpoints.

What it does
------------

* **Tender** (``ekap.tender``): tender reference number (İKN), contracting
  authority, province, tender type (goods / construction / services /
  consultancy) and procedure, announcement and deadline datetimes, approximate
  cost, limit value and its source, state, documents and chatter.
* **Work items** (``ekap.tender.item``): the unit-price bid schedule — item
  code, description, OKAS code, quantity, unit, the authority's unit price and
  the offer unit price.
* **Public analyses** (``ekap.analysis``): the inputs of an analysis (material,
  labour, machine, transport, other) with the 25% profit and general expenses
  used by public analyses.
* **Bid** (``ekap.bid``): one offer per attempt, generated from the tender items,
  priced per item or with a bulk discount coefficient, checked against the limit
  value, the labour floor, securities, stamp duty and VAT.
* **Limit value wizard**: computes the limit value from the bids given in the
  tender (works and services) and writes it back on the tender.
* **Labour calculation** (``ekap.labor.calc``): the minimum cost per worker and
  month using the components of the KİK labour module.
* **Report**: the *Unit Price Bid Schedule* PDF with bid lines, securities,
  taxes and the result of the controls.
* **Award result**: winning firm, contract price and number of valid bids from
  the result notice. The discount follows from the approximate cost, and the
  tender shows what the results recorded in the database say about the same
  authority: how many results exist, their mean discount and mean number of
  valid bids.

Where the numbers come from
---------------------------

No rate is hard-coded. Every rate or coefficient is an ``ekap.parameter`` row
with an effective date, a source and an optional company:

* construction works limit value coefficient (KGT 45.1.1.1) — ``WORKS_N_*``;
* service limit value coefficients (KGT 79.1.2) — ``SERVICE_R_*``, per KİK year;
* provisional security, minimum 3% of the bid (Law 4734 art.33);
* final security, 6% of the bid (Law 4734 art.43);
* final security of a construction bid below the limit value, on the
  approximate cost (Law 4734 art.43);
* stamp duty of the award decision and of the contract (Law 488);
* VAT (Law 3065);
* profit and overhead of a public analysis (25%);
* employer and employee social security shares (Law 5510 / 4447);
* meal rate (KGT 79.7) and contract/general overhead of the labour minimum
  (3%).

Two things are deliberately **not** seeded:

* the minimum wage periods (``ekap.labor.rate``) — the gross wage is a decision
  of the Minimum Wage Fixing Commission; add one record per period. Without a
  period covering the tender date the labour calculation raises instead of
  inventing a number;
* several seeded rates carry a ``(verify)`` note in their ``source`` field.
  Check them against the current Communiqué / KİK announcement before a real
  bid. Service coefficients change every year.

Configuration
-------------

1. Install the module; the *Tender* application appears in the apps menu.
2. *Tender → Configuration → Parameters*: review the rates. The records are
   ``noupdate="1"``, so a later module update will not overwrite your edits.
3. *Tender → Configuration → Minimum Wage Periods*: add the current period.
4. *Tender → Configuration → Labour Calculations* (optional): pre-compute the
   labour floor of a tender and link it to the tender for the check.
5. Give users the *Tender User* group; parameters are maintained by *Tender
   Manager* only.

Legal and technical scope
-------------------------

A bid is given in the EKAP desktop application with the e-signature of the
authorised signatory, and the e-key must reach EKAP before the bid opening time.
KİK states that no web service exists for submitting bids on behalf of a firm
(kik.gov.tr/Duyuru/236). This module therefore does **not** submit anything to
EKAP, does not produce e-signatures and does not read the internal API of
ekapv2: it prepares and checks the numbers; the offer itself is given on EKAP.

The public EKAP query endpoints are protected by a human-verification step
(Cloudflare Turnstile). The module never tries to solve a captcha, drive a
stealth browser or reuse a verified session. Tenders are entered by hand —
İKN, authority, dates — which is what the record's help texts describe.

The output of the engine is a check, not a legal opinion: the contracting
authority's commission decides.

Tests
-----

::

    odoo-bin -u soft_ekap_ihale -c <config> -d <db> --test-enable \
        --test-tags /soft_ekap_ihale --stop-after-init

The suite covers the two limit value formulas, the abnormally low bid states,
the labour floor arithmetic, securities, stamp duty, VAT, the amount parser,
access rights, company-specific parameters, the tender → items → bid → controls
flow, the lowest-bid selection and the award result/history. **49 tests.**

License
-------

LGPL-3.

Credits
-------

Softteknik Bilişim (<https://www.softteknik.com>).
