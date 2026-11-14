# Part of Odoo. See LICENSE file for full copyright and licensing details.

"""PDF conversion + preview mixin.

Provides:

* ``_merge_pdfs`` — merge multiple PDF byte-strings via pypdf/PyPDF2.
* ``action_preview_report`` — generate a PDF preview from the first
  available record and open it in a new tab.
* ``_find_libreoffice`` / ``_get_install_hint`` — locate the LibreOffice
  binary cross-platform.
* ``_convert_to_pdf`` / ``_convert_format`` — convert DOCX bytes to
  PDF/HTML/ODT/RTF using LibreOffice headless mode.
"""

import base64
import logging
import os
import pathlib
import platform
import shutil
import subprocess
import tempfile
from io import BytesIO

from odoo import _, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class PdfConverterMixin(models.AbstractModel):
    """Mixin that adds PDF merge, preview, and LibreOffice conversion."""

    _name = 'soft.report.template.pdf.mixin'
    _description = 'Soft Report Template — PDF Converter Mixin'

    # ==================================================================
    #  PDF MERGE
    # ==================================================================

    def _merge_pdfs(self, pdf_list, skip_invalid=False):
        """Merge a list of PDF byte-strings into a single PDF.

        :param bool skip_invalid: log and skip an input that pypdf cannot read
            instead of failing the whole merge. Used for product documents:
            one encrypted/corrupt attachment must not turn the print into a
            500 page. Generated reports and cover pages pass ``False`` so a
            broken intermediate output is reported as a ``UserError``.
        """
        # Try modern pypdf first, then PyPDF2 (new API), then PyPDF2 (old API)
        PdfReader = PdfWriter = None
        legacy = False

        try:
            from pypdf import PdfReader, PdfWriter  # noqa: PLC0415
        except ImportError:
            try:
                from PyPDF2 import PdfReader, PdfWriter  # noqa: PLC0415
            except ImportError:
                try:
                    from PyPDF2 import PdfFileReader as PdfReader, PdfFileWriter as PdfWriter  # noqa: PLC0415,E501
                    legacy = True
                except ImportError:
                    raise UserError(self.env._(
                        'PDF merge requires the "pypdf" library.\n\n'
                        'Install it with:  pip install pypdf'
                    ))

        writer = PdfWriter()
        for pdf_bytes in pdf_list:
            try:
                reader = PdfReader(BytesIO(pdf_bytes))
                if legacy:
                    for i in range(reader.getNumPages()):
                        writer.addPage(reader.getPage(i))
                else:
                    for page in reader.pages:
                        writer.add_page(page)
            except Exception as exc:
                if skip_invalid:
                    _logger.warning(
                        'Skipping an unreadable PDF while merging: %s', exc)
                    continue
                raise UserError(self.env._(
                    'A PDF could not be read while merging: %(error)s',
                    error=exc,
                )) from exc

        buf = BytesIO()
        writer.write(buf)
        return buf.getvalue()

    def _merge_product_documents(self, record, pdf_bytes):
        """Append the product documents of *record* to ``pdf_bytes``.

        Odoo 19 replaced ``_get_product_documents_pdf()`` (which returned merged
        bytes) with ``_get_product_documents()``, returning ``product.document``
        records; the old ``hasattr()`` hook therefore matched nothing on 19 and
        the documented product-PDF merge silently did nothing. Only real PDF
        attachments are appended, in document order, and the input is returned
        unchanged when the record has none (or the model has no such method).
        """
        getter = getattr(record, '_get_product_documents', None)
        if not getter:
            return pdf_bytes
        try:
            documents = getter()
        except Exception:
            _logger.warning(
                'Product documents of %s could not be read', record, exc_info=True)
            return pdf_bytes

        parts = [pdf_bytes]
        for document in documents:
            if document.type != 'binary' or not document.datas:
                continue
            if not (document.mimetype or '').endswith('pdf'):
                continue
            try:
                data = base64.b64decode(document.datas)
            except Exception:
                continue
            if not data.startswith(b'%PDF'):
                continue
            parts.append(data)
        if len(parts) == 1:
            return pdf_bytes
        return self._merge_pdfs(parts, skip_invalid=True)

    # ==================================================================
    #  PDF PREVIEW
    # ==================================================================
    def _render_preview_pdf(self, record):
        """Render *record* to PDF for preview, cover page included.

        Shared by the ``Preview PDF`` button and the HTTP preview route: the
        two used to diverge (the route silently dropped the cover page).
        """
        self._check_records_match_domain(record)
        if not self.template_file:
            raise UserError(_('Please upload a template file first.'))
        if self.template_type != 'docx':
            raise UserError(_('Unsupported template type.'))

        file_bytes = base64.b64decode(self.template_file)
        ctx = self._build_render_context(record)
        output = self._render_docx(file_bytes, ctx)
        pdf_bytes = self._convert_format(output, self.template_type, 'pdf')

        # Same cover page as the print path, so the preview matches the output
        if self.cover_file:
            cover_bytes = base64.b64decode(self.cover_file)
            cover_output = self._render_docx(cover_bytes, ctx)
            cover_pdf = self._convert_format(cover_output, 'docx', 'pdf')
            pdf_bytes = self._merge_pdfs([cover_pdf, pdf_bytes])
        return pdf_bytes

    def action_preview_report(self):
        """Generate a preview PDF and open it in a new browser tab."""
        self.ensure_one()
        record = self._get_test_record()
        pdf_bytes = self._render_preview_pdf(record)

        attachment = self.env['ir.attachment'].create({
            'name': 'Preview - %s.pdf' % self.name,
            'datas': base64.b64encode(pdf_bytes),
            'res_model': self._name,
            'res_id': self.id,
            'type': 'binary',
        })

        return {
            'type': 'ir.actions.act_url',
            'url': '/web/content/%d?download=false' % attachment.id,
            'target': 'new',
        }

    # ==================================================================
    #  PDF CONVERSION (cross-platform: Linux / macOS / Windows)
    # ==================================================================

    @staticmethod
    def _find_libreoffice():
        """Locate the LibreOffice binary on Linux, macOS, or Windows."""
        system = platform.system()

        if system == 'Linux':
            candidates = [
                'libreoffice',
                '/usr/bin/libreoffice',
                '/usr/lib/libreoffice/program/soffice',
                '/snap/bin/libreoffice',
                'soffice',
            ]
        elif system == 'Darwin':  # macOS
            candidates = [
                '/Applications/LibreOffice.app/Contents/MacOS/soffice',
                'libreoffice',
                'soffice',
            ]
        elif system == 'Windows':
            candidates = [
                r'C:\Program Files\LibreOffice\program\soffice.exe',
                r'C:\Program Files (x86)\LibreOffice\program\soffice.exe',
                'soffice.exe',
                'soffice',
            ]
        else:
            candidates = ['libreoffice', 'soffice']

        for cmd in candidates:
            found = shutil.which(cmd)
            if found:
                return found
            if os.path.isfile(cmd) and os.access(cmd, os.X_OK):
                return cmd

        return None

    def _get_install_hint(self):
        """Return OS-specific install instructions for LibreOffice."""
        system = platform.system()
        if system == 'Linux':
            return (
                'Linux:  sudo apt-get install libreoffice-core\n'
                '   or:  sudo dnf install libreoffice-core\n'
                '   or:  sudo snap install libreoffice'
            )
        if system == 'Darwin':
            return (
                'macOS:  brew install --cask libreoffice\n'
                '   or:  Download from https://www.libreoffice.org/download/'
            )
        if system == 'Windows':
            return (
                'Windows:  Download and install from '
                'https://www.libreoffice.org/download/\n'
                'Make sure soffice.exe is in your PATH or installed in the '
                'default location.'
            )
        return 'Install LibreOffice from https://www.libreoffice.org/download/'

    def _convert_to_pdf(self, file_bytes, source_type):
        """Convert DOCX bytes to PDF. Backward-compatible wrapper."""
        return self._convert_format(file_bytes, source_type, 'pdf')

    def _convert_format(self, file_bytes, source_type, target_format):
        """Convert DOCX bytes to target format via LibreOffice."""
        lo_bin = self._find_libreoffice()
        if not lo_bin:
            raise UserError(self.env._(
                'LibreOffice is not installed on this server.\n\n%s'
            ) % self._get_install_hint())

        tmp_in = tempfile.NamedTemporaryFile(
            suffix='.%s' % source_type, delete=False,
        )
        try:
            tmp_in.write(file_bytes)
            tmp_in.flush()
            tmp_in.close()

            out_dir = tempfile.mkdtemp()
            try:
                # Every conversion gets its own LibreOffice profile. With the
                # default (shared) profile two concurrent conversions make one
                # of them exit with status 1 and an EMPTY stderr - measured
                # 4/4 runs, while a dedicated profile failed 0/4.
                profile_uri = pathlib.Path(
                    os.path.join(out_dir, 'lo_profile')).as_uri()
                cmd = [
                    lo_bin, '-env:UserInstallation=%s' % profile_uri,
                    '--headless', '--norestore',
                    '--convert-to', target_format,
                    '--outdir', out_dir, tmp_in.name,
                ]

                # On Windows, hide the console window
                kwargs = {}
                if platform.system() == 'Windows':
                    si = subprocess.STARTUPINFO()
                    si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                    kwargs['startupinfo'] = si

                try:
                    result = subprocess.run(
                        cmd, capture_output=True, timeout=120, **kwargs,
                    )
                except subprocess.TimeoutExpired:
                    raise UserError(self.env._(
                        'The %(fmt)s conversion timed out after 120 seconds.',
                        fmt=target_format.upper(),
                    ))
                if result.returncode != 0:
                    _logger.error(
                        'LibreOffice conversion failed:\n'
                        'Binary: %s\nOS: %s\nFormat: %s\n'
                        'stdout: %s\nstderr: %s',
                        lo_bin, platform.system(), target_format,
                        result.stdout.decode(errors='replace'),
                        result.stderr.decode(errors='replace'),
                    )
                    output = (
                        result.stderr or result.stdout or b''
                    ).decode(errors='replace').strip()
                    raise UserError(self.env._(
                        '%(fmt)s conversion failed. LibreOffice returned an error.\n'
                        'Binary used: %(binary)s\n'
                        'Output: %(output)s\n\n%(hint)s',
                        fmt=target_format.upper(),
                        binary=lo_bin,
                        output=output or self.env._('<no output>'),
                        hint=self._get_install_hint(),
                    ))

                out_name = (
                    os.path.splitext(os.path.basename(tmp_in.name))[0]
                    + '.%s' % target_format
                )
                out_path = os.path.join(out_dir, out_name)
                if not os.path.isfile(out_path):
                    raise UserError(self.env._(
                        '%(fmt)s conversion completed but output file was not found.\n'
                        'Expected: %(path)s\n\n'
                        'This may happen if LibreOffice is not fully installed.',
                        fmt=target_format.upper(),
                        path=out_path,
                    ))
                with open(out_path, 'rb') as f:
                    return f.read()
            finally:
                shutil.rmtree(out_dir, ignore_errors=True)
        except FileNotFoundError:
            raise UserError(self.env._(
                'LibreOffice binary not found: %(binary)s\n\n%(hint)s',
                binary=lo_bin,
                hint=self._get_install_hint(),
            ))
        finally:
            try:
                os.unlink(tmp_in.name)
            except OSError:
                pass
