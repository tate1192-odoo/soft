# Part of Odoo. See LICENSE file for full copyright and licensing details.

"""Tests for HTML → DOCX inline rendering and placeholder parsing.

Covers BUG-2 (dead except chain) and BUG-6 (HTML render edge cases).
"""

from lxml import etree

from odoo.tests import tagged

from odoo.addons.soft_report_generator.tests.common import (
    SoftReportGeneratorCommon,
    make_simple_docx,
    W_NS,
)


def _make_para(*runs):
    """Build <w:p> with the given list of text runs."""
    p = etree.Element('{%s}p' % W_NS)
    for txt in runs:
        r = etree.SubElement(p, '{%s}r' % W_NS)
        t = etree.SubElement(r, '{%s}t' % W_NS)
        t.text = txt
        t.set('{http://www.w3.org/XML/1998/namespace}space', 'preserve')
    return p


@tagged('post_install', '-at_install')
class TestHtmlToDocx(SoftReportGeneratorCommon):
    """Verify HTML → DOCX inline conversion is robust."""

    def test_html_to_docx_runs_plain_text(self):
        para = _make_para('{{x}}')
        template = self._build_template(make_simple_docx('x'))
        images, counter = {}, [1000]
        template._html_to_docx_runs(para, 'Hello world', {}, images, counter)
        runs = para.findall('{%s}r' % W_NS)
        self.assertEqual(len(runs), 1)
        self.assertEqual(runs[0].find('{%s}t' % W_NS).text, 'Hello world')

    def test_html_to_docx_runs_bold(self):
        para = _make_para('{{x}}')
        template = self._build_template(make_simple_docx('x'))
        images, counter = {}, [1000]
        template._html_to_docx_runs(
            para, '<b>Bold</b>', {}, images, counter,
        )
        runs = para.findall('{%s}r' % W_NS)
        self.assertEqual(len(runs), 1)
        rpr = runs[0].find('{%s}rPr' % W_NS)
        self.assertIsNotNone(rpr)
        self.assertIsNotNone(rpr.find('{%s}b' % W_NS))

    def test_html_to_docx_runs_malformed_falls_back_to_text(self):
        """BUG-2: malformed HTML must not raise — must produce a plain run."""
        para = _make_para('{{x}}')
        template = self._build_template(make_simple_docx('x'))
        images, counter = {}, [1000]
        # Inputs that are non-empty but unparseable — must fall through
        # to a plain-text run instead of raising.
        malformed_inputs = [
            '<<broken<>>',
            'unclosed <b>tag',
            '<<>>',
            '<<<>>>',
            '<?xml?><<<>>>',
        ]
        for bad in malformed_inputs:
            with self.subTest(bad=bad):
                p = _make_para('{{x}}')
                template._html_to_docx_runs(p, bad, {}, images, counter)
                runs = p.findall('{%s}r' % W_NS)
                self.assertGreaterEqual(
                    len(runs), 1,
                    'No <w:r> produced for %r' % bad,
                )

    def test_html_to_docx_runs_only_control_chars_yields_no_run(self):
        """Pure control chars are sanitized away — paragraph stays clean."""
        template = self._build_template(make_simple_docx('x'))
        images, counter = {}, [1000]
        p = _make_para('{{x}}')
        template._html_to_docx_runs(p, '\x00\x01\x02', {}, images, counter)
        self.assertFalse(p.findall('{%s}r' % W_NS))

    def test_html_to_docx_runs_empty_input(self):
        template = self._build_template(make_simple_docx('x'))
        images, counter = {}, [1000]
        for empty in ('', '   ', None):
            with self.subTest(empty=empty):
                p = _make_para('{{x}}')
                template._html_to_docx_runs(p, empty, {}, images, counter)
                # Empty input must not produce any new run AND must clear
                # the placeholder run the paragraph started with.
                self.assertFalse(
                    p.findall('{%s}r' % W_NS),
                    'Empty HTML should yield zero runs (got: %r)' % empty,
                )

    def test_html_to_docx_runs_italic_underline(self):
        para = _make_para('{{x}}')
        template = self._build_template(make_simple_docx('x'))
        images, counter = {}, [1000]
        template._html_to_docx_runs(
            para, '<i><u>ItalicUnder</u></i>',
            {}, images, counter,
        )
        runs = para.findall('{%s}r' % W_NS)
        rpr = runs[0].find('{%s}rPr' % W_NS)
        self.assertIsNotNone(rpr.find('{%s}i' % W_NS))
        self.assertIsNotNone(rpr.find('{%s}u' % W_NS))

    def test_html_to_docx_runs_br_creates_break(self):
        para = _make_para('{{x}}')
        template = self._build_template(make_simple_docx('x'))
        images, counter = {}, [1000]
        template._html_to_docx_runs(para, 'A<br>B', {}, images, counter)
        runs = para.findall('{%s}r' % W_NS)
        # One run for 'A', one for break, one for 'B'
        self.assertEqual(len(runs), 3)
        self.assertIsNotNone(runs[1].find('{%s}br' % W_NS))

    def test_html_to_docx_runs_unordered_list(self):
        para = _make_para('{{x}}')
        template = self._build_template(make_simple_docx('x'))
        images, counter = {}, [1000]
        template._html_to_docx_runs(
            para, '<ul><li>One</li><li>Two</li></ul>', {}, images, counter,
        )
        runs = para.findall('{%s}r' % W_NS)
        # Each <li> produces bullet+text+br → 2 li = 6 runs minimum
        self.assertGreaterEqual(len(runs), 6)
        # First run of each item should contain bullet char
        texts = [
            r.find('{%s}t' % W_NS).text
            for r in runs if r.find('{%s}t' % W_NS) is not None
        ]
        self.assertTrue(any(t and '\u2022' in t for t in texts))

    def test_html_to_docx_runs_ordered_list_uses_numbers(self):
        para = _make_para('{{x}}')
        template = self._build_template(make_simple_docx('x'))
        images, counter = {}, [1000]
        template._html_to_docx_runs(
            para, '<ol><li>One</li><li>Two</li></ol>', {}, images, counter,
        )
        runs = para.findall('{%s}r' % W_NS)
        texts = [
            r.find('{%s}t' % W_NS).text
            for r in runs if r.find('{%s}t' % W_NS) is not None
        ]
        self.assertTrue(
            any(t and t.strip().startswith('1.') for t in texts),
            'OL should start numbering at 1. Got: %r' % texts,
        )
        self.assertTrue(
            any(t and t.strip().startswith('2.') for t in texts),
            'OL should continue with 2. Got: %r' % texts,
        )

    def test_html_to_docx_runs_paragraph_breaks(self):
        para = _make_para('{{x}}')
        template = self._build_template(make_simple_docx('x'))
        images, counter = {}, [1000]
        template._html_to_docx_runs(
            para, '<p>Para 1</p><p>Para 2</p>', {}, images, counter,
        )
        runs = para.findall('{%s}r' % W_NS)
        # Expect at least 2 breaks between the two paragraphs
        breaks = [r for r in runs if r.find('{%s}br' % W_NS) is not None]
        self.assertGreaterEqual(len(breaks), 2)
