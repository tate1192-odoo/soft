# Part of Odoo. See LICENSE file for full copyright and licensing details.

"""Tests for HTML <img> URL parsing in DOCX rendering (BUG-5)."""

from odoo.tests import tagged

from odoo.addons.soft_report_generator.tests.common import (
    SoftReportGeneratorCommon,
    make_simple_docx,
)


@tagged('post_install', '-at_install')
class TestImageRendering(SoftReportGeneratorCommon):
    """Verify image URL parsing in inline HTML is robust."""

    def _setup_partner_with_image(self):
        partner = self._make_partner('Image Co')
        # 1x1 transparent PNG header
        png_bytes = (
            b'\x89PNG\r\n\x1a\n'
            b'\x00\x00\x00\rIHDR'
            b'\x00\x00\x00\x01\x00\x00\x00\x01'
            b'\x08\x06\x00\x00\x00\x1f\x15\xc4\x89'
            b'\x00\x00\x00\rIDATx\x9cc\xf8\xff\xff?\x00\x05\xfe\x02\xfe\xa3W\xe0\xd0'
            b'\x00\x00\x00\x00IEND\xaeB`\x82'
        )
        import base64
        partner.write({
            'image_1920': base64.b64encode(png_bytes),
        })
        return partner, png_bytes

    def test_image_data_uri_inline(self):
        import base64
        from lxml import etree
        from odoo.addons.soft_report_generator.models.report_template import W_NS
        png = b'\x89PNG\r\n\x1a\n' + b'\x00' * 50
        b64 = base64.b64encode(png).decode()
        data_uri = 'data:image/png;base64,' + b64
        template = self._build_template(make_simple_docx('x'))
        para = etree.Element('{%s}p' % W_NS)
        images, counter = {}, [1000]
        template._html_img_to_docx(para, data_uri, images, counter)
        self.assertEqual(len(images), 1)

    def test_image_web_image_url_standard(self):
        """Standard /web/image/<model>/<id>/<field> form."""
        partner, png = self._setup_partner_with_image()
        template = self._build_template(make_simple_docx('x'))
        from lxml import etree
        from odoo.addons.soft_report_generator.models.report_template import W_NS
        para = etree.Element('{%s}p' % W_NS)
        images, counter = {}, [1000]
        url = '/web/image/res.partner/%d/image_1920' % partner.id
        template._html_img_to_docx(para, url, images, counter)
        self.assertEqual(len(images), 1)
        rid = next(iter(images))
        self.assertTrue(images[rid][1].startswith(b'\x89PNG'))

    def test_image_web_image_url_with_query(self):
        """URL with ?unique=... query string should still parse."""
        partner, png = self._setup_partner_with_image()
        template = self._build_template(make_simple_docx('x'))
        from lxml import etree
        from odoo.addons.soft_report_generator.models.report_template import W_NS
        para = etree.Element('{%s}p' % W_NS)
        images, counter = {}, [1000]
        url = '/web/image/res.partner/%d/image_1920?unique=abc' % partner.id
        template._html_img_to_docx(para, url, images, counter)
        self.assertEqual(len(images), 1)

    def test_image_web_image_url_with_size(self):
        """URL with size suffix /web/image/<model>/<id>/<field>/<size>."""
        partner, png = self._setup_partner_with_image()
        template = self._build_template(make_simple_docx('x'))
        from lxml import etree
        from odoo.addons.soft_report_generator.models.report_template import W_NS
        para = etree.Element('{%s}p' % W_NS)
        images, counter = {}, [1000]
        url = '/web/image/res.partner/%d/image_1920/200x150' % partner.id
        template._html_img_to_docx(para, url, images, counter)
        self.assertEqual(len(images), 1)

    def test_image_malformed_url_silently_skipped(self):
        template = self._build_template(make_simple_docx('x'))
        from lxml import etree
        from odoo.addons.soft_report_generator.models.report_template import W_NS
        para = etree.Element('{%s}p' % W_NS)
        images, counter = {}, [1000]
        # Garbage URL must not raise
        for bad in [
            '/web/image/garbage',
            '/web/image/res.partner/9999999999/image_1920',  # non-existent
            '/web/image/no_model_here/1/field',
            'http://example.com/foo.png',  # not /web/image
            '',
        ]:
            with self.subTest(bad=bad):
                images.clear()
                template._html_img_to_docx(para, bad, images, counter)
                # Either skipped (no entry) or skipped (no exception)
                self.assertEqual(
                    len(images), 0,
                    'Should not produce image for %r' % bad,
                )
