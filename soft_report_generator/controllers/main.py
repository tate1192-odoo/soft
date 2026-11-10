# -*- coding: utf-8 -*-

import base64
import logging

from odoo import http
from odoo.exceptions import AccessError
from odoo.http import request, content_disposition

_logger = logging.getLogger(__name__)

_TEMPLATE_USER_GROUP = 'soft_report_generator.group_soft_report_generator_user'

# Mapping from template_type / output_format to HTTP Content-Type.
# Shared by preview and download routes.
_FORMAT_MIME_MAP = {
    'pdf': 'application/pdf',
    'docx': 'application/vnd.openxmlformats-officedocument'
            '.wordprocessingml.document',
    'html': 'text/html',
    'odt': 'application/vnd.oasis.opendocument.text',
    'rtf': 'application/rtf',
}


class SoftReportGeneratorController(http.Controller):

    @staticmethod
    def _is_template_user():
        """Group gate shared by the routes below.

        ``@http.route(groups=…)`` no longer exists in Odoo 19 (the key is
        dropped from the routing dict), so the check is explicit: a user
        outside the group gets a 404 instead of the ``AccessError`` the http
        layer would turn into a 500 page.
        """
        return request.env.user.has_group(_TEMPLATE_USER_GROUP)

    @http.route(
        '/soft_report_generator/preview/<int:template_id>/<int:record_id>',
        type='http', auth='user',
    )
    def preview_pdf(self, template_id, record_id, **kwargs):
        """Render and return a PDF for inline browser preview."""
        if not self._is_template_user():
            return request.not_found()
        template = request.env['soft.report.template'].browse(template_id)
        if not template.exists():
            return request.not_found()
        template.check_access('read')

        record = request.env[template.model_name].browse(record_id)
        if not record.exists():
            return request.not_found()
        try:
            record.check_access('read')
        except AccessError:
            return request.not_found()

        # Shared with the Preview PDF button, cover page included
        pdf_bytes = template._render_preview_pdf(record)

        filename = '%s - %s.pdf' % (
            template.name, record.display_name or record.id,
        )

        return request.make_response(
            pdf_bytes,
            headers=[
                ('Content-Type', 'application/pdf'),
                ('Content-Disposition',
                 content_disposition(filename, 'inline')),
                ('Content-Length', len(pdf_bytes)),
            ],
        )

    @http.route(
        '/soft_report_generator/download/<int:template_id>/<int:record_id>',
        type='http', auth='user',
    )
    def download_report(self, template_id, record_id, **kwargs):
        """Generate and download the report in its configured output format."""
        if not self._is_template_user():
            return request.not_found()
        template = request.env['soft.report.template'].browse(template_id)
        if not template.exists():
            return request.not_found()
        template.check_access('read')

        record = request.env[template.model_name].browse(record_id)
        if not record.exists():
            return request.not_found()
        try:
            record.check_access('read')
        except AccessError:
            return request.not_found()

        file_bytes = base64.b64decode(template.template_file)
        ctx = template._build_render_context(record)

        if template.template_type == 'docx':
            output = template._render_docx(file_bytes, ctx)
        else:
            return request.not_found()

        if template.output_format not in ('original', False):
            output = template._convert_format(
                output, template.template_type, template.output_format,
            )
            ext = template.output_format
        else:
            ext = template.template_type

        content_type = _FORMAT_MIME_MAP.get(ext, 'application/octet-stream')

        filename = '%s - %s.%s' % (
            template.name, record.display_name or record.id, ext,
        )

        return request.make_response(
            output,
            headers=[
                ('Content-Type', content_type),
                ('Content-Disposition', content_disposition(filename)),
                ('Content-Length', len(output)),
            ],
        )
