from odoo.tests import HttpCase, tagged


@tagged("post_install", "-at_install")
class TestSoftWebMapContactsTour(HttpCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env["res.partner"].create(
            {
                "name": "Soft Web Map Tour Partner",
                "partner_latitude": 39.9334,
                "partner_longitude": 32.8597,
                "city": "Ankara",
            }
        )

    def test_map_tour(self):
        self.start_tour(
            "/odoo/action-contacts.action_contacts",
            "soft_web_map_contacts_tour",
            login="admin",
        )
