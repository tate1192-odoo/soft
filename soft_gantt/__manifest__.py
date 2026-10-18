{
    'name': 'Soft Gantt',
    'version': '19.0.1.1.0',
    'summary': 'Native Gantt / timeline view for Odoo 19 Community: bars read '
               'their dates from the view itself, search and filters drive the '
               'records, bars can be dragged to reschedule. No Enterprise, no '
               'vendored JavaScript library.',
    'author': 'Softteknik Bilişim',
    'website': 'https://softteknik.com',
    'license': 'AGPL-3',
    'category': 'Productivity/Productivity',
    'depends': [
        'web',
        'project',
    ],
    'data': [
        'views/project_task_gantt_views.xml',
    ],
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
