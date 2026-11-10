# Part of Odoo. See LICENSE file for full copyright and licensing details.

"""Value hints for the model selected on a template.

One resolver, three sources (the first source wins per path):

1. **Declaration** — the target model defines ``_soft_report_value_hints()``
   and returns its own curated list.  A module that already knows which values
   its document needs (possibly with an allow-list) stays the source of truth.
2. **QWeb reports** — ``ir.actions.report`` records of that model, following
   ``t-call`` chains into the document template: "what this module already
   prints".  No declaration needed, and customised views are picked up.
3. **Field types** — syntax examples derived from ``ir.model.fields``: the
   model always has *some* field worth printing.

The result feeds three consumers: the hint box shown while the template is a
draft, the *Available Values* page, and ``field_path`` validation on Activate.

A declared hint may be a plain path string or a dict::

    {'path': 'partner_id.name', 'label': 'Customer', 'kind': 'relation'}

Hints are guidance, not permissions: the DOCX engine still resolves any field
of the model, declared or not.
"""

import logging
import re

from odoo import models

_logger = logging.getLogger(__name__)

_CALL_RE = re.compile(r't-call="([\w.]+)"')
# ``doc.name`` / ``o.name`` / ``record.name`` in a QWeb report
_DOC_FIELD_RE = re.compile(
    r't-(?:field|out|esc|raw|value)="(?:doc|o|record)\.([A-Za-z_][\w.]*)"'
)
_FOREACH_RE = re.compile(
    r't-foreach="(?:doc|o|record)\.([A-Za-z_][\w.]*)"[^>]*?t-as="(\w+)"'
)
_ALIAS_FIELD_RE = re.compile(
    r't-(?:field|out|esc|raw|value)="(\w+)\.([A-Za-z_][\w.]*)"'
)

# Layout templates that never carry the document's own values
_SKIP_CALLS = {'web.html_container', 'web.external_layout', 'web.basic_layout'}

# Fields that read well as the first example of their type
_PREFERRED = ('name', 'reference', 'subject', 'display_name', 'description',
              'comment')
_PREFERRED_RELATIONS = ('partner_id', 'parent_id', 'company_id', 'user_id')

# Technical / mail-thread fields nobody prints in a document.  They used to win
# the "first of its type" picks (`id` as the numeric example, `activity_ids` as
# the loop example), which made the hint list misleading.
_SKIP_PREFIXES = (
    'message_', 'activity_', 'my_activity_', 'website_message_',
    'starred_message_', 'rating_', '__',
)
_SKIP_NAMES = {
    'id', 'display_name', 'create_uid', 'create_date', 'write_uid',
    'write_date', 'sequence',
}
_SKIP_COMODELS = {'mail.message', 'mail.followers', 'mail.activity'}


def _is_noise(name):
    return name in _SKIP_NAMES or name.startswith(_SKIP_PREFIXES)

_RELATIONAL = ('many2one', 'one2many', 'many2many')


