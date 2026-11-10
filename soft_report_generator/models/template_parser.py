# Part of Odoo. See LICENSE file for full copyright and licensing details.

"""Template parser mixin.

Provides methods for:
* Parsing the DOCX template and extracting placeholders / loops.
* Decoding Odoo 17+ ``tax_totals`` Binary/JSON field.
* Auto-resolving placeholder strings to real field paths.
"""

import base64
import json
import logging
import re
import zipfile
from io import BytesIO

from lxml import etree

from odoo import models
from odoo.tools.misc import formatLang

_logger = logging.getLogger(__name__)

# Module-level XML namespace constants shared across the rendering engine
# and parser.  ``report_template`` re-exports them so tests can keep
# importing them from the historical location.
W_NS = 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'
XML_NS = 'http://www.w3.org/XML/1998/namespace'
WP_NS = 'http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing'
A_NS = 'http://schemas.openxmlformats.org/drawingml/2006/main'
PIC_NS = 'http://schemas.openxmlformats.org/drawingml/2006/picture'
R_NS = 'http://schemas.openxmlformats.org/officeDocument/2006/relationships'
REL_NS = 'http://schemas.openxmlformats.org/package/2006/relationships'
CT_NS = 'http://schemas.openxmlformats.org/package/2006/content-types'

#: Placeholders filled from ``tax_totals`` at render time — they are not model
#: fields, so they must not be validated against the model.
SYSTEM_PLACEHOLDERS = (
    'tax_totals_total', 'tax_totals_cash_rounding',
    'tax_totals_same_tax_base', 'tax_totals_has_cash_rounding',
)

#: Loops filled from ``tax_totals`` at render time — they carry no field path.
SYSTEM_LOOPS = ('tax_groups', 'tax_subtotals')


