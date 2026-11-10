# -*- coding: utf-8 -*-

import base64
import logging
import zipfile
from io import BytesIO

from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError
from odoo.tools.safe_eval import safe_eval

_logger = logging.getLogger(__name__)

# Re-export the XML namespace constants from the parser mixin so existing
# imports (``from .models.report_template import W_NS``) keep working.
from .template_parser import (  # noqa: F401
    W_NS, XML_NS, WP_NS, A_NS, PIC_NS, R_NS, REL_NS, CT_NS,
    SYSTEM_LOOPS, SYSTEM_PLACEHOLDERS,
)


def _check_docx_bytes(env, file_bytes):
    """Raise a user-facing error when *file_bytes* is not a readable .docx.

    ``zipfile.BadZipFile`` used to escape raw from the parse/render paths and
    reached the user as a generic "Odoo Server Error" page.
    """
    try:
        with zipfile.ZipFile(BytesIO(file_bytes)) as zf:
            names = zf.namelist()
    except zipfile.BadZipFile:
        names = []
    if 'word/document.xml' not in names:
        raise UserError(env._(
            'The uploaded file is not a valid .docx document. Please open it in '
            'Word or LibreOffice and save it again as .docx.'
        ))


# ---------------------------------------------------------------------------
#  Main template model
#
#  This class pulls in three mixins:
#   * soft.report.template.parser.mixin — DOCX/tax_totals parsing
#   * soft.report.template.docx.mixin   — DOCX rendering engine
#   * soft.report.template.pdf.mixin    — PDF merge, preview, LibreOffice conv.
#
#  Field-level business logic and ORM overrides live here.
# ---------------------------------------------------------------------------

