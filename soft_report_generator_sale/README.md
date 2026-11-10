# Soft Report Generator — Sales

Sales-order binding for [`soft_report_generator`](../soft_report_generator).

The core module is model-agnostic: it renders a `.docx` template for any Odoo
model, using the placeholders the user maps. Everything that only makes sense
for `sale.order` lives here, so the core stays free of a `sale` dependency.

## What this module adds

* `has_discount` / `has_tax` — stored computed booleans on `sale.order`,
  usable in templates as `{{#if has_discount}} … {{/if}}`
  (`has_discount` is true when a non-section line carries a discount,
  `has_tax` when a non-section line has taxes).
* **Print Quotation (Soft Report)** in the *Print* menu (`binding_type =
  report`): picks the active template for `sale.order` by domain (lowest
  `priority` first) and opens a template picker when several match.
* The real-DOCX sale-order fixture and its parse tests (`tests/`).

## Template hints for sale orders

```
Sayın {{partner_id.name}}
Teklif No: {{name}}            Tarih: {{date_order|date}}
{{#order_line}} … {{/order_line}}     ← table rows
{{#if has_discount}} … {{/if}}
Toplam: {{amount_total|currency}}
```

Line children: `product_id.name`, `name`, `product_uom_qty`,
`product_uom_id.name`, `price_unit`, `discount`, `price_subtotal`,
`price_total`, `tax_ids`. Section and note lines are skipped by the loop.
Tax breakdown: `{{tax_totals_total}}`, `{{#tax_groups}} … {{/tax_groups}}`
(see the core README).

## Install

`auto_install = True`: on a database where both `soft_report_generator` and
`sale` are installed, this module installs itself, so behaviour stays identical
to the old single-module setup.

```
odoo-bin -c <conf> -d <db> -i soft_report_generator_sale --stop-after-init
```

## Tests

```
odoo-bin -c <conf> -d <db> -i soft_report_generator_sale \
    --test-enable --test-tags=/soft_report_generator_sale --stop-after-init
```

`tests/test_sale_order_helpers.py` covers the two computed flags, the print
action binding, and the parse of the real sale-order `.docx`
(`tests/files/sale_order_quotation_template.docx`).
