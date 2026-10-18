# Copyright 2026 - Today Softteknik (<https://www.softteknik.com>)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl.html).
"""Register the ``gantt_soft`` view type.

Odoo 19 Community has no Gantt view: the ``gantt`` view type only exists in the
Enterprise add-on ``web_gantt``. This module adds its own view type with the
exact recipe the core uses for its extra view types (see ``web_hierarchy``):

* ``ir.ui.view.type`` gains ``gantt_soft``: ``ir.ui.view.create`` derives the
  type from the arch root tag and validates it against that selection, so a
  ``<gantt_soft>`` arch is accepted as-is;
* ``ir.actions.act_window.view.view_mode`` gains ``gantt_soft``, which is what
  lets the view be listed in an action's ``view_mode``;
* ``_get_view_info`` advertises the view (and its icon) to the view switcher;
* the arch is validated server side, so an unknown field or attribute fails
  when the view is installed instead of when a user opens the screen.

The view type itself is generic: the dates are named by the view's own
``date_start`` / ``date_stop`` attributes, so nothing here is model specific.
"""

from odoo import _, fields, models

#: Attributes accepted on a ``<gantt_soft>`` root node. The bounds are strict
#: on purpose: an attribute that is not implemented must fail loudly rather
#: than be silently ignored by the client.
GANTT_SOFT_VALID_ATTRIBUTES = frozenset({
    '__validate__',          # ir.ui.view implementation detail
    'class',
    'js_class',
    'string',
    'create',
    'edit',
    'delete',
    'duplicate',
    'open_form_view',
    'date_start',
    'date_stop',
    'label',
    'progress',
    'color',
    'default_order',
    'default_range',
    'group_by',
    'mode',
    'scales',
    'limit',
})

#: Arch attribute -> the field types it accepts.
GANTT_SOFT_FIELD_ATTRIBUTES = {
    'date_start': ('date', 'datetime'),
    'date_stop': ('date', 'datetime'),
    # The text on the left of every row: anything a user can read, but not a
    # binary or a relational list the client could not render.
    'label': ('char', 'text', 'selection', 'integer', 'float', 'many2one'),
    'progress': ('float', 'integer'),
    'color': ('integer',),
    # The row a record is drawn on. A name, a team, a status: something with
    # few distinct values. A date is the timeline itself and a float would give
    # one row per value, so both are refused.
    'group_by': ('char', 'text', 'selection', 'integer', 'many2one', 'boolean'),
}

#: Field types a declared ``<field>`` node can render (tooltip and card).
GANTT_SOFT_FIELD_NODE_TYPES = (
    'char',
    'text',
    'selection',
    'integer',
    'float',
    'monetary',
    'many2one',
    'date',
    'datetime',
    'boolean',
)

#: The scales a Gantt timeline can be drawn with.
GANTT_SOFT_SCALES = ('day', 'week', 'month')

#: The calendar units a window can be aligned on. `quarter` and `year` are
#: drawn with month columns, so they cost nothing extra.
GANTT_SOFT_RANGES = ('day', 'week', 'month', 'quarter', 'year')


