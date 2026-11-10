# Part of Odoo. See LICENSE file for full copyright and licensing details.

"""Unit tests for the low-level DOCX text/placeholder helpers.

Targets the three helpers in ``DocxEngineMixin`` involved in the
``NameError`` regression (self used inside ``@staticmethod``):

* :func:`_get_paragraph_text` — static helper, no ``self``.
* :func:`_get_row_text` — instance method, calls ``self._get_paragraph_text``.
* :func:`_normalize_cross_paragraph_placeholders` — instance method,
  calls ``self._get_paragraph_text`` while walking the paragraph tree.

The tests guard against a recurrence of the static-method ``self``
regression and verify that the placeholder-normalisation logic still
merges split ``{{...}}`` fragments across adjacent paragraphs in body,
table cells, and text boxes.
"""

from lxml import etree

from odoo.tests import tagged

from odoo.addons.soft_report_generator.models.docx_engine import (
    DocxEngineMixin,
)
from odoo.addons.soft_report_generator.tests.common import (
    SoftReportGeneratorCommon,
    W_NS,
)


def _xml(s):
    """Parse a fragment string into an lxml element."""
    return etree.fromstring(s)


@tagged('post_install', '-at_install')
class TestDocxEngineHelpers(SoftReportGeneratorCommon):
    """Unit tests for static DOCX helpers."""

    def setUp(self):
        super().setUp()
        # `_get_row_text` and `_normalize_cross_paragraph_placeholders`
        # are instance methods, so they need a recordset handle. An
        # abstract mixin can be instantiated via self.env as an empty
        # recordset.
        self.mixin = self.env['soft.report.template.docx.mixin']

    # ------------------------------------------------------------------
    #  _get_paragraph_text
    # ------------------------------------------------------------------

    def test_get_paragraph_text_single_run(self):
        para = _xml(
            '<w:p xmlns:w="%s">'
            '<w:r><w:t>Hello world</w:t></w:r>'
            '</w:p>' % W_NS
        )
        self.assertEqual(
            DocxEngineMixin._get_paragraph_text(para),
            'Hello world',
        )

    def test_get_paragraph_text_multiple_runs(self):
        para = _xml(
            '<w:p xmlns:w="%s">'
            '<w:r><w:t>Hello </w:t></w:r>'
            '<w:r><w:t>brave </w:t></w:r>'
            '<w:r><w:t>world</w:t></w:r>'
            '</w:p>' % W_NS
        )
        self.assertEqual(
            DocxEngineMixin._get_paragraph_text(para),
            'Hello brave world',
        )

    def test_get_paragraph_text_empty(self):
        para = _xml('<w:p xmlns:w="%s"/>' % W_NS)
        self.assertEqual(DocxEngineMixin._get_paragraph_text(para), '')

    def test_get_paragraph_text_skips_empty_t(self):
        para = _xml(
            '<w:p xmlns:w="%s">'
            '<w:r><w:t></w:t></w:r>'
            '<w:r><w:t>foo</w:t></w:r>'
            '<w:r><w:t/></w:r>'
            '</w:p>' % W_NS
        )
        self.assertEqual(
            DocxEngineMixin._get_paragraph_text(para),
            'foo',
        )

    # ------------------------------------------------------------------
    #  _get_row_text
    # ------------------------------------------------------------------

    def test_get_row_text_single_cell(self):
        row = _xml(
            '<w:tr xmlns:w="%s">'
            '<w:tc><w:p><w:r><w:t>Cell A</w:t></w:r></w:p></w:tc>'
            '</w:tr>' % W_NS
        )
        self.assertEqual(
            self.mixin._get_row_text(row),
            'Cell A',
        )

    def test_get_row_text_multiple_cells(self):
        row = _xml(
            '<w:tr xmlns:w="%s">'
            '<w:tc><w:p><w:r><w:t>Qty</w:t></w:r></w:p></w:tc>'
            '<w:tc><w:p><w:r><w:t>3</w:t></w:r></w:p></w:tc>'
            '</w:tr>' % W_NS
        )
        self.assertEqual(
            self.mixin._get_row_text(row),
            'Qty 3',
        )

    def test_get_row_text_empty(self):
        row = _xml('<w:tr xmlns:w="%s"/>' % W_NS)
        self.assertEqual(self.mixin._get_row_text(row), '')

    # ------------------------------------------------------------------
    #  _normalize_cross_paragraph_placeholders
    # ------------------------------------------------------------------

    def test_normalize_merges_split_placeholder_in_body(self):
        # Body contains two paragraphs: first ends with "{{name",
        # second starts with "}}". After merge there should be one
        # paragraph holding the full text "{{name}}".
        tree = _xml(
            '<w:document xmlns:w="%s">'
            '<w:body>'
            '<w:p><w:r><w:t>Hello {{name</w:t></w:r></w:p>'
            '<w:p><w:r><w:t>}}!</w:t></w:r></w:p>'
            '</w:body>'
            '</w:document>' % W_NS
        )
        self.mixin._normalize_cross_paragraph_placeholders(tree)
        body = tree.find('{%s}body' % W_NS)
        paras = body.findall('{%s}p' % W_NS)
        self.assertEqual(len(paras), 1)
        self.assertEqual(
            ''.join(t.text or '' for t in paras[0].iter('{%s}t' % W_NS)),
            'Hello {{name}}!',
        )

    def test_normalize_noop_on_complete_placeholder(self):
        # Both paragraphs contain complete placeholders — no merge.
        tree = _xml(
            '<w:document xmlns:w="%s">'
            '<w:body>'
            '<w:p><w:r><w:t>Hi {{name}}</w:t></w:r></w:p>'
            '<w:p><w:r><w:t>Bye {{surname}}</w:t></w:r></w:p>'
            '</w:body>'
            '</w:document>' % W_NS
        )
        self.mixin._normalize_cross_paragraph_placeholders(tree)
        body = tree.find('{%s}body' % W_NS)
        self.assertEqual(len(body.findall('{%s}p' % W_NS)), 2)

    def test_normalize_merges_inside_table_cell(self):
        # The split happens inside a single <w:tc> — must be normalised
        # there as well.
        tree = _xml(
            '<w:document xmlns:w="%s">'
            '<w:body>'
            '<w:tbl>'
            '<w:tr>'
            '<w:tc>'
            '<w:p><w:r><w:t>Code: {{ref</w:t></w:r></w:p>'
            '<w:p><w:r><w:t>}}</w:t></w:r></w:p>'
            '</w:tc>'
            '</w:tr>'
            '</w:tbl>'
            '</w:body>'
            '</w:document>' % W_NS
        )
        self.mixin._normalize_cross_paragraph_placeholders(tree)
        cell = tree.find('.//{%s}tc' % W_NS)
        paras = cell.findall('{%s}p' % W_NS)
        self.assertEqual(len(paras), 1)
        self.assertEqual(
            ''.join(t.text or '' for t in paras[0].iter('{%s}t' % W_NS)),
            'Code: {{ref}}',
        )

    def test_normalize_merges_inside_textbox(self):
        # The split happens inside a <w:txbxContent> (text box).
        tree = _xml(
            '<w:document xmlns:w="%s">'
            '<w:body>'
            '<w:p><w:r><w:t>Container</w:t></w:r></w:p>'
            '<w:txbxContent>'
            '<w:p><w:r><w:t>Title: {{title</w:t></w:r></w:p>'
            '<w:p><w:r><w:t>}}</w:t></w:r></w:p>'
            '</w:txbxContent>'
            '</w:body>'
            '</w:document>' % W_NS
        )
        self.mixin._normalize_cross_paragraph_placeholders(tree)
        tb = tree.find('.//{%s}txbxContent' % W_NS)
        paras = tb.findall('{%s}p' % W_NS)
        self.assertEqual(len(paras), 1)
        self.assertEqual(
            ''.join(t.text or '' for t in paras[0].iter('{%s}t' % W_NS)),
            'Title: {{title}}',
        )

    def test_normalize_does_not_touch_paragraph_with_no_open_brace(self):
        # No '{{' in p1 — should not merge even if p2 has '}}'.
        tree = _xml(
            '<w:document xmlns:w="%s">'
            '<w:body>'
            '<w:p><w:r><w:t>Hello</w:t></w:r></w:p>'
            '<w:p><w:r><w:t>}} world</w:t></w:r></w:p>'
            '</w:body>'
            '</w:document>' % W_NS
        )
        self.mixin._normalize_cross_paragraph_placeholders(tree)
        body = tree.find('{%s}body' % W_NS)
        self.assertEqual(len(body.findall('{%s}p' % W_NS)), 2)