class TemplateParserMixin(models.AbstractModel):
    """Mixin that adds DOCX/tax_totals parsing helpers to a template model."""

    _name = 'soft.report.template.parser.mixin'
    _description = 'Soft Report Template — Parser Mixin'

    # ------------------------------------------------------------------
    #  tax_totals decoder (Odoo 17+)
    # ------------------------------------------------------------------

    def _parse_tax_totals(self, record):
        """Parse Odoo tax_totals (Binary/JSON) into a flat dict + loop data.

        In Odoo 17+, tax_totals is stored as fields.Binary (base64-encoded JSON).
        This method decodes it and returns structured data suitable for
        placeholder replacement and {{#tax_groups}} loop expansion.

        Returns a dict with:
        - 'context': flat {placeholder: value} for simple placeholders
        - 'loops': {'tax_groups': [{group_name, tax_amount, base_amount, ...}]}
        - 'subtotal_loops': {'tax_subtotals': [{name, base_amount, ...}]}
        Returns None if tax_totals is not available or cannot be parsed.
        """
        if 'tax_totals' not in record._fields:
            return None

        val = record['tax_totals']
        if not val:
            return None

        # --- Currency for formatting ---
        currency = record.currency_id if hasattr(record, 'currency_id') else None

        def _fmt(amount):
            """Format a monetary amount using the record's currency."""
            if amount is None or amount is False or amount == '':
                return ''
            try:
                return formatLang(self.env, float(amount), currency_obj=currency)
            except (ValueError, TypeError):
                return str(amount)

        try:
            # Decode binary/base64 → JSON string → Python dict.
            # In Odoo 17+, computed Binary fields (without store=True)
            # return the raw dict from cache — no decoding needed.
            if isinstance(val, dict):
                data = val
            elif isinstance(val, str):
                # Could be base64 or raw JSON
                if val.startswith('{'):
                    data = json.loads(val)
                else:
                    decoded = base64.b64decode(val)
                    data = json.loads(decoded.decode('utf-8'))
            elif isinstance(val, bytes):
                data = json.loads(val.decode('utf-8'))
            else:
                return None

            if not isinstance(data, dict):
                return None

            # --- Flat context values ---
            context = {}
            context['tax_totals_total'] = _fmt(data.get('total_amount_currency', ''))
            context['tax_totals_has_cash_rounding'] = (
                'cash_rounding_base_amount_currency' in data
            )
            context['tax_totals_cash_rounding'] = _fmt(data.get(
                'cash_rounding_base_amount_currency', '',
            ))
            context['tax_totals_same_tax_base'] = data.get(
                'same_tax_base', False,
            )

            # --- Tax groups loop ({{#tax_groups}}) ---
            tax_groups = []
            subtotals_list = []
            for subtotal in data.get('subtotals', []):
                subtotal_name = subtotal.get('name', '')
                subtotal_base = subtotal.get('base_amount_currency', '')
                subtotals_list.append({
                    'name': subtotal_name,
                    'base_amount': _fmt(subtotal_base if subtotal_base else ''),
                })
                for tg in subtotal.get('tax_groups', []):
                    display_base = tg.get(
                        'display_base_amount_currency',
                        tg.get('base_amount_currency', ''),
                    )
                    if display_base is False:
                        display_base = ''
                    tax_groups.append({
                        'subtotal_name': subtotal_name,
                        'subtotal_base': _fmt(subtotal_base if subtotal_base else ''),
                        'group_name': tg.get('group_name', ''),
                        'tax_amount': _fmt(tg.get('tax_amount_currency', '')),
                        'base_amount': _fmt(str(display_base) if display_base else ''),
                    })

            return {
                'context': context,
                'loops': {'tax_groups': tax_groups},
                'subtotal_loops': {'tax_subtotals': subtotals_list},
            }
        except Exception:
            _logger.warning('Failed to parse tax_totals', exc_info=True)
            return None

    # ------------------------------------------------------------------
    #  Placeholder extraction
    # ------------------------------------------------------------------

    def _parse_docx_placeholders(self, file_bytes):
        """Return (simple_set, loops_set, {loop: children_set}) from DOCX."""
        simple = set()
        loops = set()
        loop_children = {}
        current_loop = None

        with zipfile.ZipFile(BytesIO(file_bytes), 'r') as zf:
            for name in zf.namelist():
                if not (name.startswith('word/') and name.endswith('.xml')):
                    continue
                try:
                    tree = etree.fromstring(zf.read(name))
                except etree.XMLSyntaxError:
                    continue

                # Merge placeholder fragments split across paragraphs
                self._normalize_cross_paragraph_placeholders(tree)

                for para in tree.iter('{%s}p' % W_NS):
                    text = self._get_paragraph_text(para)
                    for match in re.finditer(r'\{\{(.+?)\}\}', text):
                        ph = match.group(1).strip()
                        if ph.startswith('=') or ph.startswith('img:'):
                            continue  # expressions & images resolved at render
                        if ph.startswith('#'):
                            tag = ph[1:]
                            if tag.startswith('if ') or tag == 'else':
                                continue  # conditionals
                            loop_name = tag
                            loops.add(loop_name)
                            loop_children.setdefault(loop_name, set())
                            current_loop = loop_name
                        elif ph.startswith('/'):
                            tag = ph[1:]
                            if tag == 'if':
                                continue
                            current_loop = None
                        else:
                            field_name = ph.split('|')[0].strip()
                            if current_loop:
                                loop_children[current_loop].add(field_name)
                            else:
                                simple.add(field_name)

        return simple, loops, loop_children

    # ------------------------------------------------------------------
    #  Auto-resolution helpers
    # ------------------------------------------------------------------

    def _auto_resolve_placeholder(self, placeholder):
        """Try to map *placeholder* to a real field path. Return (path, bool)."""
        if not self.model_name:
            return '', False

        # System-reserved loops (auto-resolved without model field mapping)
        _SYSTEM_LOOPS = ('tax_groups', 'tax_subtotals')
        if placeholder in _SYSTEM_LOOPS:
            return placeholder, True

        # System-reserved flat placeholders (from tax_totals parsing)
        _SYSTEM_FLAT = (
            'tax_totals_total', 'tax_totals_cash_rounding',
            'tax_totals_same_tax_base', 'tax_totals_has_cash_rounding',
        )
        if placeholder in _SYSTEM_FLAT:
            return placeholder, True

        Model = self.env[self.model_name]

        # Direct match
        if placeholder in Model._fields:
            return placeholder, True

        # Dot-notation check
        if '.' in placeholder:
            parts = placeholder.split('.')
            obj_model = Model
            valid = True
            for i, part in enumerate(parts):
                if part not in obj_model._fields:
                    valid = False
                    break
                field_def = obj_model._fields[part]
                if i < len(parts) - 1:
                    comodel = getattr(field_def, 'comodel_name', None)
                    if comodel:
                        obj_model = self.env[comodel]
                    else:
                        valid = False
                        break
            if valid:
                return placeholder, True

        return '', False

    def _auto_resolve_loop_child(self, loop_placeholder, child_placeholder):
        """Resolve *child_placeholder* against the comodel of the loop field."""
        if not self.model_name:
            return '', False

        # System-reserved loop children (from tax_totals parsing)
        # For system loops, auto-resolve ALL children — they're all synthetic
        _SYSTEM_LOOPS = ('tax_groups', 'tax_subtotals')
        if loop_placeholder in _SYSTEM_LOOPS:
            return child_placeholder, True

        # Find the loop's field path
        loop_map = self.field_ids.filtered(
            lambda f: f.placeholder == loop_placeholder and f.is_loop
        )
        loop_path = loop_map.field_path if loop_map else loop_placeholder

        # Walk the loop path to find the comodel
        Model = self.env[self.model_name]
        for part in (loop_path or loop_placeholder).split('.'):
            if part not in Model._fields:
                return '', False
            field_def = Model._fields[part]
            comodel = getattr(field_def, 'comodel_name', None)
            if comodel:
                Model = self.env[comodel]
            else:
                return '', False

        # Now resolve child in the comodel
        if child_placeholder in Model._fields:
            return child_placeholder, True

        # --- Known field-name aliases (different Odoo instances / custom modules) ---
        _FIELD_ALIASES = {
            'product_uom': 'product_uom_id',
            'product_uom_id': 'product_uom',
        }
        alias = _FIELD_ALIASES.get(child_placeholder)
        if alias and alias in Model._fields:
            return alias, True

        if '.' in child_placeholder:
            parts = child_placeholder.split('.')
            obj = Model
            valid = True
            for i, p in enumerate(parts):
                if p not in obj._fields:
                    valid = False
                    break
                fd = obj._fields[p]
                if i < len(parts) - 1:
                    cm = getattr(fd, 'comodel_name', None)
                    if cm:
                        obj = self.env[cm]
                    else:
                        valid = False
                        break
            if valid:
                return child_placeholder, True

        # Cross-context fallback: resolve against parent model
        # (e.g. master_product_id.proforma_name from sale.order
        #  used inside {{#order_line}} loop on sale.order.line)
        parent_model = self.env[self.model_name]
        if child_placeholder in parent_model._fields:
            return child_placeholder, True
        if '.' in child_placeholder:
            parts = child_placeholder.split('.')
            obj = parent_model
            valid = True
            for i, p in enumerate(parts):
                if p not in obj._fields:
                    valid = False
                    break
                fd = obj._fields[p]
                if i < len(parts) - 1:
                    cm = getattr(fd, 'comodel_name', None)
                    if cm:
                        obj = self.env[cm]
                    else:
                        valid = False
                        break
            if valid:
                return child_placeholder, True

        return '', False
