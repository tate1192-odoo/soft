# Part of Odoo. See LICENSE file for full copyright and licensing details.

"""DOCX rendering engine mixin.

Provides everything needed to turn a populated template context into
a filled DOCX byte-string:

* Context helpers — ``_build_render_context``, ``_resolve_field_path``,
  ``_format_value``, ``_resolve_placeholder``, ``_strip_html_tags``,
  ``_eval_expression``, ``_eval_condition``, ``_apply_format_pipe``.
* HTML→DOCX rendering — ``_html_to_docx_runs``, ``_emit_text_run``,
  ``_emit_break``, ``_html_node_to_docx``, ``_html_img_to_docx``,
  ``_detect_html_field``.
* Image handling — ``_fetch_web_image``, ``_detect_image_format``,
  ``_get_image_size_emu``, ``_create_image_run``,
  ``_update_docx_rels``, ``_update_content_types``.
* DOCX pipeline — ``_render_docx``, ``_process_docx_xml``,
  ``_normalize_cross_paragraph_placeholders``,
  ``_process_docx_table_loops``, ``_process_docx_simple_replacements``,
  ``_docx_replace_paragraph``, ``_html_docx_replace``,
  ``_process_docx_conditionals``, ``_process_docx_images``,
  ``_docx_table_loops``, ``_docx_expand_table``.
* Text extraction — ``_get_paragraph_text``, ``_get_row_text``.
"""

import base64
import binascii
import logging
import re
import struct
import zipfile
from copy import deepcopy
from io import BytesIO

from lxml import etree
from lxml import html as lh

from odoo import models, _
from odoo.exceptions import UserError
from odoo.tools.misc import format_date, format_datetime, formatLang
from odoo.tools.safe_eval import datetime as safe_datetime
from odoo.tools.safe_eval import safe_eval
from odoo.tools.safe_eval import time as safe_time

try:
    from PIL import Image as PILImage
except ImportError:
    PILImage = None

_logger = logging.getLogger(__name__)

# Re-use the XML namespace constants from the parser mixin so we don't
# duplicate them in every mixin.
from .template_parser import (  # noqa: E402,F401
    W_NS, XML_NS, WP_NS, A_NS, PIC_NS, R_NS, REL_NS, CT_NS,
)

# Magic bytes that identify common image formats supported by DOCX.
# JPEG is matched on the first 2 bytes (\xff\xd8) since the third byte
# varies between JFIF and EXIF containers.
_IMAGE_MAGIC_HEADERS = (
    b'\x89PNG',  # PNG
    b'GIF8',     # GIF87a/GIF89a
    b'RIFF',     # WEBP (RIFF...WEBP)
    b'BM',       # BMP
    b'\xff\xd8',  # JPEG
)
IMG_REL_TYPE = (
    'http://schemas.openxmlformats.org/officeDocument/'
    '2006/relationships/image'
)


class _TemplateValueProxy:
    """Field-value view of a record for template expressions.

    A DOCX template is data, not code: an expression may read the values the
    template already maps, but it must never reach the environment, the cursor
    or any other ORM entry point (``record.env.cr.execute(...)`` would turn an
    uploaded template into arbitrary SQL). Only real field names pass; every
    other attribute raises. The stored record is kept in a dunder slot, which
    safe_eval refuses to read.
    """

    __slots__ = ("__record",)

    def __init__(self, record):
        object.__setattr__(self, "_TemplateValueProxy__record", record)

    def __getattr__(self, name):
        record = object.__getattribute__(self, "_TemplateValueProxy__record")
        if name in record._fields:
            return _TemplateValueProxy._wrap(record[name])
        raise AttributeError(
            "template expressions may only read fields, not %r" % name
        )

    def __getitem__(self, name):
        return getattr(self, name)

    def __str__(self):
        record = object.__getattribute__(self, "_TemplateValueProxy__record")
        return record.display_name or ""

    @staticmethod
    def _wrap(value):
        if isinstance(value, models.BaseModel):
            return _TemplateValueProxy(value)
        return value


