# Soft Report Generator — Word Template Engine (Odoo 19)

Prints `.docx` templates for any Odoo model: upload the file, map its
`{{placeholders}}` to fields, print. PDF/HTML/ODT/RTF output is converted by
LibreOffice; `output_format = original` returns the docx unchanged.

## Requirements

| Requirement | Notes |
|---|---|
| Odoo 19.0 | Community or Enterprise |
| LibreOffice (`soffice`) | Only for PDF / HTML / ODT / RTF output. `output_format = original` (docx) works without it. |
| `lxml`, `Pillow` | Ship with Odoo (`requirements.txt`); Pillow is optional (image size falls back to header parsing). |
| `pypdf` or `PyPDF2` | Only for merging several PDFs into one; `pypdf` is preferred, `PyPDF2` is accepted. |

## Workflow

1. Create a **Report Template**, pick the Odoo model it prints (e.g. *Sales Order*).
2. Upload the `.docx` on the **Template File** tab.
3. **Parse Template** — every `{{placeholder}}` in the document (body, tables,
   headers and footers) is detected and auto-mapped to a field when the name
   matches; the rest stay empty for manual mapping in **Field Mappings**.
4. **Activate** — creates a server action on that model bound as a *report*, so
   the template appears in the record's **Print** menu as “Print: <template
   name>” (restricted to the *Report Generator / User* group).
5. **Test Report** / **Preview PDF** generate the document with the first
   record of the model (preview opens in the browser).
6. Optionally set a **domain** so the template is only offered for matching
   records, and a **cover page** `.docx` that is rendered with the same data and
   prepended to the PDF.

## Template syntax

### Values

| Syntax | Meaning |
|---|---|
| `{{name}}` | Field of the record being printed. |
| `{{partner_id.name}}` | Dot path through relational fields (any depth). |
| `{{partner_id.city}}` | Same, resolved at render time. |
| `{{field\|pipe}}` | Value passed through a format pipe (see below). |
| `{{description}}` | HTML field → rendered as formatted Word runs (see *HTML fields*). |
| `{{img:company_id.logo}}` | Binary field → inline image (max 15 × 10 cm). |

Placeholders work in the document body, in table cells, and in
headers/footers (every `word/*.xml` part is processed). One caveat: image
relationships are only added to the main document part, so `{{img:…}}` is
reliable in the body — in a header/footer the text placeholders are replaced
but the image will not resolve.

### Format pipes

| Pipe | Effect |
|---|---|
| `upper` / `lower` / `title` | Text case. |
| `date` | `format_date` in the record's language (falls back to `dd/mm/yyyy`). |
| `datetime` | `format_datetime` in the user's timezone. |
| `currency` | `formatLang` with the record's `currency_id`. |
| `number` | `formatLang` without a currency. |

### Expressions

`{{=expression}}` is evaluated with `safe_eval`. The namespace contains the
mapped values, `time`, `datetime`, and `o` / `record` — a **field-only proxy**
of the record (`o.partner_id.name`, `o.amount_total`). The environment, the
cursor and the ORM methods are deliberately not reachable, so a template stays
data, never code.

```
{{=amount_untaxed + amount_tax}}
{{=o.partner_id.name.upper()}}
```

### Conditionals

```
{{#if state == 'sale'}}
  …shown for confirmed orders…
{{#else}}
  …otherwise…
{{/if}}
```

`{{#if field_name}}` (a bare field path) tests truthiness without an
expression. Blocks can be nested; the marker paragraphs or table rows are
removed from the output. Content controls (`w:sdt`) are traversed like any
other container, and a block inside a loop row is evaluated against **that
row's** record.

A block written inside a single paragraph (`Total: {{#if taxed}}incl. VAT{{/if}}`)
is resolved in place — only the markers disappear, the surrounding text stays.
Expressions and conditions resolve bare field names from the record, so
`{{=amount_total * 0.1}}` works even when `{{amount_total}}` is not printed
elsewhere in the document.

### Loops

```
{{#order_line}}                     ← marker row, removed
| {{product_id.name}} | {{name}} | {{product_uom_qty}} | {{price_unit}} | {{price_subtotal}} |
{{/order_line}}                     ← marker row, removed
```

* Loops expand **table rows** only: the rows between the two markers are
  repeated once per item. A loop written in plain paragraphs does nothing.
* The loop placeholder itself must be mapped to a `One2many` / `Many2many`
  field (validated on *Activate*); its children need **Loop Parent** set to the
  loop placeholder.
* Child placeholders resolve against the loop's model first, then fall back to
  the parent record — so `{{master_product_id.proforma_name}}` works inside an
  `order_line` loop when the field lives on the order.
* Rows whose record has a `display_type` (section / note lines) are skipped.
* Nested loops are not supported.

### Images

* `{{img:field}}` — base64/binary field of the record (or of the loop item).
* Inside HTML fields, `<img src="data:image/png;base64,…">` and Odoo
  `/web/image/<model>/<id>/<field>` sources are supported.