class IrUiView(models.Model):
    _inherit = 'ir.ui.view'

    type = fields.Selection(
        selection_add=[('gantt_soft', 'Gantt')],
        ondelete={'gantt_soft': 'cascade'},
    )

    def _validate_tag_gantt_soft(self, node, name_manager, node_info):
        """Validate a ``<gantt_soft>`` arch.

        Everything that can be checked without a browser is checked here, so a
        broken view is refused at install/update time with a message that names
        the offending attribute, instead of failing later in the client.
        """
        if not node_info['validate']:
            return

        remaining = set(node.attrib) - GANTT_SOFT_VALID_ATTRIBUTES
        if remaining:
            self._raise_view_error(
                _(
                    "Invalid attribute(s) %(invalid)s in gantt_soft view. "
                    "Valid attributes are: %(valid)s",
                    invalid=', '.join(sorted(remaining)),
                    valid=', '.join(sorted(GANTT_SOFT_VALID_ATTRIBUTES)),
                ),
                node,
            )

        model_fields = name_manager.model._fields
        for attribute, allowed_types in GANTT_SOFT_FIELD_ATTRIBUTES.items():
            field_name = node.get(attribute)
            if not field_name:
                continue
            field = model_fields.get(field_name)
            if field is None:
                self._raise_view_error(
                    _(
                        "Unknown field %(field)r used as %(attribute)s in a "
                        "gantt_soft view of %(model)s.",
                        field=field_name,
                        attribute=attribute,
                        model=name_manager.model._name,
                    ),
                    node,
                )
            elif field.type not in allowed_types:
                self._raise_view_error(
                    _(
                        "Field %(field)r used as %(attribute)s in a gantt_soft "
                        "view must be of type %(types)s, not %(type)s.",
                        field=field_name,
                        attribute=attribute,
                        types='/'.join(allowed_types),
                        type=field.type,
                    ),
                    node,
                )

        for attribute in ('date_start', 'date_stop'):
            if not node.get(attribute):
                self._raise_view_error(
                    _(
                        "The %(attribute)s attribute is required in a "
                        "gantt_soft view.",
                        attribute=attribute,
                    ),
                    node,
                )

        scales = list(GANTT_SOFT_SCALES)
        scales_attribute = node.get('scales')
        if scales_attribute is not None:
            scales = [scale.strip() for scale in scales_attribute.split(',') if scale.strip()]
            if not scales:
                self._raise_view_error(
                    _(
                        "The scales attribute of a gantt_soft view must list at "
                        "least one of: %(scales)s",
                        scales=', '.join(GANTT_SOFT_SCALES),
                    ),
                    node,
                )
            invalid = [scale for scale in scales if scale not in GANTT_SOFT_SCALES]
            if invalid:
                self._raise_view_error(
                    _(
                        "Invalid scale(s) %(invalid)s in gantt_soft view. Valid "
                        "scales are: %(scales)s",
                        invalid=', '.join(invalid),
                        scales=', '.join(GANTT_SOFT_SCALES),
                    ),
                    node,
                )
            # Keep the declared order, drop duplicates.
            scales = list(dict.fromkeys(scales))

        mode = node.get('mode')
        if mode and mode not in scales:
            self._raise_view_error(
                _(
                    "Invalid mode %(mode)r in gantt_soft view. It must be one of "
                    "the view's scales: %(scales)s",
                    mode=mode,
                    scales=', '.join(scales),
                ),
                node,
            )

        default_range = node.get('default_range')
        if default_range and default_range not in GANTT_SOFT_RANGES:
            self._raise_view_error(
                _(
                    "Invalid default_range %(range)r in gantt_soft view. Valid "
                    "ranges are: %(ranges)s",
                    range=default_range,
                    ranges=', '.join(GANTT_SOFT_RANGES),
                ),
                node,
            )

        limit = node.get('limit')
        if limit:
            try:
                parsed_limit = int(limit)
            except (TypeError, ValueError):
                parsed_limit = 0
            if parsed_limit <= 0:
                self._raise_view_error(
                    _(
                        "The limit of a gantt_soft view must be a positive "
                        "integer, got %(limit)r.",
                        limit=limit,
                    ),
                    node,
                )

        # Only <field> children are rendered. Refusing anything else here keeps
        # the client parser from silently ignoring a node the author expected
        # to see, and a declared field must be a value the tooltip can read.
        for child in node:
            if not isinstance(child.tag, str):
                # An XML comment or processing instruction.
                continue
            if child.tag != 'field':
                self._raise_view_error(
                    _(
                        "A gantt_soft view can only contain <field> nodes, "
                        "got <%(tag)s>.",
                        tag=child.tag,
                    ),
                    child,
                )
            field = model_fields.get(child.get('name'))
            if field is not None and field.type not in GANTT_SOFT_FIELD_NODE_TYPES:
                self._raise_view_error(
                    _(
                        "Field %(field)r of type %(type)s cannot be declared in a "
                        "gantt_soft view.",
                        field=child.get('name'),
                        type=field.type,
                    ),
                    child,
                )

    def _get_view_info(self):
        return {'gantt_soft': {'icon': 'fa fa-tasks'}} | super()._get_view_info()


class IrActionsActWindowView(models.Model):
    _inherit = 'ir.actions.act_window.view'

    view_mode = fields.Selection(
        selection_add=[('gantt_soft', 'Gantt')],
        ondelete={'gantt_soft': 'cascade'},
    )
