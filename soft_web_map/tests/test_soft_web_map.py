from odoo.exceptions import ValidationError
from odoo.tests import TransactionCase, tagged

from odoo.addons.soft_web_map.hooks import uninstall_hook


@tagged("post_install", "-at_install")
class TestSoftWebMap(TransactionCase):
    def test_default_view_for_model_without_stored_view(self):
        """A model without a leaflet_map view gets the fallback architecture."""
        result = self.env["res.users"].get_view(view_type="leaflet_map")
        self.assertIn("<leaflet_map", result["arch"])
        self.assertIn('string="User"', result["arch"])

    def test_valid_view_arch_is_accepted(self):
        view = self.env["ir.ui.view"].create(
            {
                "name": "soft_web_map test view",
                "model": "res.partner",
                "type": "leaflet_map",
                "arch": (
                    '<leaflet_map latitude="partner_latitude" '
                    'longitude="partner_longitude">'
                    '<field name="display_name"/>'
                    "</leaflet_map>"
                ),
            }
        )
        self.assertEqual(view.type, "leaflet_map")
        view.unlink()

    def test_invalid_view_arch_is_rejected(self):
        with self.assertRaises(ValidationError):
            self.env["ir.ui.view"].create(
                {
                    "name": "soft_web_map invalid view",
                    "model": "res.partner",
                    "type": "leaflet_map",
                    "arch": "<leaflet_map><bogus/></leaflet_map>",
                }
            )

    def test_uninstall_hook_cleans_window_actions(self):
        Action = self.env["ir.actions.act_window"]
        only_map = Action.create(
            {
                "name": "soft_web_map only action",
                "res_model": "res.partner",
                "view_mode": "leaflet_map",
                "mobile_view_mode": "leaflet_map",
            }
        )
        mixed = Action.create(
            {
                "name": "soft_web_map mixed action",
                "res_model": "res.partner",
                "view_mode": "list,leaflet_map",
                "mobile_view_mode": "kanban,leaflet_map",
            }
        )
        mobile_only = Action.create(
            {
                "name": "soft_web_map mobile only action",
                "res_model": "res.partner",
                "view_mode": "list",
                "mobile_view_mode": "leaflet_map",
            }
        )

        uninstall_hook(self.env)

        self.assertFalse(only_map.exists())
        self.assertEqual(mixed.view_mode, "list")
        self.assertEqual(mixed.mobile_view_mode, "kanban")
        self.assertEqual(mobile_only.mobile_view_mode, "kanban")
