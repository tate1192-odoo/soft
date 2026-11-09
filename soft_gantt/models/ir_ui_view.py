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
from odoo.tools.safe_eval import safe_eval

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
    'milestone',
    'dependencies',
    'default_order',
    'default_range',
    'group_by',
    'group_total',
    'group_avatar',
    'collapse_first_level',
    'cell_create',
    'mode',
    'scales',
    'precision',
    'limit',
})

#: Values a boolean arch attribute can carry. The client reads them with
#: ``exprToBoolean``, whose only false strings are ``"0"`` and ``"false"``:
#: ``str2bool`` would also accept ``no``/``off`` as false while the client would
#: read them as true, so only the values both sides read the same way pass.
GANTT_SOFT_BOOLEAN_VALUES = frozenset({'0', '1', 'false', 'true'})

#: Cell unit of each scale: what a column of that scale shows. A ``precision``
#: entry is written ``"<unit>:<full|half|quarter>"`` and must name that unit.
GANTT_SOFT_SCALE_UNITS = {
    'day': 'hour',
    'week': 'day',
    'month': 'day',
    'quarter': 'week',
    'year': 'month',
}

#: Subdivisions a cell can be cut in, with the factors the client uses.
GANTT_SOFT_CELL_PRECISIONS = {'full': 1, 'half': 2, 'quarter': 4}

#: Scales whose cells (hours or days) can be subdivided by ``precision``.
GANTT_SOFT_PRECISION_SCALES = ('day', 'week', 'month')

#: Decorations a bar can carry. The expression next to the name is evaluated on
#: the record, like the ``decoration-*`` attributes of a list view, and the bar
#: draws a ring in that colour.
GANTT_SOFT_DECORATIONS = ('danger', 'info', 'secondary', 'success', 'warning')

#: Arch attribute -> the field types it accepts.
GANTT_SOFT_FIELD_ATTRIBUTES = {
    'date_start': ('date', 'datetime'),
    'date_stop': ('date', 'datetime'),
    # The text on the left of every row: anything a user can read, but not a
    # binary or a relational list the client could not render.
    'label': ('char', 'text', 'selection', 'integer', 'float', 'many2one'),
    'progress': ('float', 'integer'),
    'color': ('integer',),
    # A record flagged by this field is drawn as a milestone (a diamond on its
    # date) instead of a bar.
    'milestone': ('boolean',),
    # The relational list holding the records that must finish before this one:
    # the client draws an arrow from each of them.
    'dependencies': ('many2many', 'one2many'),
    # A numeric field summed over the records of a group and shown on its row.
    'group_total': ('float', 'integer'),
}

#: Field types a ``group_by`` level can name. A name, a team, a status:
#: something with few distinct values. A date is the timeline itself and a
#: float would give one row per value, so both are refused.
GANTT_SOFT_GROUP_BY_TYPES = ('char', 'text', 'selection', 'integer', 'many2one', 'boolean')

#: Attributes a ``<button>`` child can carry. The card offers the buttons in
#: arch order; the label (``string``) and the confirmation text are translatable
#: terms, like on the buttons of the other views.
GANTT_SOFT_BUTTON_ATTRIBUTES = frozenset({
    'name',
    'type',
    'string',
    'icon',
    'confirm',
    'class',
})

