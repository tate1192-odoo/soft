{
    'name': 'Soft Gantt',
    'version': '19.0.1.2.0',
    'summary': 'Native Gantt / timeline view type for Odoo 19 Community: bars '
               'read their dates from the view itself, search and filters drive '
               'the records, bars can be dragged to reschedule. No Enterprise, '
               'no vendored JavaScript library, no business dependency.',
    'author': 'Softteknik Bilişim',
    'website': 'https://softteknik.com',
    'license': 'AGPL-3',
    'category': 'Productivity/Productivity',
    # The view type is generic: it names its own date fields, so it schedules
    # any model without knowing which one. This module must therefore depend on
    # `web` and nothing else: a business dependency (`project`, `mrp`, ...)
    # would make the type unavailable to the models it does not depend on, and
    # would tie a view type to the first model that happened to use it.
    'depends': [
        'web',
    ],
    # The Enterprise Gantt answers the `gantt` view type. Offering both in the
    # same database would give users two buttons for the same screen, so the
    # two modules are never installed together: this is the manifest key
    # `ir.module.module._update_exclusions` reads (the same way `soft_web_map`
    # excludes `web_map`).
    'excludes': [
        'web_gantt',
    ],
    # No `data`: this module ships the view type only, without a view, a field
    # or an action. A module that schedules a model declares its own
    # `<gantt_soft>` view and adds the mode to its action's `view_mode`
    # (`field_operation_gantt` is the reference consumer, see the README).
    'assets': {
        'web.assets_backend': [
            'soft_gantt/static/src/gantt/gantt_soft.scss',
            'soft_gantt/static/src/gantt/gantt_controller.xml',
            'soft_gantt/static/src/gantt/gantt_renderer.xml',
            'soft_gantt/static/src/gantt/gantt_popover.xml',
            'soft_gantt/static/src/gantt/gantt_utils.js',
            'soft_gantt/static/src/gantt/gantt_arch_parser.js',
            'soft_gantt/static/src/gantt/gantt_model.js',
            'soft_gantt/static/src/gantt/gantt_renderer.js',
            'soft_gantt/static/src/gantt/gantt_popover.js',
            'soft_gantt/static/src/gantt/gantt_controller.js',
            'soft_gantt/static/src/gantt/gantt_view.js',
        ],
        # Dark mode is served as the `web.assets_web_dark` bundle, which the
        # server sends only when `ir_http.color_scheme()` is dark (the reader's
        # colour-scheme cookie / user setting, see ica_web_responsive). The
        # bundle includes the light stylesheet and this dark variables file, and
        # the `before` directive places the latter first so its values win over
        # the `!default`s in `gantt_soft.scss`. No media query, no theme
        # attribute.
        'web.assets_web_dark': [
            # Insert the dark variables BEFORE the light stylesheet so their
            # values win over its `!default` assignments: the house
            # variables-override idiom (as ica_web_responsive does for its own).
            ('before', 'soft_gantt/static/src/gantt/gantt_soft.scss',
                       'soft_gantt/static/src/gantt/gantt_soft.dark.scss'),
        ],
        # Test files, run with:
        # --test-tags '/web:WebSuite.test_unit_desktop[@soft_gantt]'
        'web.assets_unit_tests': [
            'soft_gantt/static/tests/**/*',
        ],
    },
    'installable': True,
    'application': False,
    'auto_install': False,
}