class SoftReportTemplate(models.Model):
    _name = 'soft.report.template'
    _description = 'Report Template'
    _inherit = [
        'mail.thread',
        'mail.activity.mixin',
        'soft.report.template.parser.mixin',
        'soft.report.template.docx.mixin',
        'soft.report.template.pdf.mixin',
        'soft.report.template.hints.mixin',
    ]
    _order = 'name'

    name = fields.Char('Template Name', required=True, tracking=True)
    model_id = fields.Many2one(
        'ir.model', string='Odoo Model', required=True,
        ondelete='cascade', tracking=True,
        domain=[('transient', '=', False)],
        help='Select the Odoo model this template applies to.',
    )
    model_name = fields.Char(related='model_id.model', store=True, readonly=True)

    # ------------------------------------------------------------------
    #  Value hints (see models/value_hints.py)
    #  What can be printed for the selected model: declared by the model,
    #  read from the QWeb reports already printing it, or derived from the
    #  field types. Shown in the form and used to validate field paths.
    # ------------------------------------------------------------------
    value_hints = fields.Text(
        'Available Values',
        compute='_compute_value_hints',
        help='Placeholders usable in the .docx for the selected model.',
    )
    hint_examples = fields.Html(
        'Value Examples',
        compute='_compute_value_hints',
    )

    template_file = fields.Binary(
        'Template File', required=True, attachment=True,
    )
    template_filename = fields.Char('File Name')
    template_type = fields.Selection(
        [('docx', 'Word (.docx)')],
        string='Type', compute='_compute_template_type', store=True,
    )
    output_format = fields.Selection(
        [
            ('original', 'Same as Template'),
            ('pdf', 'PDF'),
            ('html', 'HTML'),
            ('odt', 'ODT'),
            ('rtf', 'RTF'),
        ],
        string='Output Format', default='pdf', required=True,
    )
    merge_pdf = fields.Boolean(
        'Merge into Single PDF',
        default=True,
        help='When printing multiple records as PDF, merge all pages '
             'into a single PDF file instead of a ZIP archive.',
    )

    # Cover page
    cover_file = fields.Binary(
        'Cover Page Template', attachment=True,
        help='Optional DOCX cover page. Rendered with the same context '
             'and prepended to the output PDF.',
    )
    cover_filename = fields.Char('Cover File Name')

    # Domain-based template selection
    use_domain = fields.Boolean(
        'Domain Filter',
        help='When enabled, this template is only available for records '
             'that match the specified domain.',
    )
    template_domain = fields.Char(
        'Domain',
        default='[]',
        help='Odoo domain expression to filter which records can use this template.\n'
             'Example: [("state", "=", "sale")] to only match confirmed sales.',
    )
    priority = fields.Integer(
        'Priority', default=10,
        help='When multiple templates match a record, the one with the '
             'lowest priority number is used first.',
    )

    field_ids = fields.One2many(
        'soft.report.template.field', 'template_id', string='Field Mappings',
    )
    state = fields.Selection(
        [('draft', 'Draft'), ('ready', 'Ready'), ('active', 'Active')],
        default='draft', tracking=True, copy=False,
    )
    active = fields.Boolean(default=True)
    company_id = fields.Many2one(
        'res.company', string='Company',
        default=lambda self: self.env.company,
    )
    server_action_id = fields.Many2one(
        'ir.actions.server', string='Print Action',
        readonly=True, copy=False,
    )

    # ------------------------------------------------------------------
    #  Computed
    # ------------------------------------------------------------------

    @api.depends('model_id')
    def _compute_value_hints(self):
        for template in self:
            model_name = template.model_name
            if model_name:
                template.value_hints = template._soft_report_hints_text(
                    model_name)
                template.hint_examples = template._soft_report_hints_html(
                    model_name)
            else:
                template.value_hints = False
                template.hint_examples = False

    @api.depends('template_filename')
    def _compute_template_type(self):
        valid = set(dict(self._fields['template_type'].selection))
        for rec in self:
            if rec.template_filename:
                ext = rec.template_filename.rsplit('.', 1)[-1].lower()
                rec.template_type = ext if ext in valid else False
            else:
                rec.template_type = False

    # ------------------------------------------------------------------
    #  Actions (buttons)
    # ------------------------------------------------------------------

    def action_parse_template(self):
        """Parse the uploaded template and extract placeholders."""
        self.ensure_one()
        if not self.template_file:
            raise UserError(_('Please upload a template file first.'))
        if not self.model_id:
            raise UserError(_('Please select an Odoo model first.'))

        file_bytes = base64.b64decode(self.template_file)

        if self.template_type == 'docx':
            _check_docx_bytes(self.env, file_bytes)
            simple, loops, loop_children = self._parse_docx_placeholders(file_bytes)
        else:
            raise UserError(_(
                'Unsupported file type. Please upload a .docx file.'
            ))

        # Remove old mappings
        self.field_ids.unlink()

        seq = 0

        # Create loop mappings
        for loop_name in sorted(loops):
            seq += 10
            field_path, resolved = self._auto_resolve_placeholder(loop_name)
            self.env['soft.report.template.field'].create({
                'template_id': self.id,
                'placeholder': loop_name,
                'field_path': field_path,
                'is_loop': True,
                'auto_resolved': resolved,
                'sequence': seq,
                'description': _('Loop over %s') % loop_name,
            })

        # Create regular placeholder mappings
        for ph in sorted(simple):
            seq += 10
            field_path, resolved = self._auto_resolve_placeholder(ph)

            # Check if this placeholder also appears inside a loop
            lp = ''
            for loop_name, children in loop_children.items():
                if ph in children:
                    lp = loop_name
                    break

            if lp:
                # Placeholder exists in BOTH top-level and loop context.
                # Create a top-level mapping first.
                self.env['soft.report.template.field'].create({
                    'template_id': self.id,
                    'placeholder': ph,
                    'field_path': field_path,
                    'loop_parent': False,
                    'auto_resolved': resolved,
                    'sequence': seq,
                })
                # Then create a loop-child mapping
                seq += 10
                child_path, child_resolved = (
                    self._auto_resolve_loop_child(lp, ph)
                    if not resolved else (field_path, resolved)
                )
                self.env['soft.report.template.field'].create({
                    'template_id': self.id,
                    'placeholder': ph,
                    'field_path': child_path,
                    'loop_parent': lp,
                    'auto_resolved': child_resolved,
                    'sequence': seq,
                })
            else:
                self.env['soft.report.template.field'].create({
                    'template_id': self.id,
                    'placeholder': ph,
                    'field_path': field_path,
                    'loop_parent': False,
                    'auto_resolved': resolved,
                    'sequence': seq,
                })

        # Create mappings for placeholders that ONLY appear inside loops
        for loop_name, children in loop_children.items():
            for ph in sorted(children - simple):
                seq += 10
                child_path, child_resolved = self._auto_resolve_loop_child(
                    loop_name, ph,
                )
                self.env['soft.report.template.field'].create({
                    'template_id': self.id,
                    'placeholder': ph,
                    'field_path': child_path,
                    'loop_parent': loop_name,
                    'auto_resolved': child_resolved,
                    'sequence': seq,
                })

        self.state = 'ready'
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Template Parsed'),
                'message': _(
                    'Found %(ph)s placeholders and %(lp)s loops.',
                    ph=len(simple), lp=len(loops),
                ),
                'type': 'success',
                'sticky': False,
            },
        }

    def action_activate(self):
        """Create a server action so users can print from the model."""
        self.ensure_one()
        unmapped = self.field_ids.filtered(
            lambda f: not f.field_path and not f.is_loop
        )
        if unmapped:
            raise UserError(_(
                'These placeholders are not mapped yet: %(names)s',
                names=', '.join(unmapped.mapped('placeholder')),
            ))
        unmapped_loops = self.field_ids.filtered(
            lambda f: f.is_loop and not f.field_path
        )
        if unmapped_loops:
            raise UserError(_(
                'These loop markers need a field path (One2many): %(names)s',
                names=', '.join(unmapped_loops.mapped('placeholder')),
            ))
        # BUG-10: validate that loop markers point to One2many/Many2many
        self._validate_loop_fields()
        # A typo in a field path used to surface only at print time
        self._validate_field_paths()

        if not self.server_action_id:
            action = self.env['ir.actions.server'].sudo().create({
                'name': _('Print: %s') % self.name,
                'model_id': self.model_id.id,
                'binding_model_id': self.model_id.id,
                # 'report' puts the entry in the Print menu; 'action' only in
                # the Action (gear) menu, where nobody looks for it.
                'binding_type': 'report',
                # Without the group the entry shows up in the Print menu of
                # every internal user, who then gets an AccessError on click.
                'group_ids': [(6, 0, [
                    self.env.ref(
                        'soft_report_generator.group_soft_report_generator_user'
                    ).id,
                ])],
                'state': 'code',
                'code': (
                    'action = env["soft.report.template"]'
                    '.browse(%d)'
                    '.generate_report(records)' % self.id
                ),
            })
            self.server_action_id = action
        else:
            # Actions generated by an older version lived in the gear menu
            self.server_action_id.sudo().write({
                'binding_model_id': self.model_id.id,
                'binding_type': 'report',
                'group_ids': [(4, self.env.ref(
                    'soft_report_generator.group_soft_report_generator_user'
                ).id)],
            })

        self.state = 'active'

    def _validate_field_paths(self):
        """Reject mappings whose field path does not exist on their model.

        Three cases must not be treated as plain model fields:

        * loop children (``loop_parent`` set) resolve against the *loop item's*
          model, and may also read the parent record (cross-context fallback);
        * ``tax_totals_*`` placeholders are filled from ``tax_totals`` at render
          time, they are not fields of any model.
        """
        if not self.model_name:
            return
        Model = self.env[self.model_name]

        comodel_of = {}
        for mapping in self.field_ids.filtered('is_loop'):
            head = (mapping.field_path or '').split('.')[0]
            field = Model._fields.get(head)
            comodel_of[mapping.placeholder] = getattr(
                field, 'comodel_name', None)

        unknown, names = [], {}
        for mapping in self.field_ids:
            path = (mapping.field_path or '').strip()
            if mapping.is_loop or not path:
                continue
            if mapping.placeholder in SYSTEM_PLACEHOLDERS:
                continue
            if mapping.loop_parent in SYSTEM_LOOPS:
                continue  # tax_groups / tax_subtotals children are synthetic
            loop_model = comodel_of.get(mapping.loop_parent)
            if not self._soft_report_unknown_paths(
                    loop_model or self.model_name, [path]):
                continue
            # A loop child may point at the parent record's field
            if loop_model and not self._soft_report_unknown_paths(
                    self.model_name, [path]):
                continue
            unknown.append(path)
            names[path] = mapping.placeholder

        if not unknown:
            return
        raise UserError(_(
            'These field paths do not exist on %(model)s: %(paths)s',
            model=self.model_name,
            paths=', '.join(
                '%s (%s)' % (path, names.get(path, '')) for path in unknown
            ),
        ))

    def _validate_loop_fields(self):
        """Ensure every loop field_path targets a One2many or Many2many.

        Raises UserError with a list of offending mappings.
        """
        invalid = []
        Model = self.env[self.model_name]
        for fm in self.field_ids.filtered('is_loop'):
            # tax_groups / tax_subtotals are filled from tax_totals at render
            # time: they are not model fields and carry no field path.
            if fm.placeholder in SYSTEM_LOOPS:
                continue
            path = fm.field_path or ''
            head = path.split('.')[0]
            if not head or head not in Model._fields:
                invalid.append(
                    (fm.placeholder, path, 'field not found')
                )
                continue
            ftype = Model._fields[head].type
            if ftype not in ('one2many', 'many2many'):
                invalid.append(
                    (fm.placeholder, path,
                     'expected One2many/Many2many, got %s' % ftype)
                )
        if invalid:
            lines = [
                '  - %(ph)s (path=%(p)s, %(why)s)' % {
                    'ph': ph, 'p': p, 'why': why,
                }
                for ph, p, why in invalid
            ]
            raise UserError(_(
                'Loop placeholders must point to One2many/Many2many fields:\n%s',
                '\n'.join(lines),
            ))

    def _generated_action_code(self):
        """The exact server-action code this template generates (see action_parse_template)."""
        self.ensure_one()
        return (
            'action = env["soft.report.template"].browse(%d).generate_report(records)' % self.id
        )

    def _remove_generated_action(self):
        """Unlink the print action, and only the one this template generated.

        server_action_id is a plain writable Many2one: a user who can write the
        template can point it at somebody else's ir.actions.server (writing an id
        needs no read access on the target). The record is therefore checked
        before it is deleted, and the unlink is scoped to that single record.
        """
        self.ensure_one()
        action = self.server_action_id
        if not action:
            return
        if action.state == 'code' and (action.code or '').strip() == self._generated_action_code():
            action.sudo().unlink()
        self.server_action_id = False

    def action_deactivate(self):
        """Remove the print action."""
        self.ensure_one()
        self._remove_generated_action()
        self.state = 'ready'

    def action_reset_draft(self):
        """Reset to draft, removing action and mappings."""
        self.ensure_one()
        self._remove_generated_action()
        self.field_ids.unlink()
        self.state = 'draft'

    def action_test_report(self):
        """Generate a test report with the first record of the model."""
        self.ensure_one()
        if not self.model_name:
            raise UserError(_('Please select a model first.'))
        Model = self.env[self.model_name]
        record = Model.search([], limit=1)
        if not record:
            raise UserError(_(
                'No records found in %(model)s to test with.',
                model=self.model_name,
            ))
        return self.generate_report(record)

    # ------------------------------------------------------------------
    #  Report generation (called from server action)
    # ------------------------------------------------------------------

    def generate_report(self, records):
        """Generate the report for *records* and return a download action."""
        self.ensure_one()
        if not records:
            raise UserError(_('No records selected.'))

        # Accept both recordsets and plain ID lists (e.g. from XML-RPC / server action)
        if isinstance(records, (list, tuple)):
            records = self.env[self.model_name].browse(records)
        elif isinstance(records, int):
            records = self.env[self.model_name].browse([records])

        if records._name != self.model_name:
            # The wizard takes res_model/res_ids from the context, so a record
            # of another model could reach here and get its PDF attached to an
            # unrelated record id (attachments are stored with self.model_name).
            raise UserError(_(
                'This template is designed for %(model)s records, not for '
                '%(other)s records.',
                model=self.model_name,
                other=records._name,
            ))

        if not self.template_file:
            # Same guard as action_parse_template: without it base64.b64decode
            # raised a raw TypeError and the user got a 500 page.
            raise UserError(_('Please upload a template file first.'))
        file_bytes = base64.b64decode(self.template_file)
        _check_docx_bytes(self.env, file_bytes)
        outputs = []

        for record in records:
            ctx = self._build_render_context(record)

            if self.template_type == 'docx':
                output = self._render_docx(file_bytes, ctx)
            else:
                raise UserError(_('Unsupported template type.'))

            if self.output_format not in ('original', False):
                output = self._convert_format(
                    output, self.template_type, self.output_format,
                )

            # Merge product PDF documents (sale_pdf_quote_builder). Odoo 19 has
            # no ``_get_product_documents_pdf()`` (it returned merged bytes);
            # the record exposes ``_get_product_documents()`` returning
            # ``product.document`` records, so merging is done here.
            if self.output_format == 'pdf':
                output = self._merge_product_documents(record, output)

            outputs.append((record, output))

        if self.output_format in ('original', False):
            ext = self.template_type
        else:
            ext = self.output_format

        # --- Cover page (PDF only) ---
        cover_pdf = None
        if self.cover_file and ext == 'pdf':
            cover_bytes = base64.b64decode(self.cover_file)
            cover_ctx = self._build_render_context(records[0])
            cover_output = self._render_docx(cover_bytes, cover_ctx)
            cover_pdf = self._convert_format(cover_output, 'docx', 'pdf')

        if len(outputs) == 1:
            record, data = outputs[0]
            if cover_pdf:
                data = self._merge_pdfs([cover_pdf, data])
            filename = '%s - %s.%s' % (
                self.name, record.display_name or record.id, ext,
            )
            attachment = self.env['ir.attachment'].create({
                'name': filename,
                'datas': base64.b64encode(data),
                'res_model': self.model_name,
                'res_id': record.id,
                'type': 'binary',
            })
            return {
                'type': 'ir.actions.act_url',
                'url': '/web/content/%d?download=true' % attachment.id,
                'target': 'new',
            }

        # Multiple records — merge PDF or fall back to ZIP
        if ext == 'pdf' and self.merge_pdf:
            pdfs = [data for _rec, data in outputs]
            if cover_pdf:
                pdfs.insert(0, cover_pdf)
            merged = self._merge_pdfs(pdfs)
            attachment = self.env['ir.attachment'].create({
                'name': '%s.pdf' % self.name,
                'datas': base64.b64encode(merged),
                'type': 'binary',
            })
            return {
                'type': 'ir.actions.act_url',
                'url': '/web/content/%d?download=true' % attachment.id,
                'target': 'new',
            }

        # Fall back: ZIP
        zip_buf = BytesIO()
        with zipfile.ZipFile(zip_buf, 'w', zipfile.ZIP_DEFLATED) as zf:
            for record, data in outputs:
                fname = '%s - %s.%s' % (
                    self.name, record.display_name or record.id, ext,
                )
                zf.writestr(fname, data)
        attachment = self.env['ir.attachment'].create({
            'name': '%s.zip' % self.name,
            'datas': base64.b64encode(zip_buf.getvalue()),
            'type': 'binary',
        })
        return {
            'type': 'ir.actions.act_url',
            'url': '/web/content/%d?download=true' % attachment.id,
            'target': 'self',
        }

    # ==================================================================
    #  DOMAIN-BASED TEMPLATE SELECTION
    # ==================================================================

    @api.model
    def get_templates_for_record(self, records):
        """Return templates matching *records* based on model + domain rules.

        Templates without domain are always returned. Templates with a domain
        are returned only when the domain matches **all** the given records, so
        a batch print never applies a template to records it was not designed
        for. Results are sorted by priority (lowest first).
        """
        model_name = records._name
        templates = self.search([
            ('model_name', '=', model_name),
            ('state', '=', 'active'),
        ], order='priority, name')

        matched = self.browse()
        for tmpl in templates:
            if not tmpl.use_domain or not tmpl.template_domain \
                    or tmpl.template_domain in ('[]', ''):
                matched |= tmpl
            else:
                try:
                    domain = safe_eval(tmpl.template_domain)
                    if len(records.filtered_domain(domain)) == len(records):
                        matched |= tmpl
                except Exception:
                    _logger.warning(
                        'Invalid domain on template %s: %s',
                        tmpl.name, tmpl.template_domain,
                    )
        return matched

    @api.model
    def action_print_with_selection(self, res_model, res_ids):
        """Show a template picker when multiple templates match, or print
        directly when only one matches. Called from JS or server action."""
        records = self.env[res_model].browse(res_ids)
        if not records:
            raise UserError(_('No records selected.'))

        templates = self.get_templates_for_record(records)
        if not templates:
            raise UserError(_(
                'No active report templates found for %(model)s.',
                model=res_model,
            ))

        if len(templates) == 1:
            return templates.generate_report(records)

        # Multiple templates — show selection wizard
        return {
            'type': 'ir.actions.act_window',
            'name': _('Select Report Template'),
            'res_model': 'soft.report.template.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_res_model': res_model,
                'default_res_ids': res_ids,
                'default_available_template_ids': templates.ids,
            },
        }

    # ------------------------------------------------------------------
    #  ORM overrides
    # ------------------------------------------------------------------

    def _check_extension_or_raise(self, filename):
        """Validate *filename* has a supported extension."""
        valid = set(dict(self._fields['template_type'].selection))
        if not filename:
            return
        ext = filename.rsplit('.', 1)[-1].lower()
        if ext not in valid:
            raise ValidationError(_(
                'Template file must have a .%(allowed)s extension. '
                'Got: .%(ext)s (%(name)s)',
                allowed='/'.join(sorted(valid)),
                ext=ext or '<none>',
                name=filename,
            ))

    @api.model_create_multi
    def create(self, vals_list):
        """Create one or more report templates.

        Validates the uploaded file extension on every record before
        delegating to the parent implementation.
        """
        for vals in vals_list:
            self._check_extension_or_raise(vals.get('template_filename'))
        return super().create(vals_list)

    def write(self, vals):
        """Update templates, with side-effects on file replacement.

        When ``template_file`` is part of ``vals``:
        * Validate the (possibly new) filename extension.
        * Deactivate any active template.
        * Drop existing field mappings if the file content actually changed.
        * Reset state to ``draft`` to force re-parse.
        """
        if 'template_file' not in vals:
            return super().write(vals)

        # Copy the caller's dict: writing ``state`` into it leaked the change
        # into the caller (and into every record of the batch).
        vals = dict(vals)
        new_filename = vals.get('template_filename')
        if new_filename is None:
            # Only a single record has an unambiguous current filename; on a
            # batch read of ``self.template_filename`` raised "Expected
            # singleton".
            new_filename = self.template_filename if len(self) == 1 else None
        if new_filename:
            self._check_extension_or_raise(new_filename)

        changed = self.browse()
        for rec in self:
            if rec.state == 'active':
                rec.action_deactivate()
            if vals['template_file'] != rec.template_file:
                rec.field_ids.unlink()
                changed |= rec

        result = super().write(vals)
        if changed:
            changed.write({'state': 'draft'})
        return result

    @api.ondelete(at_uninstall=False)
    def _unlink_check(self):
        for rec in self:
            rec._remove_generated_action()