class DocxEngineMixin(models.AbstractModel):
    """Mixin that adds DOCX rendering helpers to a template model."""

    _name = 'soft.report.template.docx.mixin'
    _description = 'Soft Report Template — DOCX Engine Mixin'

    def _build_render_context(self, record):
        """Build a flat {placeholder: value} dict plus loop data."""
        context = {}
        raw = {}
        loops = {}
        html_fields = {}
        loop_html_fields = {}

        _SYSTEM_LOOPS = ('tax_groups', 'tax_subtotals')
        _SYSTEM_FLAT = (
            'tax_totals_total', 'tax_totals_cash_rounding',
            'tax_totals_same_tax_base', 'tax_totals_has_cash_rounding',
        )
        for fm in self.field_ids:
            # System-reserved placeholders are not real model fields —
            # skip field-based resolution; they are populated later
            # from _parse_tax_totals.
            if fm.placeholder in _SYSTEM_FLAT:
                continue
            if fm.is_loop:
                # System-reserved loops are handled separately via
                # _parse_tax_totals — skip field-based resolution.
                if fm.placeholder in _SYSTEM_LOOPS:
                    continue
                items = self._resolve_field_path(record, fm.field_path)
                children = self.field_ids.filtered(
                    lambda f, lp=fm.placeholder: (
                        f.loop_parent == lp and not f.is_loop
                    )
                )
                loop_items = []
                loop_hf = {}
                if hasattr(items, '__iter__') and not isinstance(items, str):
                    for item in items:
                        # Section / note lines (e.g. sale.order.line with a
                        # display_type) carry no data of their own: printing
                        # them only adds empty rows to the loop table.
                        if (
                            isinstance(item, models.BaseModel)
                            and 'display_type' in item._fields
                            and item.display_type
                        ):
                            continue
                        item_ctx = {}
                        item_raw = {}
                        item_hf = {}
                        child_model = getattr(item, '_name', None)
                        for child in children:
                            child_path = (child.field_path or '').strip()
                            # A loop child points at the item model, but it may
                            # also read the parent record (e.g. a field of
                            # sale.order inside the {{#order_line}} loop).
                            # Choose by the models that carry the path, not by
                            # the resolved value: the old fallback only retried
                            # the parent for an empty value containing a dot,
                            # so parent-only paths such as ``ref`` were never
                            # found.
                            from_parent = bool(
                                child_path
                                and child_model
                                and self._soft_report_unknown_paths(
                                    child_model, [child_path])
                                and not self._soft_report_unknown_paths(
                                    record._name, [child_path])
                            )
                            source = record if from_parent else item
                            source_model = record._name if from_parent else child_model
                            val = self._resolve_field_path(source, child_path)
                            item_raw[child.placeholder] = val
                            if child_path and self._detect_html_field(
                                    child_path, source_model):
                                item_ctx[child.placeholder] = ''  # will render raw
                                item_hf[child.placeholder] = val
                            else:
                                item_ctx[child.placeholder] = self._format_value(val)
                        item_ctx['__raw__'] = item_raw
                        item_ctx['__record__'] = item
                        item_ctx['__html_fields__'] = item_hf
                        # Merge parent record raw values for cross-context access
                        # (e.g. master_product_id.proforma_name from sale.order
                        #  accessible inside {{#order_line}} loop)
                        for parent_key, parent_val in raw.items():
                            if parent_key not in item_raw:
                                item_raw[parent_key] = parent_val
                                # Also format and add to display context
                                if parent_key in html_fields:
                                    item_ctx[parent_key] = ''
                                    item_hf[parent_key] = parent_val
                                else:
                                    item_ctx[parent_key] = self._format_value(parent_val)
                        item_ctx['__parent_raw__'] = dict(raw)
                        item_ctx['__parent_record__'] = record
                        loop_items.append(item_ctx)
                    loop_html_fields[fm.placeholder] = loop_hf
                    loops[fm.placeholder] = loop_items

            elif not fm.loop_parent:
                val = self._resolve_field_path(record, fm.field_path)
                raw[fm.placeholder] = val
                if fm.field_path and self._detect_html_field(fm.field_path):
                    context[fm.placeholder] = ''  # placeholder, actual rendering handles it
                    html_fields[fm.placeholder] = val
                else:
                    context[fm.placeholder] = self._format_value(val)

        # --- Parse tax_totals for structured tax breakdown ---
        tax_data = self._parse_tax_totals(record)
        if tax_data:
            # Merge flat context values (overwrite empty/missing values from
            # field-based resolution — system placeholders like
            # tax_totals_total are not real fields and resolve to '').
            for key, value in tax_data['context'].items():
                if key not in context or not context[key]:
                    context[key] = value
                    raw[key] = value
            # Merge tax_groups loop (always available, doesn't need field mapping)
            if 'tax_groups' in tax_data['loops']:
                loops['tax_groups'] = tax_data['loops']['tax_groups']
            if 'tax_subtotals' in tax_data['subtotal_loops']:
                loops['tax_subtotals'] = tax_data['subtotal_loops']['tax_subtotals']

        context['__loops__'] = loops
        context['__raw__'] = raw
        context['__record__'] = record
        context['__html_fields__'] = html_fields
        context['__loop_html_fields__'] = loop_html_fields
        return context

    # ------------------------------------------------------------------
    #  Field resolution helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _resolve_field_path(record, field_path):
        """Safely walk a dot-separated field path on a record."""
        if not field_path:
            return ''
        obj = record
        for part in field_path.split('.'):
            if isinstance(obj, models.BaseModel):
                if part not in obj._fields:
                    _logger.warning(
                        'Field %s not found on model %s', part, obj._name,
                    )
                    return ''
                try:
                    obj = obj[part]
                except Exception:
                    return ''
            else:
                return str(obj) if obj else ''
        return obj

    def _format_value(self, value):
        """Convert a field value to a display string."""
        if isinstance(value, bool):
            return self.env._('Yes') if value else self.env._('No')
        if isinstance(value, models.BaseModel):
            return value.display_name or ''
        if value is False or value is None:
            return ''
        return str(value)

    # ------------------------------------------------------------------
    #  HTML→DOCX rendering
    # ------------------------------------------------------------------

    def _detect_html_field(self, field_path, model_name=None):
        """Check if a field path resolves to an HTML type field.

        :param str model_name: model to resolve the path on.  Loop children
            belong to the loop item's model, not to ``self.model_name``, so
            an HTML field on the child (e.g. ``mail.message.body``) used to be
            printed as literal ``<p>`` tags.
        """
        model_name = model_name or self.model_name
        if not field_path or not model_name or model_name not in self.env:
            return False
        Model = self.env[model_name]
        parts = field_path.split('.')
        obj = Model
        for i, part in enumerate(parts):
            if part not in obj._fields:
                return False
            field = obj._fields[part]
            if i < len(parts) - 1:
                comodel = getattr(field, 'comodel_name', None)
                if comodel:
                    obj = self.env[comodel]
                else:
                    return False
            else:
                return field.type == 'html'
        return False

    def _html_to_docx_runs(self, para, html_content, context, images, img_counter,
                           clean=True):
        """Replace paragraph content with formatted DOCX runs from HTML.

        Handles: <b>/<strong>, <i>/<em>, <u>/<ins>, <br>, <p>, <ul>/<ol>/<li>,
        <img>, <a>, <span>, <div>, <h1>-<h6>.

        :param bool clean: remove the runs already present in ``para`` first.
            ``_html_docx_replace`` clears the paragraph once for the whole
            placeholder list and then passes ``clean=False``: clearing here
            again used to delete the text runs built for the parts *before*
            the HTML field (``Sayın {{partner}}, {{note}}`` lost ``Sayın …``).
        """
        # Clean existing runs first so empty input leaves the para clean
        if clean:
            for r in list(para.findall('{%s}r' % W_NS)):
                para.remove(r)

        if not html_content or not html_content.strip():
            return

        # Strip control chars that lxml refuses to parse (NUL, etc.)
        if isinstance(html_content, str):
            html_content = re.sub(r'[\x00-\x08\x0b-\x1f]', '', html_content)

        # Normalize whitespace in HTML
        html_content = html_content.strip()

        if not html_content:
            return

        # Parse HTML — try in order:
        # 1) lxml fragment (multiple top-level nodes)
        # 2) lxml wrapped in <div>
        # 3) plain text fallback (BUG-2: was dead code)
        try:
            root = lh.fragment_fromstring(html_content)
        except (etree.ParserError, ValueError, TypeError, UnicodeError):
            try:
                root = lh.fromstring('<div>%s</div>' % html_content)
            except (etree.ParserError, ValueError, TypeError, UnicodeError):
                # Plain-text fallback
                self._emit_text_run(para, html_content)
                return

        self._html_node_to_docx(para, root, images, img_counter)

    def _emit_text_run(self, para, text, bold=False, italic=False,
                       underline=False):
        """Append a single <w:r> with the given text and formatting."""
        if not text:
            return
        run = etree.SubElement(para, '{%s}r' % W_NS)
        if bold or italic or underline:
            rpr = etree.SubElement(run, '{%s}rPr' % W_NS)
            if bold:
                etree.SubElement(rpr, '{%s}b' % W_NS)
            if italic:
                etree.SubElement(rpr, '{%s}i' % W_NS)
            if underline:
                u_el = etree.SubElement(rpr, '{%s}u' % W_NS)
                u_el.set('{%s}val' % W_NS, 'single')
        t_el = etree.SubElement(run, '{%s}t' % W_NS)
        t_el.text = text
        t_el.set('{%s}space' % XML_NS, 'preserve')

    def _emit_break(self, para, count=1):
        """Append *count* <w:br/> inside their own runs."""
        for _ in range(count):
            run = etree.SubElement(para, '{%s}r' % W_NS)
            etree.SubElement(run, '{%s}br' % W_NS)

    def _html_node_to_docx(self, para, node, images, img_counter,
                           bold=False, italic=False, underline=False,
                           list_index=0):
        """Recursively convert an HTML node tree to DOCX runs.

        :param list_index: current item number when inside <ol>, else 0
        """
        if node is None:
            return

        tag = getattr(node, 'tag', None)

        # Text nodes
        if tag is None:
            # Never strip() a text node: ``Hello <b>World</b> again`` arrives as
            # three nodes and stripping each one glued the words together
            # ("HelloWorldagain"). Only whitespace-only nodes are dropped and
            # source line breaks inside a run are collapsed to a single space.
            text = node if isinstance(node, str) else str(node or '')
            if not text.strip():
                return
            text = re.sub(r'[\r\n\t]+', ' ', text)
            self._emit_text_run(para, text, bold, italic, underline)
            return

        # Comments and processing instructions carry no printable text
        if not isinstance(tag, str):
            return

        tag_lower = tag.lower()

        # --- Formatting tags ---
        new_bold = bold or tag_lower in ('b', 'strong')
        new_italic = italic or tag_lower in ('i', 'em')
        new_underline = underline or tag_lower in ('u', 'ins')

        # --- Line break ---
        if tag_lower == 'br':
            self._emit_break(para)
            return

        # --- Paragraph ---
        if tag_lower == 'p':
            self._html_node_to_docx(
                para, node.text, images, img_counter,
                new_bold, new_italic, new_underline, list_index,
            )
            for child in node:
                self._html_node_to_docx(
                    para, child, images, img_counter,
                    new_bold, new_italic, new_underline, list_index,
                )
                self._html_node_to_docx(
                    para, child.tail, images, img_counter,
                    new_bold, new_italic, new_underline, list_index,
                )
            # Paragraph break: double line break
            self._emit_break(para, count=2)
            return

        # --- Headings ---
        if tag_lower in ('h1', 'h2', 'h3', 'h4', 'h5', 'h6'):
            self._html_node_to_docx(
                para, node.text, images, img_counter,
                True, False, False, list_index,
            )
            for child in node:
                self._html_node_to_docx(
                    para, child, images, img_counter,
                    True, new_italic, new_underline, list_index,
                )
                self._html_node_to_docx(
                    para, child.tail, images, img_counter,
                    True, new_italic, new_underline, list_index,
                )
            self._emit_break(para)
            return

        # --- Ordered list: number each <li> (BUG-6 fix) ---
        if tag_lower == 'ol':
            for i, child in enumerate(node, start=1):
                self._html_node_to_docx(
                    para, child, images, img_counter,
                    new_bold, new_italic, new_underline, list_index=i,
                )
            return

        # --- Unordered list / description list ---
        if tag_lower in ('ul', 'dl'):
            for child in node:
                self._html_node_to_docx(
                    para, child, images, img_counter,
                    new_bold, new_italic, new_underline, list_index=0,
                )
            return

        if tag_lower == 'li':
            if list_index:
                marker = '%d. ' % list_index
            else:
                marker = '\u2022 '  # bullet
            self._emit_text_run(para, marker)
            self._html_node_to_docx(
                para, node.text, images, img_counter,
                new_bold, new_italic, new_underline, list_index=0,
            )
            for child in node:
                self._html_node_to_docx(
                    para, child, images, img_counter,
                    new_bold, new_italic, new_underline, list_index=0,
                )
                self._html_node_to_docx(
                    para, child.tail, images, img_counter,
                    new_bold, new_italic, new_underline, list_index=0,
                )
            self._emit_break(para)
            return

        # --- Images ---
        if tag_lower == 'img':
            img_src = node.get('src', '')
            self._html_img_to_docx(para, img_src, images, img_counter)
            return

        # --- Links ---
        if tag_lower == 'a':
            self._html_node_to_docx(
                para, node.text, images, img_counter,
                new_bold, new_italic, True, list_index,
            )
            for child in node:
                self._html_node_to_docx(
                    para, child, images, img_counter,
                    new_bold, new_italic, True, list_index,
                )
                self._html_node_to_docx(
                    para, child.tail, images, img_counter,
                    new_bold, new_italic, True, list_index,
                )
            return

        # --- Div, span, section, header, footer, etc. (passthrough) ---
        self._html_node_to_docx(
            para, node.text, images, img_counter,
            new_bold, new_italic, new_underline, list_index,
        )
        for child in node:
            self._html_node_to_docx(
                para, child, images, img_counter,
                new_bold, new_italic, new_underline, list_index,
            )
            self._html_node_to_docx(
                para, child.tail, images, img_counter,
                new_bold, new_italic, new_underline, list_index,
            )

    def _html_img_to_docx(self, para, img_src, images, img_counter):
        """Extract and insert an image from HTML src attribute into DOCX."""
        if not img_src:
            return

        img_data = None

        # data: URI (base64 encoded)
        if img_src.startswith('data:'):
            try:
                _, b64part = img_src.split(',', 1)
                img_data = base64.b64decode(b64part)
            except (ValueError, TypeError, binascii.Error):
                return

        # /web/image/... Odoo URL
        elif '/web/image/' in img_src:
            img_data = self._fetch_web_image(img_src)

        if not img_data or len(img_data) < 8:
            # 8 bytes covers the smallest image magic header (PNG: 8 bytes
            # including the 4-byte length that follows the signature).
            return

        fmt = self._detect_image_format(img_data)
        cx, cy = self._get_image_size_emu(img_data)
        rid = 'rId%d' % img_counter[0]
        filename = 'image%d.%s' % (img_counter[0], fmt)
        img_counter[0] += 1
        images[rid] = (filename, img_data)

        img_run = self._create_image_run(rid, filename, cx, cy, img_counter[0])
        para.append(img_run)

    def _fetch_web_image(self, img_src):
        """Parse /web/image/<model>/<id>/<field>[/<size>] and fetch bytes.

        Returns the decoded image bytes, or None if the URL is malformed
        or the record/field is empty.
        """
        try:
            # Strip query and trailing slash
            path = img_src.split('/web/image/', 1)[1].split('?')[0].rstrip('/')
            segs = [s for s in path.split('/') if s]
            if len(segs) < 2:
                return None
            model_name = segs[0]
            if model_name not in self.env:
                return None
            Model = self.env[model_name]

            # /web/image/<model>/<id>/<field>[/<size>]
            # or  /web/image/<model>/<id>-<field>  (older syntax)
            second = segs[1]
            rec_id = None
            field_name = None
            try:
                rec_id = int(second)
                field_name = segs[2] if len(segs) > 2 else None
            except ValueError:
                if '-' in second:
                    rid_str, field_name = second.split('-', 1)
                    try:
                        rec_id = int(rid_str)
                    except ValueError:
                        return None
            if not rec_id or not field_name:
                return None
            record = Model.browse(rec_id).exists()
            if not record or field_name not in record._fields:
                return None
            val = record[field_name]
            if not val:
                return None
            if isinstance(val, str):
                try:
                    return base64.b64decode(val)
                except (binascii.Error, ValueError):
                    return None
            if isinstance(val, bytes):
                # Binary fields may store raw image bytes, OR the base64
                # encoded form as bytes (Odoo 19 default for image_*).
                # Detect by magic header; if absent, try b64decode.
                if val[:4] in _IMAGE_MAGIC_HEADERS or val[:2] == b'\xff\xd8':
                    return val
                try:
                    decoded = base64.b64decode(val, validate=True)
                    if (decoded[:4] in _IMAGE_MAGIC_HEADERS
                            or decoded[:2] == b'\xff\xd8'):
                        return decoded
                except (binascii.Error, ValueError):
                    pass
                return val
        except Exception:
            _logger.debug('web image fetch failed for %s', img_src)
        return None

    def _resolve_placeholder(self, ph, context):
        """Resolve a single placeholder to its display value.

        Handles:
        - ``{{field}}``          → simple lookup
        - ``{{field|format}}``   → value + format pipe
        - ``{{#...}}`` / ``{{/...}}`` → control tags → ''
        - ``{{img:field}}``      → '' (images handled in dedicated pass)
        - HTML fields            → stripped HTML
        """
        if ph.startswith('#') or ph.startswith('/'):
            return ''
        if ph.startswith('='):
            return str(self._eval_expression(ph[1:], context))
        if ph.startswith('img:'):
            return ''   # images handled separately
        if '|' in ph:
            field_name, fmt = ph.split('|', 1)
            field_name = field_name.strip()
            fmt = fmt.strip()
            record = context.get('__record__')
            raw_val = context.get('__raw__', {}).get(field_name)
            if raw_val is None and record:
                raw_val = self._resolve_field_path(record, field_name)
            # Fallback to parent record for cross-context fields
            # (e.g. master_product_id.proforma_name inside {{#order_line}} loop)
            if raw_val is None:
                parent = context.get('__parent_record__')
                if parent:
                    raw_val = self._resolve_field_path(parent, field_name)
            return self._apply_format_pipe(raw_val, fmt, record)

        # HTML field rendered as plain text (non-DOCX fallback path)
        html_fields = context.get('__html_fields__', {})
        if ph in html_fields:
            raw_html = html_fields[ph]
            if raw_html:
                return self._strip_html_tags(str(raw_html))
            return ''

        # Check loop context for HTML fields
        loop_html = context.get('__loop_html_fields__', {})
        if ph in loop_html:
            raw_html = loop_html[ph]
            if raw_html:
                return self._strip_html_tags(str(raw_html))
            return ''

        # Try context first, then parent record for cross-context fields
        # (e.g. master_product_id.proforma_name inside {{#order_line}} loop)
        val = context.get(ph)
        if val is None:
            parent = context.get('__parent_record__')
            if parent:
                val = self._resolve_field_path(parent, ph)
                if val is not None and val != '':
                    val = self._format_value(val)
        if val is None:
            # Keep the marker in the output but make the problem visible in the
            # log: an unmapped placeholder used to ship silently.
            _logger.warning(
                'Unresolved template placeholder %r was printed as-is', ph)
            return '{{%s}}' % ph
        return str(val)

    @staticmethod
    def _strip_html_tags(html_text):
        """Strip HTML tags and normalize whitespace."""
        text = re.sub(r'<[^>]+>', ' ', html_text)
        # Decode common HTML entities
        text = text.replace('&nbsp;', ' ').replace('&amp;', '&')
        text = text.replace('&lt;', '<').replace('&gt;', '>')
        text = text.replace('&quot;', '"').replace('&#39;', "'")
        # Normalize whitespace
        text = re.sub(r'\s+', ' ', text).strip()
        return text

    def _expression_namespace(self, context, expr=None):
        """safe_eval namespace for ``{{=expr}}`` and ``{{#if expr}}``.

        Values only: the mapped raw values plus the wrapped ``time`` and
        ``datetime`` modules. The environment, the user and the cursor are NOT
        reachable from template content (see :class:`_TemplateValueProxy`).

        When *expr* is given, bare field names used in the expression are
        resolved from the record as well — ``{{#if amount_total > 100}}`` used
        to fail unless ``{{amount_total}}`` also appeared in the document.
        """
        namespace = {
            name: _TemplateValueProxy._wrap(value)
            for name, value in context.get('__raw__', {}).items()
            if not name.startswith('__')
        }
        record = context.get('__record__')
        if expr and record:
            parent = context.get('__parent_record__')
            for name in set(re.findall(r'[A-Za-z_]\w*', expr)):
                if name in namespace:
                    continue
                value = None
                if name in getattr(record, '_fields', {}):
                    value = self._resolve_field_path(record, name)
                elif parent and name in getattr(parent, '_fields', {}):
                    value = self._resolve_field_path(parent, name)
                else:
                    continue
                namespace[name] = _TemplateValueProxy._wrap(value)
        namespace['o'] = namespace['record'] = _TemplateValueProxy._wrap(record)
        namespace['time'] = safe_time
        namespace['datetime'] = safe_datetime
        return namespace

    def _eval_expression(self, expr, context):
        """Evaluate ``{{=expr}}`` using safe_eval."""
        try:
            result = safe_eval(
                expr.strip(), self._expression_namespace(context, expr))
        except Exception as exc:
            raise UserError(self.env._(
                'The template expression %(expr)s could not be evaluated: %(error)s',
                expr='{{=%s}}' % expr, error=exc,
            )) from exc
        if result is None:
            return ''
        return self._format_value(result)

    def _eval_condition(self, condition, context):
        """Evaluate a condition string for ``{{#if …}}``."""
        record = context.get('__record__')

        # Simple field truthiness: {{#if field_name}}
        if re.match(r'^[a-zA-Z_][a-zA-Z0-9_.]*$', condition):
            raw = context.get('__raw__', {})
            val = raw.get(condition)
            if val is None and record:
                val = self._resolve_field_path(record, condition)
            if val is None:
                val = context.get(condition)
            return bool(val) and val != '' and val != _('No')

        # Full expression: {{#if amount_total > 1000}}
        try:
            return bool(safe_eval(
                condition, self._expression_namespace(context, condition)))
        except Exception as exc:
            raise UserError(self.env._(
                'The template condition %(expr)s could not be evaluated: %(error)s',
                expr='{{#if %s}}' % condition, error=exc,
            )) from exc

    def _apply_format_pipe(self, raw_value, fmt, record=None):
        """Apply a format pipe to a raw field value.

        Supported pipes: ``date``, ``datetime``, ``currency``, ``number``,
        ``upper``, ``lower``, ``title``.
        """
        import datetime as _dt  # noqa: PLC0415

        if raw_value is False or raw_value is None:
            return ''
        fmt = fmt.lower()

        if fmt == 'upper':
            return str(raw_value).upper()
        if fmt == 'lower':
            return str(raw_value).lower()
        if fmt == 'title':
            return str(raw_value).title()

        if fmt == 'date':
            if isinstance(raw_value, (_dt.date, _dt.datetime)):
                if record and format_date:
                    return format_date(record.env, raw_value)
                return raw_value.strftime('%d/%m/%Y')
            return str(raw_value)

        if fmt == 'datetime':
            if isinstance(raw_value, _dt.datetime):
                if record and format_datetime:
                    return format_datetime(record.env, raw_value)
                return raw_value.strftime('%d/%m/%Y %H:%M')
            return str(raw_value)

        if fmt == 'currency':
            if isinstance(raw_value, (int, float)):
                if record and formatLang:
                    # Use record's own currency if available, else company currency
                    currency = getattr(record, 'currency_id', None) or record.env.company.currency_id
                    return formatLang(record.env, raw_value,
                                     currency_obj=currency)
                return '{:,.2f}'.format(raw_value)
            return str(raw_value)

        if fmt == 'number':
            if isinstance(raw_value, (int, float)):
                if record and formatLang:
                    return formatLang(record.env, raw_value)
                return '{:,.2f}'.format(raw_value)
            return str(raw_value)

        return str(raw_value)

    # ------------------------------------------------------------------
    #  Image helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _detect_image_format(data):
        """Detect image format from binary header."""
        if data[:8] == b'\x89PNG\r\n\x1a\n':
            return 'png'
        if data[:2] == b'\xff\xd8':
            return 'jpeg'
        if data[:4] == b'GIF8':
            return 'gif'
        if data[:4] == b'RIFF' and len(data) > 11 and data[8:12] == b'WEBP':
            return 'webp'
        if data[:2] == b'BM':
            return 'bmp'
        return 'png'

    @staticmethod
    def _get_image_size_emu(image_bytes,
                            max_width_cm=15, max_height_cm=10):
        """Return (cx, cy) in EMU, scaled to fit max dimensions."""
        EMU_PER_CM = 360000
        default_cx = 5 * EMU_PER_CM
        default_cy = 5 * EMU_PER_CM

        w_px = h_px = None

        if PILImage is not None:
            try:
                img = PILImage.open(BytesIO(image_bytes))
                w_px, h_px = img.size
            except Exception:
                pass
        else:
            # Fallback: read PNG / JPEG header with struct
            try:
                if image_bytes[:8] == b'\x89PNG\r\n\x1a\n':
                    w_px = struct.unpack('>I', image_bytes[16:20])[0]
                    h_px = struct.unpack('>I', image_bytes[20:24])[0]
                elif image_bytes[:2] == b'\xff\xd8':
                    # JPEG — scan for SOF marker
                    offset = 2
                    while offset < len(image_bytes) - 9:
                        marker = struct.unpack('>H', image_bytes[offset:offset+2])[0]
                        if 0xFFC0 <= marker <= 0xFFC3:
                            h_px = struct.unpack(
                                '>H', image_bytes[offset+5:offset+7])[0]
                            w_px = struct.unpack(
                                '>H', image_bytes[offset+7:offset+9])[0]
                            break
                        length = struct.unpack(
                            '>H', image_bytes[offset+2:offset+4])[0]
                        offset += 2 + length
            except Exception:
                pass

        if not w_px or not h_px:
            return default_cx, default_cy

        dpi = 96
        w_cm = w_px / dpi * 2.54
        h_cm = h_px / dpi * 2.54

        if w_cm > max_width_cm:
            ratio = max_width_cm / w_cm
            w_cm *= ratio
            h_cm *= ratio
        if h_cm > max_height_cm:
            ratio = max_height_cm / h_cm
            w_cm *= ratio
            h_cm *= ratio

        return int(w_cm * EMU_PER_CM), int(h_cm * EMU_PER_CM)

    # ==================================================================
    #  DOCX ENGINE
    # ==================================================================

    @staticmethod
    def _get_paragraph_text(para):
        """Concatenate all <w:t> texts in a paragraph."""
        parts = []
        for t in para.iter('{%s}t' % W_NS):
            if t.text:
                parts.append(t.text)
        return ''.join(parts)

    def _get_row_text(self, row):
        """Concatenate all paragraph texts in a table row."""
        parts = []
        for para in row.iter('{%s}p' % W_NS):
            parts.append(self._get_paragraph_text(para))
        return ' '.join(parts)

    # ---- rendering ----

    def _render_docx(self, file_bytes, context):
        """Render a DOCX template, return bytes of the filled document."""
        buf_in = BytesIO(file_bytes)
        images = {}       # {rId: (filename, image_bytes, source_part)}
        img_counter = [1000]  # mutable counter for unique IDs

        # First pass: process XML parts (may populate images dict)
        processed = {}
        with zipfile.ZipFile(buf_in, 'r') as zin:
            infos = zin.infolist()
            for item in infos:
                data = zin.read(item.filename)
                if (
                    item.filename.startswith('word/')
                    and item.filename.endswith('.xml')
                ):
                    part_images = {}
                    try:
                        data = self._process_docx_xml(
                            data, context, part_images, img_counter,
                        )
                    except UserError:
                        # A broken template expression must reach the user, it
                        # must not silently print a half-filled document.
                        raise
                    except Exception:
                        _logger.exception(
                            'Error processing %s', item.filename,
                        )
                    else:
                        # Remember which part produced each rId: header and
                        # footer images must be declared in their own .rels.
                        for rid, (fname, img_bytes) in part_images.items():
                            images[rid] = (fname, img_bytes, item.filename)
                processed[item.filename] = (item, data)

        # Group the collected images per source part
        rels_targets = {}
        for rid, (fname, img_bytes, part) in images.items():
            rels_name = 'word/_rels/%s.rels' % part.rsplit('/', 1)[-1]
            rels_targets.setdefault(rels_name, {})[rid] = (fname, img_bytes)

        # Second pass: update rels/content-types now that images are known
        buf_out = BytesIO()
        with zipfile.ZipFile(buf_out, 'w', zipfile.ZIP_DEFLATED) as zout:
            for filename, (item, data) in processed.items():
                if filename in rels_targets:
                    data = self._update_docx_rels(
                        data, rels_targets.pop(filename))
                elif filename == '[Content_Types].xml' and images:
                    data = self._update_content_types(data, images)
                zout.writestr(item, data)

            # Rels parts the template did not ship (header/footer images): a
            # dangling r:embed makes Word ask to "repair" the document.
            for rels_name, group in rels_targets.items():
                zout.writestr(rels_name, self._build_docx_rels(group))

            # Write collected images into word/media/
            for _rid, (fname, img_bytes, _part) in images.items():
                zout.writestr('word/media/' + fname, img_bytes)

        return buf_out.getvalue()

    def _normalize_cross_paragraph_placeholders(self, tree):
        """Merge {{placeholder}} fragments split across adjacent <w:p> elements.

        Word and LibreOffice sometimes split a single placeholder across
        two consecutive paragraphs (e.g. when text wraps in narrow table
        cells or when formatting/rsid markers intervene).

        This scans every container (body, table cells, text boxes) and
        when a paragraph ends with an unclosed ``{{...`` and the *next*
        non-empty paragraph starts with the remainder, the runs from
        the second paragraph are moved into the first.
        """
        # All containers that can hold <w:p> children
        containers = list(tree.iter('{%s}body' % W_NS))
        containers += list(tree.iter('{%s}tc' % W_NS))       # table cells
        containers += list(tree.iter('{%s}txbxContent' % W_NS))  # text boxes

        for container in containers:
            changed = True
            while changed:
                changed = False
                # Collect direct-child paragraphs, skipping empty ones
                paras = [
                    child for child in container
                    if child.tag == '{%s}p' % W_NS
                ]
                if len(paras) < 2:
                    break

                for idx in range(len(paras) - 1):
                    p1 = paras[idx]
                    p2 = paras[idx + 1]

                    text1 = self._get_paragraph_text(p1)
                    text2 = self._get_paragraph_text(p2)

                    # Empty paragraphs are irrelevant
                    if not text1 or not text2:
                        continue

                    # Check if p1 has an unclosed {{ (no }} after it)
                    open_pos = text1.rfind('{{')
                    close_pos = text1.rfind('}}')

                    if open_pos >= 0 and (close_pos < 0 or open_pos > close_pos):
                        # p1 ends with an open placeholder — p2 should close it
                        if '}}' in text2:
                            # Merge: move all child elements from p2 into p1.
                            # A paragraph has exactly one w:pPr (and possibly
                            # one w:sectPr) and they must not end up in the
                            # middle of the merged paragraph: the old code
                            # produced ['pPr','r','pPr','r'], which makes Word
                            # offer to repair the document.
                            for child in list(p2):
                                if child.tag in (
                                    '{%s}pPr' % W_NS, '{%s}sectPr' % W_NS,
                                ):
                                    continue
                                p1.append(child)
                            container.remove(p2)
                            changed = True
                            break  # restart — child list is stale

    def _process_docx_xml(self, xml_bytes, context,
                          images=None, img_counter=None):
        """Replace placeholders in one XML part of the DOCX.

        Pipeline (order matters):
        1. Normalize — merge placeholders split across runs/paragraphs
        2. Table-row loops — each copied row is then rendered with its own
           loop context (conditionals, images and values of the row item)
        3. Conditionals — process ``{{#if}}/{{#else}}/{{/if}}`` blocks
        4. Images — replace ``{{img:field}}`` with inline images
        5. Simple replacement — resolve remaining ``{{placeholder}}`` text

        Conditionals and images run *after* the loops on purpose: they used to
        run before, so a ``{{#if}}`` or ``{{img:…}}`` sitting inside a loop row
        was evaluated against the parent record and printed the wrong data.
        """
        tree = etree.fromstring(xml_bytes)

        # 1) normalise — merge split placeholders *before* everything else
        self._normalize_cross_paragraph_placeholders(tree)

        # 2) table-row loops (per-row conditionals/images/values inside)
        self._process_docx_table_loops(tree, context, images, img_counter)

        # 3) conditionals  — {{#if}} / {{#else}} / {{/if}}
        self._process_docx_conditionals(tree, context)

        # 4) images — {{img:field}}
        if images is not None:
            self._process_docx_images(tree, context, images, img_counter)

        # 5) simple placeholder replacement
        self._process_docx_simple_replacements(tree, context, images, img_counter)

        return etree.tostring(
            tree, xml_declaration=True, encoding='UTF-8', standalone=True,
        )

    def _process_docx_table_loops(self, tree, context, images, img_counter):
        """Step 4: duplicate table rows per loop record."""
        loops = context.get('__loops__', {})
        if not loops:
            return
        self._docx_table_loops(tree, loops, images, img_counter)

    def _process_docx_simple_replacements(self, tree, context, images,
                                          img_counter):
        """Step 5: resolve ``{{placeholder}}`` for every paragraph."""
        for para in tree.iter('{%s}p' % W_NS):
            self._docx_replace_paragraph(para, context, images, img_counter)

    def _docx_replace_paragraph(self, para, context, images=None, img_counter=None):
        """Replace {{…}} in a single paragraph.
        
        Handles HTML content specially — converts to formatted DOCX runs.
        """
        text_elements = list(para.iter('{%s}t' % W_NS))
        if not text_elements:
            return

        full_text = ''.join(t.text or '' for t in text_elements)
        if '{{' not in full_text:
            return

        # Check if this paragraph has any HTML field placeholders
        html_fields = context.get('__html_fields__', {})
        has_html = any(
            '{{%s}}' % ph in full_text or '{{%s|' % ph in full_text
            for ph in html_fields
        )

        if has_html:
            # HTML field rendering — replace placeholder with formatted runs
            self._html_docx_replace(para, full_text, context, images, img_counter,
                                     html_fields)
            return

        # Standard (non-HTML) replacement
        def _repl(m):
            ph = m.group(1).strip()
            return self._resolve_placeholder(ph, context)

        new_text = re.sub(r'\{\{(.+?)\}\}', _repl, full_text)
        if new_text == full_text:
            return

        # Put everything in the first <w:t>, blank the rest
        text_elements[0].text = new_text
        text_elements[0].set('{%s}space' % XML_NS, 'preserve')
        for t in text_elements[1:]:
            t.text = ''

    def _html_docx_replace(self, para, full_text, context, images, img_counter,
                            html_fields):
        """Replace placeholders in a paragraph, rendering HTML fields as DOCX runs.
        
        Non-HTML placeholders are resolved as plain text.
        HTML placeholders get the raw HTML from __html_fields__ and are rendered
        via _html_to_docx_runs.
        """
        if images is None:
            images = {}
        if img_counter is None:
            img_counter = [1000]

        parts = []
        last_end = 0
        for m in re.finditer(r'\{\{(.+?)\}\}', full_text):
            start, end = m.start(), m.end()
            ph = m.group(1).strip()
            # Text before this placeholder
            if start > last_end:
                parts.append(('text', full_text[last_end:start]))
            # Check if it's an HTML field
            field_name = ph.split('|')[0].strip()
            raw_html = html_fields.get(field_name)
            if '=' in ph or 'img:' in ph:
                # Expression or image — resolve as usual
                parts.append(('text', self._resolve_placeholder(ph, context)))
            elif raw_html:
                parts.append(('html', raw_html))
            else:
                parts.append(('text', self._resolve_placeholder(ph, context)))
            last_end = end

        if last_end < len(full_text):
            parts.append(('text', full_text[last_end:]))

        # Remove all existing runs from paragraph
        for r in list(para.findall('{%s}r' % W_NS)):
            para.remove(r)

        # Render each part
        for ptype, content in parts:
            if ptype == 'text' and content:
                run = etree.SubElement(para, '{%s}r' % W_NS)
                t_el = etree.SubElement(run, '{%s}t' % W_NS)
                t_el.text = content
                t_el.set('{%s}space' % XML_NS, 'preserve')
            elif ptype == 'html':
                self._html_to_docx_runs(
                    para, content, context, images, img_counter, clean=False,
                )

    # ---- conditionals ----

    def _process_docx_conditionals(self, parent, context):
        """Process ``{{#if}}``, ``{{#else}}``, ``{{/if}}`` blocks.

        Works on body, table cells, or any container with paragraphs
        and table rows as children.  Supports nesting.
        """
        stack = []   # list of bools: True = currently showing
        to_remove = []

        for child in list(parent):
            tag = child.tag.split('}')[-1] if '}' in child.tag else child.tag

            # Get text content
            text = ''
            if tag == 'p':
                text = self._get_paragraph_text(child)
            elif tag == 'tr':
                text = self._get_row_text(child)

            # {{#if condition}}
            if_match = re.search(r'\{\{#if\s+(.+?)\}\}', text) if text else None
            if if_match:
                parent_showing = stack[-1] if stack else True
                if parent_showing:
                    # A block written inside a single paragraph ("A {{#if x}}
                    # yes {{/if}} B") keeps its text: the marker used to take
                    # the whole paragraph down, silently dropping the content.
                    inline = self._render_inline_conditionals(text, context)
                    if inline is not None:
                        if tag != 'tr':
                            self._set_paragraph_text(child, inline)
                            continue
                        if not self._row_has_block_conditional(child):
                            # A complete inline block inside one cell
                            # paragraph: let the paragraph render it. Writing
                            # the result on the row produced a w:r child of
                            # w:tr (invalid OOXML) and left both branches in
                            # the cells. A conditional spanning separate
                            # paragraphs is a block marker row and keeps the
                            # row-level handling below.
                            for tc in child.findall('{%s}tc' % W_NS):
                                self._process_docx_conditionals(tc, context)
                            continue
                    result = self._eval_condition(
                        if_match.group(1).strip(), context)
                    stack.append(result)
                else:
                    stack.append(False)
                to_remove.append(child)
                continue

            # {{#else}}
            if '{{#else}}' in text:
                if stack:
                    parent_showing = stack[-2] if len(stack) > 1 else True
                    if parent_showing:
                        stack[-1] = not stack[-1]
                to_remove.append(child)
                continue

            # {{/if}}
            if '{{/if}}' in text:
                if stack:
                    stack.pop()
                to_remove.append(child)
                continue

            # If currently inside a false block, remove
            if stack and not stack[-1]:
                to_remove.append(child)
                continue

            # Recurse into containers. ``sdt``/``sdtContent`` are Word content
            # controls: templates built with them were skipped here, so the
            # markers inside survived and the block was always printed.
            if tag in ('body', 'tbl', 'tc', 'txbxContent',
                       'sdt', 'sdtContent', 'hdr', 'ftr'):
                self._process_docx_conditionals(child, context)
            elif tag == 'tr':
                for tc in child.findall('{%s}tc' % W_NS):
                    self._process_docx_conditionals(tc, context)

        for elem in to_remove:
            try:
                parent.remove(elem)
            except ValueError:
                pass

    def _row_has_block_conditional(self, row):
        """Return True when *row* contains a marker spread over paragraphs.

        ``{{#if}}``/``{{/if}}`` in the same paragraph is an inline block; one
        paragraph carrying only the opening (or only the closing) marker means
        the condition spans cells/paragraphs and belongs to the row, where it
        is handled by the block stack (the row is dropped when false).
        """
        for para in row.iter('{%s}p' % W_NS):
            text = self._get_paragraph_text(para)
            if ('{{#if' in text) != ('{{/if}}' in text):
                return True
        return False

    def _render_inline_conditionals(self, text, context):
        """Render ``{{#if}}`` blocks opened and closed in the same paragraph.

        ``A {{#if x}}yes{{/if}} B`` used to lose the whole paragraph, text
        included.  Returns ``None`` when the paragraph only holds markers (block
        style, handled by the caller paragraph-by-paragraph) or when the blocks
        are nested.
        """
        if '{{#if' not in text or '{{/if}}' not in text:
            return None
        residual = re.sub(r'\{\{#if\s+.+?\}\}', '', text)
        residual = residual.replace('{{#else}}', '').replace('{{/if}}', '')
        if not residual.strip():
            return None  # marker-only paragraph: a block marker, not content

        out = []
        pos = 0
        while True:
            start = text.find('{{#if', pos)
            if start < 0:
                break
            open_match = re.match(r'\{\{#if\s+(.+?)\}\}', text[start:])
            if not open_match:
                return None
            end = text.find('{{/if}}', start + open_match.end())
            if end < 0:
                return None
            inner = text[start + open_match.end():end]
            if '{{#if' in inner or '{{/if}}' in inner:
                return None  # nested inline blocks are not supported
            then_part, _sep, else_part = inner.partition('{{#else}}')
            condition = open_match.group(1).strip()
            keep = then_part if self._eval_condition(condition, context) else else_part
            out.append(text[pos:start])
            out.append(keep)
            pos = end + len('{{/if}}')
        out.append(text[pos:])
        return ''.join(out)

    def _set_paragraph_text(self, para, text):
        """Replace the content of *para* with a single run holding *text*."""
        for run in list(para.findall('{%s}r' % W_NS)):
            para.remove(run)
        if text and text.strip():
            self._emit_text_run(para, text)

    # ---- images ----

    def _process_docx_images(self, tree, context, images, img_counter):
        """Replace ``{{img:field_path}}`` with inline images."""
        record = context.get('__record__')
        if not record:
            return

        for para in list(tree.iter('{%s}p' % W_NS)):
            text = self._get_paragraph_text(para)
            if '{{img:' not in text:
                continue

            matches = list(re.finditer(r'\{\{img:(.+?)\}\}', text))
            if not matches:
                continue

            # Resolve images
            resolved = []
            for m in matches:
                field_path = m.group(1).strip()
                raw_val = self._resolve_field_path(record, field_path)
                _logger.debug(
                    'IMG placeholder=%s field_path=%s raw_val_type=%s raw_val_len=%s',
                    m.group(0), field_path,
                    type(raw_val).__name__,
                    len(raw_val) if raw_val else 0,
                )
                img_data = None
                if raw_val:
                    if isinstance(raw_val, str):
                        try:
                            img_data = base64.b64decode(raw_val)
                        except Exception:
                            pass
                    elif isinstance(raw_val, bytes):
                        # Odoo binary fields may return base64 as bytes
                        try:
                            img_data = base64.b64decode(raw_val)
                        except Exception:
                            img_data = raw_val  # fallback: raw bytes

                if img_data and len(img_data) >= 8:
                    fmt = self._detect_image_format(img_data)
                    cx, cy = self._get_image_size_emu(img_data)
                    rid = 'rId%d' % img_counter[0]
                    filename = 'image%d.%s' % (img_counter[0], fmt)
                    img_counter[0] += 1
                    images[rid] = (filename, img_data)
                    resolved.append((m.start(), m.end(), rid, filename,
                                     cx, cy))
                else:
                    resolved.append((m.start(), m.end(),
                                     None, None, 0, 0))

            # Rebuild paragraph runs
            for r in list(para.findall('{%s}r' % W_NS)):
                para.remove(r)

            last_end = 0
            for start, end, rid, filename, cx, cy in resolved:
                seg = text[last_end:start]
                if seg:
                    run = etree.SubElement(para, '{%s}r' % W_NS)
                    t_el = etree.SubElement(run, '{%s}t' % W_NS)
                    t_el.text = seg
                    t_el.set('{%s}space' % XML_NS, 'preserve')
                if rid:
                    img_run = self._create_image_run(
                        rid, filename, cx, cy, img_counter[0])
                    para.append(img_run)
                last_end = end

            tail = text[last_end:]
            if tail:
                run = etree.SubElement(para, '{%s}r' % W_NS)
                t_el = etree.SubElement(run, '{%s}t' % W_NS)
                t_el.text = tail
                t_el.set('{%s}space' % XML_NS, 'preserve')

    @staticmethod
    def _create_image_run(rid, filename, cx, cy, doc_id):
        """Build a ``<w:r>`` element containing an inline drawing."""
        xml = (
            '<w:r xmlns:w="{w}" xmlns:wp="{wp}" xmlns:a="{a}" '
            'xmlns:pic="{pic}" xmlns:r="{r}">'
            '<w:drawing>'
            '<wp:inline distT="0" distB="0" distL="0" distR="0">'
            '<wp:extent cx="{cx}" cy="{cy}"/>'
            '<wp:docPr id="{did}" name="Image {did}"/>'
            '<a:graphic>'
            '<a:graphicData uri="{pic}">'
            '<pic:pic>'
            '<pic:nvPicPr>'
            '<pic:cNvPr id="0" name="{fn}"/>'
            '<pic:cNvPicPr/>'
            '</pic:nvPicPr>'
            '<pic:blipFill>'
            '<a:blip r:embed="{rid}"/>'
            '<a:stretch><a:fillRect/></a:stretch>'
            '</pic:blipFill>'
            '<pic:spPr>'
            '<a:xfrm>'
            '<a:off x="0" y="0"/>'
            '<a:ext cx="{cx}" cy="{cy}"/>'
            '</a:xfrm>'
            '<a:prstGeom prst="rect"><a:avLst/></a:prstGeom>'
            '</pic:spPr>'
            '</pic:pic>'
            '</a:graphicData>'
            '</a:graphic>'
            '</wp:inline>'
            '</w:drawing>'
            '</w:r>'
        ).format(
            w=W_NS, wp=WP_NS, a=A_NS, pic=PIC_NS, r=R_NS,
            cx=cx, cy=cy, did=doc_id, fn=filename, rid=rid,
        )
        return etree.fromstring(xml)

    @staticmethod
    def _update_docx_rels(rels_bytes, images):
        """Add image relationships to a ``.rels`` part."""
        tree = etree.fromstring(rels_bytes)
        for rid, (filename, _data) in images.items():
            rel = etree.SubElement(tree, '{%s}Relationship' % REL_NS)
            rel.set('Id', rid)
            rel.set('Type', IMG_REL_TYPE)
            rel.set('Target', 'media/' + filename)
        return etree.tostring(
            tree, xml_declaration=True, encoding='UTF-8', standalone=True)

    @staticmethod
    def _build_docx_rels(images):
        """Build a fresh ``.rels`` part for a header/footer without one."""
        tree = etree.Element('{%s}Relationships' % REL_NS, nsmap={None: REL_NS})
        for rid, (filename, _data) in images.items():
            rel = etree.SubElement(tree, '{%s}Relationship' % REL_NS)
            rel.set('Id', rid)
            rel.set('Type', IMG_REL_TYPE)
            rel.set('Target', 'media/' + filename)
        return etree.tostring(
            tree, xml_declaration=True, encoding='UTF-8', standalone=True)

    @staticmethod
    def _update_content_types(ct_bytes, images):
        """Ensure image content types are registered.

        OOXML requires the ``<Default>`` elements to come before any
        ``<Override>``; appending them used to leave the part out of schema
        order on every document that gained an image.
        """
        tree = etree.fromstring(ct_bytes)
        existing = {c.get('Extension', '').lower()
                     for c in tree if c.get('Extension')}
        mime_map = {
            'png': 'image/png', 'jpeg': 'image/jpeg', 'jpg': 'image/jpeg',
            'gif': 'image/gif', 'bmp': 'image/bmp', 'webp': 'image/webp',
        }
        needed = set()
        for entry in images.values():
            fn = entry[0]
            ext = fn.rsplit('.', 1)[-1].lower()
            needed.add(ext)
        for ext in sorted(needed - existing):
            ct = mime_map.get(ext, 'application/octet-stream')
            el = etree.Element('{%s}Default' % CT_NS)
            el.set('Extension', ext)
            el.set('ContentType', ct)
            first_override = tree.find('{%s}Override' % CT_NS)
            if first_override is not None:
                first_override.addprevious(el)
            else:
                tree.append(el)
        return etree.tostring(
            tree, xml_declaration=True, encoding='UTF-8', standalone=True)

    # ---- table-row loops ----

    def _docx_table_loops(self, tree, loops, images=None, img_counter=None):
        """Expand {{#name}} / {{/name}} table row blocks."""
        for table in tree.iter('{%s}tbl' % W_NS):
            self._docx_expand_table(table, loops, images, img_counter)

    def _docx_expand_table(self, table, loops, images=None, img_counter=None):
        """Process one <w:tbl> for loop expansion. Restarts on mutation."""
        changed = True
        while changed:
            changed = False
            rows = list(table.findall('{%s}tr' % W_NS))

            for loop_name, items in loops.items():
                start_tag = '{{#%s}}' % loop_name
                end_tag = '{{/%s}}' % loop_name
                start_idx = end_idx = None

                for i, row in enumerate(rows):
                    txt = self._get_row_text(row)
                    if start_tag in txt and start_idx is None:
                        start_idx = i
                    if end_tag in txt:
                        end_idx = i
                        break

                if start_idx is None or end_idx is None or end_idx <= start_idx:
                    continue

                # Rows between markers are the template
                template_rows = rows[start_idx + 1:end_idx]

                # Remember the element after the end-marker for insertion
                after = rows[end_idx + 1] if end_idx + 1 < len(rows) else None

                # Remove marker rows and template rows
                table.remove(rows[start_idx])
                for tr in template_rows:
                    table.remove(tr)
                table.remove(rows[end_idx])

                # Insert expanded rows
                for item_ctx in items:
                    for tmpl_row in template_rows:
                        new_row = deepcopy(tmpl_row)

                        # Normalize split placeholders inside copied cells
                        for tc in new_row.iter('{%s}tc' % W_NS):
                            changed_cell = True
                            while changed_cell:
                                changed_cell = False
                                paras = [
                                    c for c in tc
                                    if c.tag == '{%s}p' % W_NS
                                ]
                                for ci in range(len(paras) - 1):
                                    p1, p2 = paras[ci], paras[ci + 1]
                                    t1 = self._get_paragraph_text(p1)
                                    t2 = self._get_paragraph_text(p2)
                                    if not t1 or not t2:
                                        continue
                                    op = t1.rfind('{{')
                                    cp = t1.rfind('}}')
                                    if op >= 0 and (cp < 0 or op > cp) and '}}' in t2:
                                        for child in list(p2):
                                            if child.tag in (
                                                '{%s}pPr' % W_NS,
                                                '{%s}sectPr' % W_NS,
                                            ):
                                                continue
                                            p1.append(child)
                                        tc.remove(p2)
                                        changed_cell = True
                                        break

                        # A row's conditionals and images belong to the loop
                        # item, not to the record being printed: resolve them
                        # with the row context before the values are replaced.
                        for tc in new_row.iter('{%s}tc' % W_NS):
                            self._process_docx_conditionals(tc, item_ctx)
                        if images is not None:
                            self._process_docx_images(
                                new_row, item_ctx, images, img_counter)
                        for para in new_row.iter('{%s}p' % W_NS):
                            self._docx_replace_paragraph(para, item_ctx, images, img_counter)
                        if after is not None:
                            after.addprevious(new_row)
                        else:
                            table.append(new_row)

                changed = True
                break  # restart — row indices are stale
