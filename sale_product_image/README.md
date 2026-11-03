# Sale Product Images (Odoo 19)

Product thumbnails inside the sale order line table and inside the printed
quotation / sale order PDF report.

## Features

* Thumbnail column in the sale order form line list, driven by
  `product.template.image_128` (no extra storage).
* **Per user** line column: the list field carries `optional="show"`, so each
  user turns the thumbnail column off/on from the list header. No global
  setting, no extra field.
* Product image column in the Quotation and Sale Order PDF reports. The column
  is dropped from the PDF when no line carries an image, so a picture-less
  quotation never prints an empty column.
* Report images are re-encoded to JPEG on a white background, so transparent
  PNGs and wide pictures print without artefacts.
* Odoo 19 Community: depends on `sale_management` only. Pillow (used for the
  JPEG re-encoding) is already an Odoo core dependency, nothing to install.
* Turkish (`tr`) translation included.

## Configuration

1. **Order lines** — nothing to configure: the column is on by default and each
   user hides or shows it from the list header (the column chooser).
2. **PDF reports** — *Sales > Configuration > Settings* → **Show Product Image in
   PDF Reports**. The column is printed only when at least one order line has an
   image.

## Usage

1. Create a quotation and add products that carry an image.
2. The image column appears next to the product name.
3. Print the quotation / sale order: the PDF contains the image column.

## Technical notes

* `sale.order.line.order_line_image` is a non-stored related field on
  `product_id.image_128`; the form list field is declared with
  `optional="show"`.
* `sale.order.line.image_for_report` is a non-stored compute field that
  converts the product image to a JPEG with a white background. It falls back
  to the original image when Pillow cannot decode it.
* The report template reads the switch itself, in core's own flag block: the
  `t-set` is anchored after `//t[@t-set='display_taxes']`, so it sits with
  `display_discount` / `hide_taxes_details` / `display_taxes`, before the editable
  `oe_structure` zone and the table:
  `show_report_image = <param> in ('True', '1') and any(l.order_line_image for l in lines_to_report)`.
  No field is added to `sale.order` just to carry a global setting.
  The header cell also bumps `colspan_count`, which core uses for the section and
  note rows, so the totals stay aligned.
* Parameter key: `sale_product_image.show_image_in_report`. The settings checkbox
  stores the string `'True'`; unchecking deletes the key.

## Known limitations

* The customer **portal** page of a quotation renders its own product table
  (`sale.view_sale_order_portal_content`), not the report template, so the
  on-screen portal view has no image column. The PDF download does (it uses
  `sale.report_saleorder`).
* `image_for_report` is a non-stored compute fed by a related field. Inside one
  transaction, writing a new product image and reading the same order lines
  afterwards still returns the old picture until the cache is dropped
  (`invalidate_recordset()`); a new request (form, PDF) is always correct.
  Scripts that update product images and print in the same transaction must
  invalidate.

## License

LGPL-3 — https://www.gnu.org/licenses/lgpl-3.0.html

## Author

Softteknik Bilişim — https://softteknik.com
