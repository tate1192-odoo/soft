# Part of Odoo. See LICENSE file for full copyright and licensing details.

"""Regression tests for the 2026-11-10 review findings.

Covers the DOCX engine bugs that silently produced wrong output:

* B1 — inline HTML nodes lost the spaces between them ("HelloWorldagain");
* B2 — ``{{#if}}`` blocks inside a ``w:sdt`` content control were ignored;
* B3 — ``{{#if}}`` inside a loop row was evaluated against the parent record;
* B4 — ``{{img:…}}`` inside a loop row printed the parent record's image;
* B5 — header/footer images were declared in the wrong ``.rels`` part;
* B6 — ``<Default>`` content types were appended after ``<Override>``;

plus the model/controller defects O1, O3, O4, O5 and O6.
"""

import base64
import zipfile
from io import BytesIO

from lxml import etree
from markupsafe import Markup

from odoo.exceptions import UserError
from odoo.tests import tagged

from odoo.addons.soft_report_generator.tests.common import (
    CT_NS,
    REL_NS,
    W_NS,
    SoftReportGeneratorCommon,
    _make_para,
    _make_table,
    make_minimal_docx,
    make_simple_docx,
)

DOCX_MAIN_CT = (
    'application/vnd.openxmlformats-officedocument.'
    'wordprocessingml.document.main+xml'
)


def _png_b64(size=(8, 8)):
    """Base64 PNG bytes, as an Odoo binary field expects them."""
    from PIL import Image  # noqa: PLC0415

    buf = BytesIO()
    Image.new('RGB', size, (200, 30, 30)).save(buf, format='PNG')
    return base64.b64encode(buf.getvalue())

_XML_DECL = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'


def _content_types(extra_defaults=('rels', 'xml')):
    defaults = ''.join(
        '<Default Extension="%s" ContentType="application/%s"/>' % (
            ext,
            'vnd.openxmlformats-package.relationships+xml'
            if ext == 'rels' else 'xml',
        )
        for ext in extra_defaults
    )
    return (
        _XML_DECL + '<Types xmlns="%s">%s'
        '<Override PartName="/word/document.xml" ContentType="%s"/></Types>'
    ) % (CT_NS, defaults, DOCX_MAIN_CT)


_PACKAGE_RELS = (
    _XML_DECL + '<Relationships xmlns="%s">'
    '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/'
    'officeDocument/2006/relationships/officeDocument" '
    'Target="word/document.xml"/></Relationships>'
) % REL_NS

_DOCUMENT_RELS = (
    _XML_DECL + '<Relationships xmlns="%s">'
    '<Relationship Id="rId9" Type="http://schemas.openxmlformats.org/'
    'officeDocument/2006/relationships/header" Target="header1.xml"/>'
    '</Relationships>'
) % REL_NS


def _document(body_xml):
    return (
        _XML_DECL + '<w:document xmlns:w="%s"><w:body>%s</w:body>'
        '</w:document>'
    ) % (W_NS, body_xml)


def _package(parts):
    """Build a .docx from an explicit ``{name: bytes/str}`` mapping."""
    buf = BytesIO()
    with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as zf:
        for name, data in parts.items():
            zf.writestr(name, data)
    return buf.getvalue()