Images are scaled to fit 15 cm × 10 cm, assuming 96 dpi.

### HTML fields

A placeholder mapped to an `html` field is not dumped as raw markup: the HTML
is converted into Word runs, keeping `<b>/<strong>`, `<i>/<em>`, `<u>/<ins>`,
`<br>`, `<p>`, `<ul>/<ol>/<li>`, `<img>`, `<a>`, `<span>`, `<div>` and
`<h1>`–`<h6>`.

### Tax totals (sale.order / account.move)

The module reads the record's `tax_totals` (JSON/Binary in Odoo 17+) and
exposes it without any field mapping:

| Placeholder | Value |
|---|---|
| `{{tax_totals_total}}` | Tax-included total. |
| `{{tax_totals_cash_rounding}}` | Cash-rounding amount, if any. |
| `{{tax_totals_same_tax_base}}` | Whether the tax groups share one base. |
| `{{tax_totals_has_cash_rounding}}` | Boolean, useful in `{{#if}}`. |

Two loops are available as well:

* `{{#tax_groups}}` → `subtotal_name`, `subtotal_base`, `group_name`,
  `tax_amount`, `base_amount`
* `{{#tax_subtotals}}` → `name`, `base_amount`

## Available values (hints)

Pick a model and the **Available Values** tab lists the placeholders that make
sense for it, ready to copy into the `.docx`. One resolver feeds that tab, the
draft help box and the field-path validation on *Activate*; three sources are
used, first one wins per path:

1. **Declaration** — the target model defines `_soft_report_value_hints()` and
   returns its own list (a module that already has an allow-list stays the
   source of truth):

   ```
   # models/some_model.py
   def _soft_report_value_hints(self):
       return [
           {'path': 'partner_id.name', 'label': 'Customer'},
           {'path': 'signature', 'kind': 'image'},
           {'path': 'line_ids', 'kind': 'loop'},
       ]
   ```

2. **QWeb reports** — the `ir.actions.report` records of that model, following
   `t-call` chains into the document template: what the module already prints
   (`t-field="doc.x"`, `t-foreach` → loop hints with their child fields).
   Nothing to declare, and customised views are picked up.
3. **Field types** — syntax examples from `ir.model.fields` (char / monetary /
   date / many2one / html / binary / one2many).

Hints are guidance, not permissions: the engine still resolves any field of the
model. Fields that require a group are marked (`note`) in the list.

## Model-specific add-ons

Core depends on `base` and `mail` only; model-specific helpers ship as
`auto_install` bridges:

| Module | Adds |
|---|---|
| `soft_report_generator_sale` | `has_discount` / `has_tax` flags, the *Print Quotation (Soft Report)* menu entry, sale-order template tests |

## Output

| `output_format` | Result |
|---|---|
| `original` | The rendered `.docx`. |
| `pdf`, `html`, `odt`, `rtf` | Converted headlessly by LibreOffice. |

* **Merge into Single PDF** (default on): printing several records produces one
  PDF; when off, a ZIP archive with one file per record is returned.
* **Cover Page**: an optional `.docx` rendered with the same context and
  prepended to the PDF (the *Preview PDF* button and the HTTP preview route
  both honour it).
* `original` returns the **rendered** `.docx` (placeholders replaced), not the
  uploaded template.
* Generated files are stored as `ir.attachment` records and served through
  `/web/content/<id>`; they are not garbage-collected automatically.

## HTTP endpoints

| Route | Purpose |
|---|---|
| `/soft_report_generator/preview/<template_id>/<record_id>` | Inline PDF preview. |
| `/soft_report_generator/download/<template_id>/<record_id>` | Download in the template's output format. |

Both require the *Report Generator / User* group (checked explicitly — the
route answers **404** outside the group) and check read access on the record.

## Security

* Groups: *Report Generator / User* (read, print) and *Manager* (edit templates).
* Menus are restricted to the User group.
* Multi-company rules apply to templates and their field mappings
  (`company_id`, or the template's company for a mapping row).

## Known limitations

* Loops only expand table rows; paragraph-level and nested loops are not
  supported.
* `{{=…}}` cannot call ORM methods or touch the environment (by design).
* Images are sized at 96 dpi and capped at 15 × 10 cm.
* LibreOffice is required for every non-docx output; without it the module
  raises a `UserError` with install hints.
* A conversion is started per print request with its own LibreOffice profile —
  expect a few seconds per document on a busy server.

## Tests

```
odoo-bin -c <conf> -d <db> -i soft_report_generator \
    --test-enable --test-tags=/soft_report_generator --stop-after-init
```

The core suite builds its `.docx` fixtures in memory, so it needs no sample
file; the sale-order fixture ships with `soft_report_generator_sale`. Generator
scripts and sample outputs live outside the module, in
`../_soft_report_generator_dev/`.

```
odoo-bin -c <conf> -d <db> -i soft_report_generator_sale \
    --test-enable --test-tags=/soft_report_generator_sale --stop-after-init
```