class SoftReportValueHintsMixin(models.AbstractModel):
    _name = 'soft.report.template.hints.mixin'
    _description = 'Soft Report Template — Value Hints'

    # ------------------------------------------------------------------
    #  Public API
    # ------------------------------------------------------------------

    def _soft_report_value_hints(self, model_name):
        """Return the value hints of *model_name* as a list of dicts.

        Each hint: ``path``, ``label``, ``placeholder``, ``kind``
        (field / relation / image / html / loop), ``note``, ``comodel`` and —
        for loops — ``children`` (hints relative to the loop item).
        """
        if not model_name or model_name not in self.env:
            return []

        hints = []
        seen = set()
        sources = (
            self._hints_from_declaration(model_name)
            + self._hints_from_reports(model_name)
            + self._hints_from_field_types(model_name)
        )
        for hint in sources:
            key = (hint['path'], hint['kind'])
            if key in seen:
                continue
            seen.add(key)
            hints.append(hint)
        return hints

    def _soft_report_hints_text(self, model_name):
        """Plain-text rendering of the hints, one per line (copy friendly)."""
        lines = []
        for hint in self._soft_report_value_hints(model_name):
            label = hint.get('label') or hint['path']
            note = ' (%s)' % hint['note'] if hint.get('note') else ''
            lines.append('%-44s %s%s' % (hint['placeholder'], label, note))
            for child in hint.get('children') or ():
                lines.append('    %-40s ↳ %s' % (
                    child['placeholder'], child.get('label') or child['path'],
                ))
        if not lines:
            return self.env._('No values found for this model.')
        return '\n'.join(lines)

    def _soft_report_hints_html(self, model_name, limit=8):
        """Small HTML block with generated examples (used by the draft box)."""
        hints = self._soft_report_value_hints(model_name)
        if not hints:
            return ''
        shown = hints[:limit]
        items = ''.join(
            '<li><code>%s</code> <small class="text-muted">%s</small></li>' % (
                hint['placeholder'], hint.get('label') or '',
            )
            for hint in shown
        )
        more = ''
        if len(hints) > len(shown):
            more = ('<p class="mb-0 mt-1"><small class="text-muted">+ %d %s'
                    '</small></p>' % (
                        len(hints) - len(shown),
                        self.env._('more values, see the Available Values tab'),
                    ))
        return (
            '<p class="mb-1"><strong>%s</strong></p><ul class="mb-0">%s</ul>%s'
        ) % (self.env._('Values you can use for this model:'), items, more)

    def _soft_report_unknown_paths(self, model_name, paths):
        """Return the *paths* that cannot be resolved on *model_name*."""
        if not model_name or model_name not in self.env:
            return [path for path in paths if path]
        Model = self.env[model_name]
        unknown = []
        for path in paths:
            current = Model
            valid = bool(path)
            for part in (path or '').split('.'):
                if not valid or current is None:
                    valid = False
                    break
                field = current._fields.get(part)
                if field is None:
                    valid = False
                    break
                if field.type in _RELATIONAL:
                    current = self.env[field.comodel_name]
                else:
                    current = None
            if not valid:
                unknown.append(path)
        return unknown

    # ------------------------------------------------------------------
    #  Source 1 — explicit declaration
    # ------------------------------------------------------------------

    def _hints_from_declaration(self, model_name):
        Model = self.env[model_name]
        if not callable(getattr(type(Model), '_soft_report_value_hints', None)):
            return []
        try:
            raw = Model._soft_report_value_hints()
        except Exception:  # a broken declaration must not kill the form
            _logger.exception(
                'Value hints of %s could not be read', model_name)
            return []
        return [
            hint for hint in (
                self._normalise_hint(model_name, item) for item in raw or ()
            ) if hint
        ]

    def _normalise_hint(self, model_name, item):
        """Accept a declaration dict or a plain ``path`` string."""
        if isinstance(item, str):
            return self._hint_for_path(model_name, item)
        if not isinstance(item, dict) or not item.get('path'):
            return None
        hint = self._hint_for_path(
            model_name, item['path'], kind=item.get('kind'))
        if not hint:
            hint = {
                'path': item['path'],
                'label': item.get('label') or item['path'],
                'kind': item.get('kind') or 'field',
                'note': item.get('note') or '',
                'placeholder': item.get('placeholder') or '{{%s}}' % item['path'],
                'comodel': item.get('comodel'),
            }
        for key in ('label', 'note', 'placeholder'):
            if item.get(key):
                hint[key] = item[key]
        return hint

    # ------------------------------------------------------------------
    #  Source 2 — what the module's own QWeb reports print
    # ------------------------------------------------------------------

    def _hints_from_reports(self, model_name):
        reports = self.env['ir.actions.report'].sudo().search(
            [('model', '=', model_name)])
        if not reports:
            return []

        paths, loops = [], []
        loop_names = []
        for report in reports:
            for arch in self._report_arch_chain(report.report_name):
                loop_alias = {
                    alias: path
                    for path, alias in _FOREACH_RE.findall(arch)
                }
                for alias, sub in _ALIAS_FIELD_RE.findall(arch):
                    loop_path = loop_alias.get(alias)
                    if not loop_path:
                        continue
                    if loop_path not in loop_names:
                        loop_names.append(loop_path)
                        loops.append((loop_path, set()))
                    for entry in loops:
                        if entry[0] == loop_path:
                            entry[1].add(sub)
                for path in _DOC_FIELD_RE.findall(arch):
                    if path not in paths:
                        paths.append(path)

        hints = [
            hint for hint in (
                self._hint_for_path(model_name, path) for path in paths
            ) if hint
        ]
        for path, children in loops:
            hint = self._hint_for_path(model_name, path, kind='loop')
            if not hint:
                continue
            hint['children'] = [
                child for child in (
                    self._hint_for_path(hint.get('comodel'), sub)
                    for sub in sorted(children)
                ) if child
            ]
            hints.append(hint)
        return hints

    def _report_arch_chain(self, key, visited=None, depth=0):
        """Return the arch of *key* plus every template it ``t-call``s."""
        if not key or depth > 5:
            return []
        visited = visited if visited is not None else set()
        if key in visited:
            return []
        visited.add(key)

        view = self.env['ir.ui.view'].sudo().search(
            [('key', '=', key)], limit=1)
        if not view:
            return []
        arch = view.arch or ''
        arches = [arch]
        for called in _CALL_RE.findall(arch):
            if called in _SKIP_CALLS:
                continue
            arches.extend(self._report_arch_chain(called, visited, depth + 1))
        return arches

    # ------------------------------------------------------------------
    #  Source 3 — field types
    # ------------------------------------------------------------------

    def _hints_from_field_types(self, model_name, with_loop=True):
        """Type-driven examples.  ``with_loop=False`` keeps this non-recursive
        (a comodel may point back at the same model, e.g. ``res.partner``
        ``child_ids``)."""
        Model = self.env[model_name]
        fields_all = {
            name: field for name, field in Model._fields.items()
            if not _is_noise(name) and field.type not in (
                'one2many', 'many2many')
        }
        scalar = {
            name: field for name, field in fields_all.items()
            if field.type != 'many2one'
        }

        def score(name, field):
            """Prefer human, stored, readable fields over technical ones."""
            value = 0
            if name in _PREFERRED or name in _PREFERRED_RELATIONS:
                value += 4
            if field.compute:
                value -= 2
            if getattr(field, 'related', None):
                value -= 1
            if getattr(field, 'groups', None):
                value -= 1
            return value

        def pick(*types, pool=None, min_score=1):
            pool = pool if pool is not None else scalar
            best = None
            for index, (name, field) in enumerate(pool.items()):
                if field.type not in types:
                    continue
                key = (score(name, field), -index)
                if best is None or key > best[0]:
                    best = (key, name)
            if best is None or best[0][0] < min_score:
                return None
            return best[1]

        chosen = [
            # a char field always reads as an example, even without a `name`
            pick('char', 'text', 'selection', min_score=0),
            pick('monetary', 'float', 'integer'),
            pick('date', 'datetime'),
            pick('many2one', pool=fields_all),
            # HTML and image examples are worth showing even unnamed
            pick('html', min_score=0),
            pick('binary', min_score=0),
        ]
        hints = [
            hint for hint in (
                self._hint_for_path(model_name, name) for name in chosen if name
            ) if hint
        ]

        # One loop makes the syntax complete; mail-thread collections are never
        # the loop a document wants
        if not with_loop:
            return hints
        loops = []
        for name, field in Model._fields.items():
            if field.type not in ('one2many', 'many2many'):
                continue
            if _is_noise(name) or field.comodel_name in _SKIP_COMODELS:
                continue
            comodel_fields = self.env[field.comodel_name]._fields
            loops.append((2 if 'name' in comodel_fields else 1, name, field))
        if loops:
            loops.sort(key=lambda item: -item[0])
            hint = self._hint_for_path(model_name, loops[0][1], kind='loop')
            if hint:
                hint['children'] = [
                    child for child in self._hints_from_field_types(
                        hint['comodel'], with_loop=False)
                    if child['kind'] != 'loop'
                ][:4]
                hints.append(hint)
        return hints

    # ------------------------------------------------------------------
    #  Builders
    # ------------------------------------------------------------------

    def _hint_for_path(self, model_name, path, kind=None):
        """Build one hint dict for *path* on *model_name* (None if unknown)."""
        if not model_name or model_name not in self.env or not path:
            return None
        current = self.env[model_name]
        field = None
        for part in path.split('.'):
            field = current._fields.get(part) if current is not None else None
            if field is None:
                return None
            if field.type in _RELATIONAL:
                current = self.env[field.comodel_name]

        if field.type in ('one2many', 'many2many'):
            kind = 'loop'
        elif kind == 'loop':
            # a loop marker must point to a collection
            return None
        kind = kind or self._kind_of(field)
        return {
            'path': path,
            'label': field.string or path,
            'kind': kind,
            'note': self._note_of(field),
            'placeholder': self._placeholder_for(path, field, kind),
            'comodel': field.comodel_name,
        }

    @staticmethod
    def _kind_of(field):
        if field.type == 'binary':
            return 'image'
        if field.type == 'html':
            return 'html'
        if field.type in _RELATIONAL:
            return 'relation'
        return 'field'

    @staticmethod
    def _note_of(field):
        notes = []
        if getattr(field, 'compute', None) and not getattr(field, 'related', None):
            notes.append('computed')
        groups = getattr(field, 'groups', None)
        if groups:
            notes.append('%s group required' % groups)
        if field.type == 'binary':
            notes.append('image')
        return ', '.join(notes)

    @staticmethod
    def _placeholder_for(path, field, kind):
        if kind == 'loop':
            return '{{#%s}} … {{/%s}}' % (path, path)
        if kind == 'image':
            return '{{img:%s}}' % path
        if field.type == 'monetary':
            return '{{%s|currency}}' % path
        if field.type in ('date', 'datetime'):
            return '{{%s|date}}' % path
        if field.type == 'many2one':
            return '{{%s.name}}' % path
        return '{{%s}}' % path