@tagged('post_install', '-at_install')
class TestEngineFixes(SoftReportGeneratorCommon):

    # ------------------------------------------------------------------
    #  helpers
    # ------------------------------------------------------------------

    def _render(self, template, context):
        return template._render_docx(
            base64.b64decode(template.template_file), context)

    @staticmethod
    def _part(docx_bytes, name):
        with zipfile.ZipFile(BytesIO(docx_bytes)) as zf:
            return zf.read(name)

    @staticmethod
    def _names(docx_bytes):
        with zipfile.ZipFile(BytesIO(docx_bytes)) as zf:
            return zf.namelist()

    def _text(self, docx_bytes):
        root = etree.fromstring(self._part(docx_bytes, 'word/document.xml'))
        return ''.join(t.text or '' for t in root.iter('{%s}t' % W_NS))

    def _html_text(self, html):
        para = etree.Element('{%s}p' % W_NS)
        template = self._build_template(make_simple_docx('x'))
        template._html_to_docx_runs(para, html, {}, {}, [1000])
        return ''.join(t.text or '' for t in para.iter('{%s}t' % W_NS))

    # ------------------------------------------------------------------
    #  B1 — HTML whitespace
    # ------------------------------------------------------------------

    def test_inline_tags_keep_word_spaces(self):
        self.assertEqual(
            self._html_text('<p>Hello <b>World</b> again</p>'),
            'Hello World again',
        )

    def test_inline_tails_keep_word_spaces(self):
        self.assertEqual(
            self._html_text('Hello <b>World</b> again, <i>ok</i>?'),
            'Hello World again, ok?',
        )

    def test_html_comments_are_not_printed(self):
        self.assertEqual(
            self._html_text('<p>A<!-- internal note -->B</p>'), 'AB',
        )

    def test_html_field_keeps_text_before_it(self):
        """The HTML run builder must not clear the runs already emitted."""
        para = etree.Element('{%s}p' % W_NS)
        for text in ('Sayin AAA, ', '{{note}}', ' ve son'):
            run = etree.SubElement(para, '{%s}r' % W_NS)
            t_el = etree.SubElement(run, '{%s}t' % W_NS)
            t_el.text = text
        template = self._build_template(make_simple_docx('x'))
        template._html_docx_replace(
            para, 'Sayin AAA, {{note}} ve son',
            {}, {}, [1000], {'note': '<b>NOTE</b>'},
        )
        text = ''.join(t.text or '' for t in para.iter('{%s}t' % W_NS))
        self.assertIn('Sayin AAA, ', text)
        self.assertIn('NOTE', text)
        self.assertIn(' ve son', text)

    def test_two_html_fields_are_both_rendered(self):
        para = etree.Element('{%s}p' % W_NS)
        template = self._build_template(make_simple_docx('x'))
        template._html_docx_replace(
            para, '{{h1}} ve {{h2}}', {}, {}, [1000],
            {'h1': '<b>ONE</b>', 'h2': '<i>TWO</i>'},
        )
        text = ''.join(t.text or '' for t in para.iter('{%s}t' % W_NS))
        self.assertIn('ONE', text)
        self.assertIn('TWO', text)

    def test_inline_conditional_inside_table_cell(self):
        """A cell-level inline block must not write a run under w:tr."""
        body = _make_table([
            ['Indirim {{#if flag}}var{{/if}} son'],
        ])
        template = self._build_template(make_minimal_docx(body))
        for flag, expected, unexpected in (
            (True, 'Indirim var son', None),
            (False, 'Indirim  son', 'var'),
        ):
            with self.subTest(flag=flag):
                out = self._render(template, {
                    '__record__': False,
                    '__raw__': {'flag': flag},
                    'flag': flag,
                })
                root = etree.fromstring(
                    self._part(out, 'word/document.xml'))
                row = root.find('.//{%s}tr' % W_NS)
                self.assertEqual(
                    row.findall('{%s}r' % W_NS), [],
                    'w:r directly under w:tr is invalid OOXML',
                )
                text = self._text(out)
                self.assertEqual(text.count(expected), 1)
                if unexpected:
                    self.assertNotIn(unexpected, text)

    def test_split_placeholder_keeps_one_paragraph_property(self):
        body = (
            '<w:p><w:pPr><w:jc w:val="center"/></w:pPr>'
            '<w:r><w:t>{{na</w:t></w:r></w:p>'
            '<w:p><w:pPr><w:jc w:val="right"/></w:pPr>'
            '<w:r><w:t>me}}</w:t></w:r></w:p>'
        )
        template = self._build_template(make_minimal_docx(body))
        out = self._render(template, {
            '__record__': False,
            '__raw__': {'name': 'X'},
            'name': 'X',
        })
        root = etree.fromstring(self._part(out, 'word/document.xml'))
        para = root.find('{%s}body/{%s}p' % (W_NS, W_NS))
        pprs = para.findall('{%s}pPr' % W_NS)
        self.assertEqual(len(pprs), 1)
        self.assertEqual(para[0].tag, '{%s}pPr' % W_NS)
        self.assertEqual(self._text(out), 'X')

    # ------------------------------------------------------------------
    #  B2 — conditionals inside w:sdt
    # ------------------------------------------------------------------

    def test_conditional_inside_content_control(self):
        body = (
            '<w:sdt><w:sdtPr/><w:sdtContent>'
            + _make_para('{{#if hide}}')
            + _make_para('SECRET')
            + _make_para('{{/if}}')
            + '</w:sdtContent></w:sdt>'
            + _make_para('TAIL')
        )
        docx = make_minimal_docx(body)
        template = self._build_template(docx)
        out = self._render(template, {
            '__record__': self._make_partner(),
            '__raw__': {'hide': False},
            'hide': False,
        })
        text = self._text(out)
        self.assertNotIn('SECRET', text)
        self.assertIn('TAIL', text)

    # ------------------------------------------------------------------
    #  B3 — loop-row conditionals
    # ------------------------------------------------------------------

    def test_loop_row_conditional_uses_row_record(self):
        body = _make_table([
            ['{{#lines}}'],
            [['{{#if flag}}', 'VISIBLE {{name}}', '{{/if}}']],
            ['{{/lines}}'],
        ])
        template = self._build_template(make_minimal_docx(body))
        items = [
            {'__raw__': {'flag': True, 'name': 'A'},
             '__record__': False, 'flag': True, 'name': 'A'},
            {'__raw__': {'flag': False, 'name': 'B'},
             '__record__': False, 'flag': False, 'name': 'B'},
        ]
        out = self._render(template, {
            '__loops__': {'lines': items},
            '__raw__': {},
            '__record__': False,
        })
        text = self._text(out)
        self.assertIn('VISIBLE A', text)
        self.assertNotIn('VISIBLE B', text)

    # ------------------------------------------------------------------
    #  B4 — loop-row images
    # ------------------------------------------------------------------

    def test_loop_row_image_uses_row_record(self):
        with_image = self._make_partner('With image')
        with_image.image_1920 = _png_b64()
        without_image = self._make_partner('Without image')

        body = _make_table([
            ['{{#lines}}'],
            [['{{img:image_1920}}', '{{name}}']],
            ['{{/lines}}'],
        ])
        template = self._build_template(make_minimal_docx(body))
        items = [
            {'__raw__': {'name': 'A'}, '__record__': with_image, 'name': 'A'},
            {'__raw__': {'name': 'B'}, '__record__': without_image,
             'name': 'B'},
        ]
        out = self._render(template, {
            '__loops__': {'lines': items},
            '__raw__': {},
            '__record__': without_image,
        })

        root = etree.fromstring(self._part(out, 'word/document.xml'))
        drawings = root.findall('.//{%s}drawing' % W_NS)
        self.assertEqual(len(drawings), 1, 'only the row item with an image')
        media = [n for n in self._names(out) if n.startswith('word/media/')]
        self.assertEqual(len(media), 1)

    # ------------------------------------------------------------------
    #  B5 / B6 — header image relationships, content types order
    # ------------------------------------------------------------------

    def _header_docx(self):
        header = (
            _XML_DECL + '<w:hdr xmlns:w="%s"><w:p><w:r><w:t>'
            '{{img:image_1920}}</w:t></w:r></w:p></w:hdr>'
        ) % W_NS
        return _package({
            '[Content_Types].xml': _content_types(),
            '_rels/.rels': _PACKAGE_RELS,
            'word/document.xml': _document(''),
            'word/header1.xml': header,
            'word/_rels/document.xml.rels': _DOCUMENT_RELS,
        })

    def test_header_image_relationship_is_written(self):
        partner = self._make_partner('Header image')
        partner.image_1920 = _png_b64()
        template = self._build_template(self._header_docx())
        out = self._render(template, {'__record__': partner, '__raw__': {}})

        self.assertIn('word/_rels/header1.xml.rels', self._names(out))
        header_rels = self._part(out, 'word/_rels/header1.xml.rels')
        document_rels = self._part(out, 'word/_rels/document.xml.rels')
        self.assertIn(b'rId1000', header_rels)
        self.assertNotIn(b'rId1000', document_rels)

    def test_content_types_keep_defaults_before_overrides(self):
        partner = self._make_partner('Content types')
        partner.image_1920 = _png_b64()
        template = self._build_template(self._header_docx())
        out = self._render(template, {'__record__': partner, '__raw__': {}})

        root = etree.fromstring(self._part(out, '[Content_Types].xml'))
        tags = [etree.QName(child).localname for child in root]
        first_override = tags.index('Override')
        self.assertTrue(
            all(tag == 'Default' for tag in tags[:first_override]),
            'schema order broken: %s' % tags,
        )
        self.assertIn('png', [
            child.get('Extension') for child in root
            if etree.QName(child).localname == 'Default'
        ])

    # ------------------------------------------------------------------
    #  O1 — the routes carry no unsupported ``groups`` routing key
    # ------------------------------------------------------------------

    def test_routes_do_not_use_groups_kwarg(self):
        from odoo.addons.soft_report_generator.controllers.main import (
            SoftReportGeneratorController,
        )
        for method_name in ('preview_pdf', 'download_report'):
            routing = getattr(
                getattr(SoftReportGeneratorController, method_name),
                'original_routing', {},
            )
            self.assertNotIn('groups', routing, method_name)
            self.assertEqual(routing.get('auth'), 'user', method_name)

    # ------------------------------------------------------------------
    #  O3 — generated print action is restricted to the module group
    # ------------------------------------------------------------------

    def test_generated_action_is_restricted_to_the_group(self):
        template = self._build_template(
            make_simple_docx('{{name}}'),
            field_ids=[(0, 0, {'placeholder': 'name', 'field_path': 'name'})],
            state='ready',
        )
        template.action_activate()
        group = self.env.ref(
            'soft_report_generator.group_soft_report_generator_user')
        self.assertTrue(template.server_action_id)
        self.assertEqual(template.server_action_id.group_ids, group)

    # ------------------------------------------------------------------
    #  O4 — empty template file
    # ------------------------------------------------------------------

    def test_generate_report_without_file_raises_user_error(self):
        template = self.Template.create({
            'name': 'No file',
            'model_id': self.env.ref('base.model_res_partner').id,
        })
        with self.assertRaises(UserError):
            template.generate_report(self._make_partner())

    # ------------------------------------------------------------------
    #  O5 — multi-record write with a new template file
    # ------------------------------------------------------------------

    def test_multi_record_write_with_template_file(self):
        docx = make_simple_docx('{{name}}')
        t1 = self._build_template(docx, name='T1', state='ready')
        t2 = self._build_template(docx, name='T2', state='ready')

        new_file = make_simple_docx('{{name}} v2')
        vals = {'template_file': base64.b64encode(new_file)}
        (t1 | t2).write(vals)

        self.assertEqual(len(t1 | t2), 2, 'no singleton error')
        self.assertEqual(set((t1 | t2).mapped('state')), {'draft'})
        self.assertNotIn('state', vals, 'caller dict must not be mutated')

    # ------------------------------------------------------------------
    #  Inline conditionals and expressions (PR review findings)
    # ------------------------------------------------------------------

    def test_inline_conditional_keeps_paragraph_text(self):
        """``A {{#if x}}yes{{/if}} B`` must not take the paragraph down."""
        template = self._build_template(
            make_simple_docx('X {{#if flag}}YES{{/if}} Y'))
        partner = self._make_partner()

        shown = self._render(template, {
            '__record__': partner, '__raw__': {'flag': True}, 'flag': True})
        hidden = self._render(template, {
            '__record__': partner, '__raw__': {'flag': False}, 'flag': False})

        self.assertIn('X YES Y', ' '.join(self._text(shown).split()))
        self.assertIn('X Y', ' '.join(self._text(hidden).split()))

    def test_inline_conditional_with_else_branch(self):
        template = self._build_template(
            make_simple_docx('VAT {{#if flag}}included{{#else}}excluded{{/if}}.'))
        out = self._render(template, {
            '__record__': self._make_partner(),
            '__raw__': {'flag': False}, 'flag': False})
        self.assertIn('VAT excluded.', ' '.join(self._text(out).split()))

    def test_expression_resolves_model_field_not_in_template(self):
        """``{{=name.upper()}}`` works even without a ``{{name}}`` placeholder."""
        template = self._build_template(make_simple_docx('{{=name.upper()}}'))
        out = self._render(template, {
            '__record__': self._make_partner('Acme'), '__raw__': {}})
        self.assertEqual(self._text(out).strip(), 'ACME')

    def test_condition_resolves_model_field_not_in_template(self):
        template = self._build_template(
            make_simple_docx('{{#if name}}has-name{{/if}}'))
        out = self._render(template, {
            '__record__': self._make_partner('Acme'), '__raw__': {}})
        self.assertIn('has-name', self._text(out))

    # ------------------------------------------------------------------
    #  Loop children — HTML detection and parent fallback
    # ------------------------------------------------------------------

    def test_loop_child_html_field_is_detected(self):
        """``mail.message.body`` is HTML on the loop item's model."""
        partner = self._make_partner()
        partner.message_post(body=Markup('<p>Merhaba <b>dünya</b></p>'))
        body = _make_table([
            ['{{#messages}}'],
            ['{{body}}'],
            ['{{/messages}}'],
        ])
        template = self._build_template(
            make_minimal_docx(body), state='ready',
            field_ids=[
                (0, 0, {
                    'placeholder': 'messages',
                    'field_path': 'message_ids',
                    'is_loop': True,
                }),
                (0, 0, {
                    'placeholder': 'body',
                    'field_path': 'body',
                    'loop_parent': 'messages',
                }),
            ],
        )

        ctx = template._build_render_context(partner)
        self.assertIn(
            'body', ctx['__loops__']['messages'][0]['__html_fields__'],
            'the HTML field of the loop item was printed as literal tags',
        )
        text = self._text(self._render(template, ctx))
        self.assertIn('Merhaba dünya', ' '.join(text.split()))
        self.assertNotIn('<p>', text)
        self.assertNotIn('<b>', text)

    def test_loop_child_parent_only_path_falls_back(self):
        """A parent-only path is read from the parent even without a dot."""
        partner = self._make_partner()
        partner.ref = 'PARENT-REF'
        partner.message_post(body='<p>note</p>')
        body = _make_table([
            ['{{#messages}}'],
            ['{{ref}}'],
            ['{{/messages}}'],
        ])
        template = self._build_template(
            make_minimal_docx(body), state='ready',
            field_ids=[
                (0, 0, {
                    'placeholder': 'messages',
                    'field_path': 'message_ids',
                    'is_loop': True,
                }),
                (0, 0, {
                    'placeholder': 'ref',
                    'field_path': 'ref',
                    'loop_parent': 'messages',
                }),
            ],
        )

        ctx = template._build_render_context(partner)
        self.assertIn('PARENT-REF', self._text(self._render(template, ctx)))

    # ------------------------------------------------------------------
    #  O6 — unmapped placeholders are reported
    # ------------------------------------------------------------------

    def test_unresolved_placeholder_is_logged(self):
        template = self._build_template(make_simple_docx('A {{nope}} B'))
        with self.assertLogs(
            'odoo.addons.soft_report_generator.models.docx_engine',
            level='WARNING',
        ):
            out = self._render(
                template,
                {'__record__': self._make_partner(), '__raw__': {}},
            )
        self.assertIn('A {{nope}} B', self._text(out))
