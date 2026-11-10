# Part of Odoo. See LICENSE file for full copyright and licensing details.

"""Shared test base for soft_report_generator.

Provides:
- :class:`SoftReportGeneratorCommon`: TransactionCase with helpers to
  build minimal .docx files in memory and create templates.
- :func:`make_minimal_docx`: build a Word document from a list of
  paragraphs/tables and return raw bytes.
"""

import base64
import zipfile
from io import BytesIO

from lxml import etree

from odoo.tests import TransactionCase


W_NS = 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'
XML_NS = 'http://www.w3.org/XML/1998/namespace'
REL_NS = 'http://schemas.openxmlformats.org/package/2006/relationships'
CT_NS = 'http://schemas.openxmlformats.org/package/2006/content-types'


_DOCX_CONTENT_TYPES = '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="xml" ContentType="application/xml"/>
  <Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>
</Types>'''


_DOCX_PACKAGE_RELS = '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>
</Relationships>'''


def _docx_document_xml(body_xml):
    return f'''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:document xmlns:w="{W_NS}">
  <w:body>
    {body_xml}
  </w:body>
</w:document>'''


def _make_para(text, style=None):
    """Create a <w:p> with one run, optionally styled."""
    pPr = ''
    if style:
        pPr = f'<w:pPr><w:pStyle w:val="{style}"/></w:pPr>'
    safe = (
        text.replace('&', '&amp;')
        .replace('<', '&lt;')
        .replace('>', '&gt;')
    )
    return (
        f'<w:p>{pPr}<w:r><w:t xml:space="preserve">{safe}</w:t></w:r></w:p>'
    )


def _make_table(rows):
    """Build a <w:tbl> from a list-of-list-of-strings grid."""
    out = ['<w:tbl><w:tblGrid></w:tblGrid>']
    for row in rows:
        out.append('<w:tr>')
        for cell in row:
            if isinstance(cell, str):
                content = _make_para(cell)
            else:
                content = ''.join(_make_para(t) for t in cell)
            out.append(f'<w:tc><w:p/></w:tc>'.replace('<w:p/>', content))
        out.append('</w:tr>')
    out.append('</w:tbl>')
    return ''.join(out)


def make_minimal_docx(body_xml):
    """Build a minimal valid .docx file and return bytes.

    :param body_xml: full <w:document><w:body> inner XML
    """
    buf = BytesIO()
    with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as zf:
        zf.writestr('[Content_Types].xml', _DOCX_CONTENT_TYPES)
        zf.writestr('_rels/.rels', _DOCX_PACKAGE_RELS)
        zf.writestr('word/document.xml', _docx_document_xml(body_xml))
    return buf.getvalue()


def make_simple_docx(*paragraphs):
    """Build a .docx from a sequence of paragraph strings."""
    body = ''.join(_make_para(p) for p in paragraphs)
    return make_minimal_docx(body)


def make_docx_with_table(table_rows):
    """Build a .docx containing a single table."""
    return make_minimal_docx(_make_table(table_rows) + _make_para(''))


class SoftReportGeneratorCommon(TransactionCase):
    """Base TransactionCase for soft_report_generator tests."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Template = cls.env['soft.report.template']
        cls.Field = cls.env['soft.report.template.field']

    def _build_template(self, docx_bytes, *, name='Test Template',
                        model_ref='base.model_res_partner',
                        state='draft', field_ids=None,
                        template_filename='test.docx'):
        """Helper to create a template record."""
        vals = {
            'name': name,
            'model_id': self.env.ref(model_ref).id,
            'template_file': base64.b64encode(docx_bytes),
            'template_filename': template_filename,
            'output_format': 'original',
            'state': state,
        }
        if field_ids is not None:
            vals['field_ids'] = field_ids
        return self.Template.create(vals)

    def _make_partner(self, name='Acme Corp'):
        return self.env['res.partner'].create({
            'name': name,
        })

    def _w_t_elements(self, para):
        """Return list of <w:t> texts in a paragraph element."""
        return [t.text or '' for t in para.iter('{%s}t' % W_NS)]
