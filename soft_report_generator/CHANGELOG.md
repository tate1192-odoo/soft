# Changelog

All notable changes to **soft_report_generator** are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [19.0.1.0.0] - 2026-11-10

İlk sürüm: modülün bu repoya girişi (PR #47). Çekirdek `soft_report_generator`
1.0.0, köprü `soft_report_generator_sale` 1.0.0.

Modül bu reponun dışında geliştirildi ve orada 1.0.3'e kadar ilerledi; buradaki
ilk sürüm 1.0.0'dır, dışarıdaki tüm turlar bu sürümün içinde. Kod tarafında
değişen bir şey yok, yalnızca sürüm numarası reponun kuralına çekildi.

### Added

- Model-agnostic DOCX template engine for any Odoo model: `{{placeholder}}`
  mapping, dot paths (`partner_id.city`), format pipes (`|currency`, `|date`,
  `|datetime`, `|number`, `|upper`, `|lower`, `|title`), expressions
  (`{{=amount * 0.1}}`), conditionals (`{{#if}}` / `{{#else}}` / `{{/if}}`,
  inline or as a block), table-row loops, `{{img:field}}` images and HTML
  fields rendered as formatted runs.
- Output as the template itself or as PDF / HTML / ODT / RTF through
  LibreOffice, cover-page merge, PDF product-document merge, multi-record PDF
  merge (ZIP fallback), TR translations and multi-company rules.
- **Value hints** (`models/value_hints.py`): one resolver that answers "what can
  I print for this model", fed by three sources — a model declaration
  (`_soft_report_value_hints()`), the QWeb reports already printing the model
  (`ir.actions.report` arch, following `t-call` chains, loops included) and the
  field types. Exposed as the *Available Values* tab (visible to the module's
  user group) and as generated examples in the draft help box.
- Field-path validation on *Activate*: a mapping pointing at a field that does
  not exist on the model now raises a `UserError` instead of printing an empty
  cell. Loop children are validated against their loop's comodel and the
  synthetic `tax_totals_*` / `tax_groups` / `tax_subtotals` placeholders are
  skipped.
- `soft_report_generator_sale`: `has_discount` / `has_tax` flags and the
  *Print Quotation (Soft Report)* entry, which falls back to a template picker
  when several templates match.

### Fixed

- DOCX: spaces between inline HTML nodes were dropped, so `<p>Hello
  <b>World</b> again</p>` printed `HelloWorldagain`. Text nodes are no longer
  stripped individually, and HTML comments are no longer printed as text.
- DOCX: `{{#if}}` blocks inside a `w:sdt` content control were ignored, so the
  block was always printed. Content controls are now traversed.
- DOCX: conditionals and `{{img:…}}` inside a loop row were evaluated against
  the parent record. Loops now expand first and each copied row is rendered
  with its own record (conditionals, images and values).
- DOCX: `{{#if}}` opened and closed in the same paragraph deleted the whole
  paragraph, text included. Inline blocks are now rendered in place; only the
  markers are removed.
- DOCX: images inserted into a header/footer were declared in
  `document.xml.rels` instead of the owning part's `.rels`, leaving a dangling
  `r:embed` that makes Word offer to repair the document.
- DOCX: `<Default>` content-type entries were appended after `<Override>`,
  breaking OOXML element order for every document that gained an image.
- DOCX: `{{#if amount_total > 100}}` / `{{=amount_total * 0.1}}` raised
  `NameError` when the field was not printed elsewhere in the document: the
  expression namespace only carried values mapped as placeholders. Bare field
  names used in an expression are now resolved from the record (and from the
  parent record inside a loop).
- Controller: `@http.route(groups=…)` does not exist in Odoo 19 (the key is
  dropped), so the group was never enforced; the check is now explicit and
  answers 404 outside the group instead of raising `AccessError` (500).
- Controller: the HTTP preview route ignored the cover page and built
  `Content-Disposition` by hand. Both preview paths now share
  `_render_preview_pdf()` and `content_disposition()` (RFC 5987).
- Generated print actions (`ir.actions.server`) and the sale print action are
  restricted to the *Report Generator / User* group; they used to show up for
  every internal user, who then got an `AccessError`.
- `generate_report()` on a template without a file raised a raw `TypeError`
  (500 page); it now raises the same `UserError` as *Parse Template*.
- `write({'template_file': …})` on several records raised "Expected singleton"
  and mutated the caller's `vals` dict; both fixed.
- Unmapped placeholders are still printed as-is but now log a warning.

### Changed

- *Activate* binds the generated server action with `binding_type = 'report'`,
  so the template appears in the **Print** menu (it used to land in the Action
  gear menu). Existing generated actions are moved on the next *Activate*.
- PDF preview logic lives in one place (`_render_preview_pdf`), used by the
  button, the HTTP route and both cover-page paths.
- The draft help box no longer hard-codes sale-order field names; the syntax
  list is generic and the examples come from the selected model.