#: The kinds of button a Gantt card can offer: call a method on the record, or
#: open an action.
GANTT_SOFT_BUTTON_TYPES = ('object', 'action')

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
GANTT_SOFT_SCALES = ('day', 'week', 'month', 'quarter', 'year')

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

        # Decorations are validated by name only: the expression itself is
        # evaluated on the record by the client, which is also what adds the
        # fields it reads to the view (base's generic attribute processing does
        # that for every `decoration-*` attribute, as it does for list views).
        for attribute in node.attrib:
            if not attribute.startswith('decoration-'):
                continue
            decoration = attribute[len('decoration-'):]
            if decoration not in GANTT_SOFT_DECORATIONS:
                self._raise_view_error(
                    _(
                        "Invalid decoration %(attribute)s in a gantt_soft view. "
                        "Valid decorations are: %(decorations)s",
                        attribute=attribute,
                        decorations=', '.join(
                            f'decoration-{name}' for name in GANTT_SOFT_DECORATIONS
                        ),
                    ),
                    node,
                )
            if not (node.get(attribute) or '').strip():
                self._raise_view_error(
                    _(
                        "The %(attribute)s attribute of a gantt_soft view must "
                        "be an expression.",
                        attribute=attribute,
                    ),
                    node,
                )

        remaining = {
            attribute
            for attribute in node.attrib
            if not attribute.startswith('decoration-')
        } - GANTT_SOFT_VALID_ATTRIBUTES
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

        # ``group_by`` names one or several levels, a comma separated list: the
        # first field makes the outer rows and the last one holds the records.
        group_by_fields = []
        group_by = node.get('group_by')
        if group_by is not None:
            group_by_fields = [name.strip() for name in group_by.split(',') if name.strip()]
            if not group_by_fields:
                self._raise_view_error(
                    _(
                        "The group_by attribute of a gantt_soft view must name at "
                        "least one field."
                    ),
                    node,
                )
            for field_name in group_by_fields:
                field = model_fields.get(field_name)
                if field is None:
                    self._raise_view_error(
                        _(
                            "Unknown field %(field)r used as group_by in a "
                            "gantt_soft view of %(model)s.",
                            field=field_name,
                            model=name_manager.model._name,
                        ),
                        node,
                    )
                elif field.type not in GANTT_SOFT_GROUP_BY_TYPES:
                    self._raise_view_error(
                        _(
                            "Field %(field)r used as group_by in a gantt_soft "
                            "view must be of type %(types)s, not %(type)s.",
                            field=field_name,
                            types='/'.join(GANTT_SOFT_GROUP_BY_TYPES),
                            type=field.type,
                        ),
                        node,
                    )

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

        # The window is read with a domain on the two dates, so a field the ORM
        # cannot filter on would install and then fail when the view is opened.
        # ``store or search`` is exactly what the server advertises as
        # ``searchable`` in ``fields_get``; the client parser checks the same
        # flag for views it builds at runtime.
        self._validate_gantt_soft_searchable_dates(node, model_fields)
        self._validate_gantt_soft_group_avatar(node, model_fields)

        # The dependencies list must point back at the view's own model: an
        # arrow can only join two bars that this view draws.
        dependencies = node.get('dependencies')
        dependencies_field = model_fields.get(dependencies) if dependencies else None
        if dependencies_field and dependencies_field.comodel_name != name_manager.model._name:
            self._raise_view_error(
                _(
                    "Field %(field)r used as dependencies in a gantt_soft view "
                    "must point at %(model)s, not at %(comodel)s.",
                    field=dependencies,
                    model=name_manager.model._name,
                    comodel=dependencies_field.comodel_name,
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

        # The two gestures are booleans: a typo must fail at install time, not
        # silently turn the gesture off the way a falsy reading would.
        for attribute in ('collapse_first_level', 'cell_create'):
            value = node.get(attribute)
            if value is not None and value.strip().lower() not in GANTT_SOFT_BOOLEAN_VALUES:
                self._raise_view_error(
                    _(
                        "The %(attribute)s attribute of a gantt_soft view must "
                        "be a boolean (0, 1, true or false), got %(value)r.",
                        attribute=attribute,
                        value=value,
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

        precision_attribute = node.get('precision')
        if precision_attribute is not None:
            try:
                precision = safe_eval(precision_attribute, {})
            except Exception:  # noqa: BLE001 - any unreadable literal is a view error
                precision = None
            if not isinstance(precision, dict):
                self._raise_view_error(
                    _(
                        "The precision attribute of a gantt_soft view must be a "
                        "dict like {'day': 'hour:quarter'}."
                    ),
                    node,
                )
            for scale, specification in precision.items():
                if scale not in GANTT_SOFT_SCALES:
                    self._raise_view_error(
                        _(
                            "Invalid scale %(scale)r in the precision of a "
                            "gantt_soft view (expected one of %(scales)s).",
                            scale=scale,
                            scales=', '.join(GANTT_SOFT_SCALES),
                        ),
                        node,
                    )
                if scale not in GANTT_SOFT_PRECISION_SCALES:
                    self._raise_view_error(
                        _(
                            "The %(scale)r scale cannot be subdivided: the "
                            "precision attribute is available on %(scales)s.",
                            scale=scale,
                            scales=', '.join(GANTT_SOFT_PRECISION_SCALES),
                        ),
                        node,
                    )
                cell_unit = GANTT_SOFT_SCALE_UNITS[scale]
                unit, separator, precision_name = str(specification).partition(':')
                if (
                    unit != cell_unit
                    or precision_name not in GANTT_SOFT_CELL_PRECISIONS
                ):
                    self._raise_view_error(
                        _(
                            "Invalid precision %(value)r for the %(scale)r scale "
                            "of a gantt_soft view (expected "
                            "%(unit)r:<%(values)s>).",
                            value=specification,
                            scale=scale,
                            unit=cell_unit,
                            values='|'.join(GANTT_SOFT_CELL_PRECISIONS),
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

        # The view accepts two kinds of children: <field> nodes, rendered in the
        # tooltip and the card, and <button> nodes, rendered as actions of the
        # card. Refusing anything else here keeps the client parser from
        # silently ignoring a node the author expected to see.
        for child in node:
            if not isinstance(child.tag, str):
                # An XML comment or processing instruction.
                continue
            if child.tag == 'button':
                self._validate_gantt_soft_button(child, name_manager.model)
                continue
            if child.tag != 'field':
                self._raise_view_error(
                    _(
                        "A gantt_soft view can only contain <field> or <button> "
                        "nodes, got <%(tag)s>.",
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

    def _validate_gantt_soft_button(self, node, model):
        """Validate a ``<button>`` child of a gantt_soft view.

        The card is a read-only surface: a button is a way to act on the record
        without leaving the chart. ``type="object"`` calls a public method on
        the record, ``type="action"`` opens an action; the method is checked at
        install time, because a typo would otherwise be a button that fails
        only when a user clicks it.
        """
        remaining = set(node.attrib) - GANTT_SOFT_BUTTON_ATTRIBUTES
        if remaining:
            self._raise_view_error(
                _(
                    "Invalid attribute(s) %(invalid)s on a <button> of a "
                    "gantt_soft view. Valid attributes are: %(valid)s",
                    invalid=', '.join(sorted(remaining)),
                    valid=', '.join(sorted(GANTT_SOFT_BUTTON_ATTRIBUTES)),
                ),
                node,
            )
        name = (node.get('name') or '').strip()
        if not name:
            self._raise_view_error(
                _("A <button> of a gantt_soft view must name a method or an action."),
                node,
            )
        button_type = node.get('type')
        if button_type not in GANTT_SOFT_BUTTON_TYPES:
            self._raise_view_error(
                _(
                    "The type of a <button> of a gantt_soft view must be one of "
                    "%(types)s, got %(type)r.",
                    types='/'.join(GANTT_SOFT_BUTTON_TYPES),
                    type=button_type,
                ),
                node,
            )
        if not (node.get('string') or node.get('icon')):
            self._raise_view_error(
                _(
                    "A <button> of a gantt_soft view needs a string or an icon: "
                    "the card would draw an empty button otherwise."
                ),
                node,
            )
        if button_type == 'object':
            method = getattr(model, name, None)
            if name.startswith('_') or not callable(method):
                self._raise_view_error(
                    _(
                        "Unknown method %(name)r on %(model)s, used as the type "
                        "object <button> of a gantt_soft view.",
                        name=name,
                        model=model._name,
                    ),
                    node,
                )

    def _validate_gantt_soft_searchable_dates(self, node, model_fields):
        """Refuse a date field the window domain could not be built on.

        The window is read with a domain on ``date_start``/``date_stop``, so a
        field the ORM cannot filter on (a computed field without a search
        method) would install and then fail when the view is opened.
        ``store or search`` is exactly what the server advertises as
        ``searchable`` in ``fields_get``; the client parser checks the same flag
        for views it builds at runtime.
        """
        for attribute in ('date_start', 'date_stop'):
            field_name = node.get(attribute)
            field = model_fields.get(field_name) if field_name else None
            if field is not None and not (field.store or field.search):
                self._raise_view_error(
                    _(
                        "Field %(field)r used as %(attribute)s in a gantt_soft "
                        "view must be stored or searchable: the window is read "
                        "with a domain on it.",
                        field=field_name,
                        attribute=attribute,
                    ),
                    node,
                )

    def _validate_gantt_soft_group_avatar(self, node, model_fields):
        """Refuse a group avatar that cannot be drawn.

        The avatar is shown on a *group* row, so the row must be a many2one and
        the image field must exist on the record it points at: the client only
        has the relation name and builds a ``/web/image`` URL from it, which
        means no field metadata is available client side to check this.
        """
        image_field_name = node.get('group_avatar')
        if not image_field_name:
            return
        group_by_fields = [
            name.strip() for name in (node.get('group_by') or '').split(',') if name.strip()
        ]
        group_by = group_by_fields[0] if group_by_fields else None
        if not group_by:
            self._raise_view_error(
                _(
                    "The group_avatar attribute of a gantt_soft view requires "
                    "the group_by attribute: there is no group row to draw it on."
                ),
                node,
            )
        group_field = model_fields.get(group_by)
        if group_field is None:
            # The group_by attribute check already reported the unknown field.
            return
        if group_field.type != 'many2one':
            self._raise_view_error(
                _(
                    "The group_avatar attribute of a gantt_soft view requires a "
                    "many2one group_by: %(field)r is a %(type)s.",
                    field=group_by,
                    type=group_field.type,
                ),
                node,
            )
        comodel_fields = self.env[group_field.comodel_name]._fields
        image_field = comodel_fields.get(image_field_name)
        if image_field is None:
            self._raise_view_error(
                _(
                    "Unknown field %(field)r on %(comodel)s, used as group_avatar "
                    "in a gantt_soft view.",
                    field=image_field_name,
                    comodel=group_field.comodel_name,
                ),
                node,
            )
        if image_field.type != 'binary':
            self._raise_view_error(
                _(
                    "Field %(field)r on %(comodel)s, used as group_avatar in a "
                    "gantt_soft view, must be a binary image field, not %(type)s.",
                    field=image_field_name,
                    comodel=group_field.comodel_name,
                    type=image_field.type,
                ),
                node,
            )

    def _get_view_info(self):
        return {'gantt_soft': {'icon': 'fa fa-tasks'}} | super()._get_view_info()


class IrActionsActWindowView(models.Model):
    _inherit = 'ir.actions.act_window.view'

    view_mode = fields.Selection(
        selection_add=[('gantt_soft', 'Gantt')],
        ondelete={'gantt_soft': 'cascade'},
    )
