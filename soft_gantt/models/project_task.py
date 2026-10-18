# Copyright 2026 - Today Softteknik (<https://www.softteknik.com>)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl.html).
"""Add the start date ``project.task`` is missing on Odoo 19 Community.

The Gantt view draws a bar between two dates, and Odoo 19 Community's
``project.task`` only carries ``date_deadline``: there is no start date to
schedule from. The field added here is plain and optional: it does not change
any task behaviour, it only gives the Gantt something to draw from, and it is
offered on the task form next to the deadline.
"""

from odoo import fields, models


class ProjectTask(models.Model):
    _inherit = 'project.task'

    date_start = fields.Datetime(
        string='Start Date',
        index=True,
        copy=False,
        help="Date the task is planned to start, used by the Gantt view. "
             "Leave empty for a task that is only bound to its deadline.",
    )
