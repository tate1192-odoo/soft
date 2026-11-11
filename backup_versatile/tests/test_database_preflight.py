"""Pre-flight check on the source database.

``backup.config.database_name`` is a plain stored field.  A configuration
created on one database and then carried over to another (a restored copy, a
staging clone, a test instance) keeps the original name, and every scheduled
run then died inside the dump with a bare
``FATAL: database "x" does not exist`` — *after* the storage providers had been
probed and reported as ready, which reads as if the provider were the problem.

These tests pin the check that replaced it: fail before the dump, and name the
field to fix.
"""

import shutil
import tempfile
import uuid

from odoo.exceptions import UserError
from odoo.tests.common import TransactionCase, tagged


@tagged('backup_versatile', 'standard')
class TestDatabasePreflight(TransactionCase):
    """The source database must exist before anything is dumped."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Provider = cls.env['backup.provider.local']
        cls.Config = cls.env['backup.config']
        cls.Job = cls.env['backup.job']

    def setUp(self):
        super().setUp()
        self.temp_dirs = []

    def tearDown(self):
        for path in self.temp_dirs:
            shutil.rmtree(path, ignore_errors=True)
        super().tearDown()

    # ---------------------------------------------------------------- helpers
    def _provider(self):
        path = tempfile.mkdtemp(prefix='bv_dbpreflight_')
        self.temp_dirs.append(path)
        return self.Provider.create({
            'name': 'Database preflight provider',
            'backup_directory': path,
            'create_subdirectories': False,
            'check_disk_space': True,
            'min_free_space_gb': 0.0001,
        })

    def _config(self, database_name, provider=None):
        return self.Config.create({
            'name': 'Database preflight config',
            'database_name': database_name,
            'backup_format': 'zip',
            'local_provider_ids': [(4, (provider or self._provider()).id)],
        })

    def _job(self, database_name):
        return self.Job.create({
            'config_id': self._config(database_name).id,
            'database_name': database_name,
            'backup_format': 'zip',
        })

    def _missing_name(self):
        name = 'bv_missing_%s' % uuid.uuid4().hex[:8]
        self.env.cr.execute(
            "SELECT 1 FROM pg_database WHERE datname = %s", (name,))
        self.assertFalse(
            self.env.cr.fetchone(), 'scratch database name must be free')
        return name

    # ------------------------------------------------------------- preflight
    def test_missing_database_is_reported_before_the_dump(self):
        missing = self._missing_name()
        config = self._config(missing)

        job = config.with_context(manual_execution=False).create_backup()

        self.assertEqual(job.status, 'error')
        message = job.error_message or ''
        self.assertIn(missing, message)
        self.assertIn('does not exist on this server', message)
        # The message names the field to fix, not just the PostgreSQL error
        self.assertIn('Database Name', message)
        # A carried-over configuration: say which database this instance serves
        self.assertIn(self.env.cr.dbname, message)

        log = job.log_entries or ''
        # The whole point: nothing was dumped and no provider was probed, so
        # the log cannot suggest that storage was the problem
        self.assertNotIn('DUMP DB', log)
        self.assertNotIn('Pre-flight check passed for provider', log)
        self.assertIn('Backup process failed', log)

    def test_configured_database_passes_preflight(self):
        job = self._job(self.env.cr.dbname)

        self.assertTrue(job._preflight_database())
        self.assertIn(
            "Pre-flight check passed for database '%s'" % self.env.cr.dbname,
            job.log_entries or '')

    def test_other_existing_database_is_allowed(self):
        """Backing up a database other than the served one stays supported.

        ``pg_database`` is cluster-wide, so the check asks whether the target
        exists — not whether it is the current database.  ``postgres`` always
        exists and is never the database a test run serves.
        """
        job = self._job('postgres')

        self.assertTrue(job._preflight_database())
        self.assertNotIn(self.env.cr.dbname, job.database_name)

    def test_missing_database_raises_on_direct_call(self):
        job = self._job(self._missing_name())

        with self.assertRaises(UserError):
            job._preflight_database()

    def test_message_survives_error_formatting(self):
        """The actionable message must not be rewritten by _format_backup_error."""
        message = (
            "Database 'uzman_v19' does not exist on this server. This "
            "configuration was created on another database — this instance "
            "serves 'uzman_v19_test_loc'. Update the 'Database Name' field on "
            "the backup configuration.")

        self.assertEqual(
            self.Job._format_backup_error(UserError(message)), message)
