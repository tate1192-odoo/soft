# -*- coding: utf-8 -*-

import os
import datetime
import glob
import re
import subprocess
import tempfile
import time
import json
import shutil
import zipfile
import logging

try:
    import odoo.release
    import odoo.sql_db
except ImportError:
    pass

from odoo import models, fields, api, tools
from odoo.exceptions import UserError, AccessDenied
from odoo.tools.misc import exec_pg_environ, find_pg_tool

_logger = logging.getLogger(__name__)

# Optional: cryptography for AES-256-GCM encryption
try:
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    CRYPTOGRAPHY_AVAILABLE = True
except ImportError:
    AESGCM = None
    CRYPTOGRAPHY_AVAILABLE = False


class BackupJob(models.Model):
    """
    Backup job model representing individual backup executions.
    
    This model tracks the execution of backup operations, including
    progress, results, and detailed logging.
    """
    _name = 'backup.job'
    _description = 'Backup Job'
    _order = 'start_time desc, id desc'
    _rec_name = 'display_name'
    
    # Basic information
    config_id = fields.Many2one(
        'backup.config',
        string='Backup Configuration',
        required=True,
        ondelete='cascade'
    )
    database_name = fields.Char(
        string='Database Name',
        required=True,
        help='Name of the database being backed up'
    )
    backup_format = fields.Selection([
        ('zip', 'ZIP Archive'),
        ('dump', 'PostgreSQL Dump'),
    ], string='Backup Format', required=True)
    is_manual = fields.Boolean(
        string='Manual Backup',
        default=False,
        help='True if this backup was triggered manually by a user'
    )
    
    # Status and timing
    status = fields.Selection([
        ('pending', 'Pending'),
        ('running', 'Running'),
        ('success', 'Success'),
        ('warning', 'Warning'),
        ('error', 'Error'),
    ], string='Status', required=True, default='pending')
    start_time = fields.Datetime(
        string='Start Time',
        required=True,
        default=fields.Datetime.now
    )
    end_time = fields.Datetime(
        string='End Time'
    )
    duration = fields.Float(
        string='Duration (seconds)',
        compute='_compute_duration',
        store=True,
        help='Total backup duration in seconds'
    )
    duration_human = fields.Char(
        string='Duration',
        compute='_compute_duration_human',
        help='Total backup duration in a human-readable format (e.g. "1h 2m 15s")'
    )

    # File information
    backup_filename = fields.Char(
        string='Backup Filename',
        help='Name of the generated backup file'
    )
    backup_size_mb = fields.Float(
        string='Backup Size (MB)',
        digits=(20, 6),
        help='Size of the backup file in megabytes (with sub-MB precision)'
    )
    backup_size_human = fields.Char(
        string='Backup Size',
        compute='_compute_backup_size_human',
        help='Human-readable backup file size'
    )
    
    # Results and logging
    backup_details = fields.Text(
        string='Backup Details',
        help='Detailed information about the backup process'
    )
    error_message = fields.Text(
        string='Error Message',
        help='Error message if backup failed'
    )
    log_entries = fields.Text(
        string='Log Entries',
        help='Detailed log of backup process'
    )
    
    # Provider results
    provider_results = fields.Text(
        string='Provider Results',
        help='JSON-encoded results from storage providers'
    )
    
    # Verification
    verification_status = fields.Selection([
        ('not_verified', 'Not Verified'),
        ('verified', 'Verified'),
        ('failed', 'Verification Failed'),
    ], string='Verification Status', default='not_verified')
    verification_details = fields.Text(
        string='Verification Details'
    )
    
    # Computed fields
    display_name = fields.Char(
        string='Display Name',
        compute='_compute_display_name',
        store=True
    )
    
    @api.depends('config_id.name', 'start_time', 'status')
    def _compute_display_name(self):
        """Compute display name for backup job."""
        for record in self:
            if record.config_id and record.start_time:
                record.display_name = f"{record.config_id.name} - {record.start_time.strftime('%Y-%m-%d %H:%M')}"
            else:
                record.display_name = f"Backup Job #{record.id}"
    
    @api.depends('start_time', 'end_time')
    def _compute_duration(self):
        """Compute backup duration."""
        for record in self:
            if record.start_time and record.end_time:
                delta = record.end_time - record.start_time
                record.duration = delta.total_seconds()
            else:
                record.duration = 0.0

    @api.depends('duration')
    def _compute_duration_human(self):
        """Format duration as a compact human-readable string (e.g. "1h 2m 15s")."""
        for record in self:
            total = int(record.duration or 0)
            if total <= 0:
                record.duration_human = '—'
                continue
            hours, remainder = divmod(total, 3600)
            minutes, seconds = divmod(remainder, 60)
            parts = []
            if hours:
                parts.append(f"{hours}h")
            if minutes:
                parts.append(f"{minutes}m")
            if seconds or not parts:
                parts.append(f"{seconds}s")
            record.duration_human = ' '.join(parts)

    @api.depends('backup_size_mb')
    def _compute_backup_size_human(self):
        """Compute human-readable backup size (auto-scales to KB / MB / GB)."""
        for record in self:
            if record.backup_size_mb and record.backup_size_mb > 0:
                size_bytes = int(record.backup_size_mb * 1024 * 1024)
                record.backup_size_human = tools.human_size(size_bytes) or ''
            else:
                record.backup_size_human = ''
    
    # Prefixes used for every temp dir this module creates under /tmp. The
    # safety sweep keys off these to avoid touching anything else.
    _TEMP_DIR_PREFIXES = ('odoo_backup_', 'odoo_backup_dump_', 'backup_restore_')

    # Marker file written inside every temp dir with the creating process
    # PID, so the stale sweep can tell an in-progress backup (owner process
    # alive) from the leftover of a killed worker (owner process gone).
    _TEMP_OWNER_MARKER = '.odoo_backup_owner'

    def _process_backup(self):
        """
        Process the backup job.

        This is the main method that orchestrates the entire backup process.
        Owns the lifecycle of the temporary directory end-to-end so the outer
        finally block can always clean it up, no matter where (or how) a
        nested step fails.
        """
        self.ensure_one()

        # Safety net: remove leftover temp dirs from previous runs that were
        # killed (SIGKILL/OOM/restart) before their own finally could run.
        # Runs before we allocate this run's temp dir so a wedged /tmp from
        # an earlier failure gets a chance to free space.
        self._cleanup_stale_temp_files()

        self._log("Starting backup process")

        # Durability: commit the freshly created job row now. Everything below
        # can run for many minutes inside this transaction; if the worker dies
        # mid-backup the row (and later the watchdog below) must still exist.
        self._commit_progress()

        # Generate backup filename (no I/O, safe before mkdtemp)
        self.backup_filename = self._generate_backup_filename()

        # Allocate the temp dir up front so the outer finally always owns it.
        # Previously this was created inside _create_backup_file, so if that
        # method raised before returning, the outer finally saw temp_dir=None
        # and only the inner except (with ignore_errors=True) ran — silently
        # swallowing any cleanup failure.
        temp_dir = tempfile.mkdtemp(prefix='odoo_backup_')
        self._mark_temp_dir_owner(temp_dir)
        try:
            # Fail fast if the configured database is not even on this server
            # (a configuration carried over from another database keeps the
            # original name), then if a provider cannot receive the file.
            # Dumping first and only then discovering a missing source database
            # or an unwritable directory wastes minutes and gigabytes.
            self._preflight_database()
            self._preflight_providers()

            # Create backup file inside our temp dir
            backup_file_path = self._create_backup_file(temp_dir)

            # Get backup file size and store as MB with sub-MB precision (Float)
            size_bytes = os.path.getsize(backup_file_path)
            self.backup_size_mb = size_bytes / (1024 * 1024)
            self._log(f"Backup file created: {backup_file_path} ({tools.human_size(size_bytes)})")

            # Verify backup integrity if enabled
            if self.config_id.verify_backups:
                self._verify_backup_integrity(backup_file_path)

            # Upload to storage providers
            provider_results = self._upload_to_providers(backup_file_path)
            self.provider_results = self._serialize_provider_results(provider_results)

            # Determine final status
            successful_uploads = sum(1 for r in provider_results.values() if r.get('success'))
            total_providers = len(self.config_id.all_providers)

            if successful_uploads == 0:
                # All uploads failed
                self.status = 'error'
                self.error_message = "All storage provider uploads failed"
                success = False
            elif successful_uploads < total_providers:
                # Some uploads failed
                self.status = 'warning'
                self.error_message = f"Only {successful_uploads}/{total_providers} provider uploads succeeded"
                success = True  # Partial success
            else:
                # All uploads succeeded
                self.status = 'success'
                success = True

            self.end_time = fields.Datetime.now()
            self._log(f"Backup process completed with status: {self.status}")
            self._commit_progress()

            return {
                'success': success,
                'message': self.error_message or 'Backup completed successfully',
                'backup_job': self,
                'provider_results': provider_results
            }
        except Exception as e:
            error_message = self._format_backup_error(e)
            self.status = 'error'
            self.end_time = fields.Datetime.now()
            self.error_message = error_message
            self._log(f"Backup process failed: {error_message}")
            self._commit_progress()

            return {
                'success': False,
                'message': error_message,
                'backup_job': self
            }
        finally:
            # Always clean up the temporary directory and its contents.
            # Uses _safe_rmtree so a failure to remove is logged (not silently
            # swallowed by ignore_errors=True) but never masks the original
            # exception by re-raising.
            self._safe_rmtree(temp_dir, label='backup temp dir')

    def _commit_progress(self):
        """Commit the job row so progress survives a killed worker.

        The whole backup runs in a single transaction; without an explicit
        commit a SIGKILL (cron ``limit_time_cpu``, OOM killer, service
        restart) rolls the job record back and the attempt becomes invisible:
        no row in the UI and no failure e-mail.
        """
        # Skipped in test mode (TransactionCase depends on the rollback).
        # Everything is inside the try so that even a broken flag lookup can
        # never take a backup down with it.
        try:
            if tools.config['test_enable']:
                return
            self.env.cr.commit()
        except Exception as e:  # a failed commit must never kill the backup
            _logger.warning("Could not commit backup job progress: %s", e)
    
    def _generate_backup_filename(self):
        """Generate backup filename based on template."""
        template = self.config_id.backup_name_template or '{database}_{timestamp}.{format}'
        
        # Prepare template variables
        timestamp = datetime.datetime.now().strftime('%Y_%m_%d_%H_%M_%S')
        variables = {
            'database': self.database_name,
            'timestamp': timestamp,
            'format': self.backup_format,
            'config': self.config_id.name,
        }
        
        # Replace variables in template
        filename = template.format(**variables)
        
        # Sanitize filename
        filename = self._sanitize_filename(filename)
        
        return filename
    
    def _sanitize_filename(self, filename):
        """Sanitize filename to be safe for all filesystems."""
        # Remove or replace invalid characters
        filename = re.sub(r'[<>:"/\\|?*]', '_', filename)
        # Remove multiple consecutive underscores
        filename = re.sub(r'_+', '_', filename)
        # Trim underscores from ends
        filename = filename.strip('_')
        return filename
    
    def _create_backup_file(self, temp_dir):
        """Create the actual backup file inside `temp_dir`.

        The caller owns `temp_dir` and is responsible for its cleanup (see
        _process_backup), so this method does not create or remove it.
        """
        self._log(f"Creating {self.backup_format.upper()} backup of database: {self.database_name}")

        backup_file_path = os.path.join(temp_dir, self.backup_filename)
        try:
            with open(backup_file_path, 'wb') as backup_file:
                self._create_database_dump(backup_file)

            self._log(f"Backup file created successfully: {backup_file_path}")
            return backup_file_path
        except Exception as e:
            raise UserError(f"Failed to create backup file: {self._format_backup_error(e)}")

    @staticmethod
    def _format_backup_error(e):
        """Produce a concise, human-readable message for backup errors.

        `shutil.copytree` raises `shutil.Error` with a list of per-file
        (src, dst, why) tuples — stringifying it dumps the whole list into
        the email body. Detect common root causes (disk full, permissions)
        and fall back to a length-capped string for everything else.
        """
        msg = str(e)
        # Messages we raise ourselves (e.g. the provider pre-flight check) are
        # already written for the operator and name the field to fix; never
        # rewrite them into a generic hint.
        if isinstance(e, UserError):
            max_len = 500
            return msg if len(msg) <= max_len else msg[:max_len] + ' … (message truncated)'
        if 'No space left on device' in msg or 'Errno 28' in msg:
            return ("No space left on device while writing temporary files. "
                    "Free up disk space (typically on /tmp) and retry.")
        if 'Permission denied' in msg or 'Errno 13' in msg:
            return ("Permission denied while writing temporary files. "
                    "Check that the Odoo user can write to /tmp and to the "
                    "configured local backup paths.")
        # Generic fallback: cap length so the email stays readable
        max_len = 500
        if len(msg) > max_len:
            return msg[:max_len] + ' … (message truncated)'
        return msg
    
    def _create_database_dump(self, stream):
        """
        Create database dump.

        Uses an internal dump implementation that replicates Odoo's
        ``odoo.service.db.dump_db`` logic without the
        ``@check_db_management_enabled`` decorator.  This allows backups
        to work even when ``list_db = False`` is set in odoo.conf.

        Security note: because this bypasses ``@check_db_management_enabled``,
        a full database dump can be produced even when the administrator has
        disabled web database management via ``list_db = False``. Authorization
        is therefore enforced here against backup-admin group membership (see
        the check below) rather than relying on Odoo's db-management gate.
        """
        # Authorization check: a database dump is a full export of the data and
        # must be restricted to the backup system (cron) or a backup
        # administrator. We verify group membership explicitly here instead of
        # trusting ``is_manual``, which is a caller-controlled context flag
        # (defaults to True) and provides no real authorization. ``is_manual``
        # is kept purely as audit metadata on the job.
        cron_user = self.env.ref('backup_versatile.backup_cron').user_id
        is_cron_user = self.env.user.id == cron_user.id
        is_backup_admin = self.env.user.has_group('backup_versatile.group_backup_admin')

        if not is_cron_user and not is_backup_admin:
            raise AccessDenied("Database dumps require backup administrator rights")

        self._log(f"Creating {self.backup_format} dump of database: {self.database_name}")

        try:
            self._dump_db(self.database_name, stream, self.backup_format)
            self._log("Database dump created successfully")
        except Exception as e:
            self._log(f"Database dump failed: {str(e)}")
            raise UserError(f"Database backup failed: {str(e)}")

    # ------------------------------------------------------------------
    # Internal dump helpers (mirror odoo.service.db without decorator)
    # ------------------------------------------------------------------

    def _dump_db_manifest(self, cr):
        """Generate the manifest dict for a ZIP backup.

        Replicates ``odoo.service.db.dump_db_manifest`` so that we are
        not affected by the ``@check_db_management_enabled`` decorator.
        """
        pg_version = "%d.%d" % divmod(cr._obj.connection.server_version / 100, 100)
        cr.execute("SELECT name, latest_version FROM ir_module_module WHERE state = 'installed'")
        modules = dict(cr.fetchall())
        return {
            'odoo_dump': '1',
            'db_name': cr.dbname,
            'version': odoo.release.version,
            'version_info': odoo.release.version_info,
            'major_version': odoo.release.major_version,
            'pg_version': pg_version,
            'modules': modules,
        }

    def _dump_db(self, db_name, stream, backup_format='zip'):
        """Dump *db_name* into the file-like *stream*.

        This is a faithful copy of ``odoo.service.db.dump_db`` **without**
        the ``@check_db_management_enabled`` decorator so that backups
        work regardless of the ``list_db`` setting.
        """
        _logger.info(
            'DUMP DB: %s format %s with filestore', db_name, backup_format,
        )

        cmd = [find_pg_tool('pg_dump'), '--no-owner', db_name]
        env = exec_pg_environ()

        if backup_format == 'zip':
            # Manual mkdtemp + try/finally instead of `with TemporaryDirectory()`:
            # if rmtree fails (e.g. disk full mid-write leaves partial state),
            # TemporaryDirectory.__exit__ swallows the rmtree error and leaks
            # the directory under /tmp. _safe_rmtree logs the failure reason,
            # then retries with ignore_errors so we still clean up what we can.
            #
            # The temp dir holds only dump.sql + manifest.json (small). The
            # filestore is streamed straight into the archive from its live
            # location by _write_backup_zip — we do NOT copy it here first.
            # Odoo's stock dump_db copies the filestore into the temp dir before
            # zipping, which makes it exist twice on disk at peak (a full copy
            # under /tmp *and* inside the growing zip). On a shared/contended
            # disk that doubled footprint is exactly what runs /tmp out of space.
            dump_dir = tempfile.mkdtemp(prefix='odoo_backup_dump_')
            self._mark_temp_dir_owner(dump_dir)
            try:
                # Generate manifest
                with open(os.path.join(dump_dir, 'manifest.json'), 'w') as fh:
                    db = odoo.sql_db.db_connect(db_name)
                    with db.cursor() as cr:
                        json.dump(self._dump_db_manifest(cr), fh, indent=4)

                # Run pg_dump -> dump.sql (kept in the temp dir)
                cmd.insert(-1, '--file=' + os.path.join(dump_dir, 'dump.sql'))
                subprocess.run(
                    cmd, env=env,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.STDOUT,
                    check=True,
                )

                # Build the zip directly into the output stream
                self._write_backup_zip(stream, dump_dir, db_name)
            finally:
                self._safe_rmtree(dump_dir, label='dump_dir')
        else:
            cmd.insert(-1, '--format=c')
            # check=True: a pg_dump failure must not be silently dumped as an
            # empty/invalid file that then passes as a "successful" backup.
            result = subprocess.run(
                cmd, env=env,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=True,
            )
            stream.write(result.stdout)

    def _write_backup_zip(self, stream, dump_dir, db_name):
        """Write a restore-compatible backup zip into *stream*.

        Layout matches Odoo's ``dump_db`` exactly so the archive restores
        through the standard path: ``dump.sql`` first (so a restore can read it
        without scanning the whole archive — the ordering Odoo's ``fnct_sort``
        guarantees), then ``manifest.json``, then the filestore under
        ``filestore/``. Unlike ``dump_db`` the filestore is read from its live
        location instead of a temp copy.

        Compression strategy: dump.sql and manifest.json are DEFLATEd (text,
        compresses well). Filestore entries are STOREd: attachments are
        already-compressed binaries (images, PDFs, ...) where DEFLATE costs a
        lot of CPU for negligible size gain — enough that on a large filestore
        the cron worker burns through its ``limit_time_cpu`` (default 600s)
        mid-archive and gets SIGKILL'd before any commit, leaving no job
        record and no failure email. zipfile reads both methods transparently
        on restore, so this is purely a cost-side change.

        allowZip64 is mandatory: real filestores routinely exceed the 4 GiB
        ZIP32 limit.
        """
        filestore = odoo.tools.config.filestore(db_name)
        with zipfile.ZipFile(
            stream, 'w', compression=zipfile.ZIP_STORED, allowZip64=True,
        ) as zf:
            zf.write(
                os.path.join(dump_dir, 'dump.sql'), 'dump.sql',
                compress_type=zipfile.ZIP_DEFLATED,
            )
            zf.write(
                os.path.join(dump_dir, 'manifest.json'), 'manifest.json',
                compress_type=zipfile.ZIP_DEFLATED,
            )
            if not os.path.exists(filestore):
                return
            for dirpath, _dirnames, filenames in os.walk(filestore):
                for fname in filenames:
                    fpath = os.path.join(dirpath, fname)
                    arcname = os.path.join(
                        'filestore', os.path.relpath(fpath, filestore),
                    )
                    try:
                        zf.write(fpath, arcname)
                    except FileNotFoundError:
                        # The attachment was unlinked (gc/vacuum) between
                        # os.walk listing it and us reading it. It is no longer
                        # referenced, so skipping keeps the archive consistent
                        # with the freshly dumped database.
                        _logger.warning(
                            "Skipping filestore file removed mid-backup: %s",
                            fpath,
                        )
    
    def _verify_backup_integrity(self, backup_file_path):
        """Verify backup file integrity."""
        self._log("Verifying backup integrity")
        
        try:
            # Basic file checks
            if not os.path.exists(backup_file_path):
                raise UserError("Backup file does not exist")
            
            file_size = os.path.getsize(backup_file_path)
            if file_size == 0:
                raise UserError("Backup file is empty")
            
            # Format-specific verification
            if self.backup_format == 'zip':
                self._verify_zip_backup(backup_file_path)
            else:
                self._verify_dump_backup(backup_file_path)
            
            self.verification_status = 'verified'
            self.verification_details = f"Backup verified successfully. File size: {tools.human_size(file_size)}"
            self._log("Backup integrity verification passed")
        except Exception as e:
            self.verification_status = 'failed'
            self.verification_details = f"Verification failed: {e}"
            self._log(f"Backup integrity verification failed: {e}")
            raise UserError(f"Backup verification failed: {e}")
    
    def _verify_zip_backup(self, backup_file_path):
        """Verify ZIP backup integrity."""
        try:
            with zipfile.ZipFile(backup_file_path, 'r') as zip_file:
                # Test ZIP file integrity — testzip() returns the name of the
                # first corrupt entry, or None when all CRCs are valid.
                bad_file = zip_file.testzip()
                if bad_file:
                    raise UserError("Corrupt entry in ZIP backup: %s" % bad_file)
                
                # Check required files
                file_list = zip_file.namelist()
                if 'dump.sql' not in file_list:
                    raise UserError("ZIP backup missing dump.sql file")
                
                if 'manifest.json' not in file_list:
                    raise UserError("ZIP backup missing manifest.json file")
                
                # Validate manifest
                with zip_file.open('manifest.json') as manifest_file:
                    manifest = json.loads(manifest_file.read().decode())
                    if manifest.get('db_name') != self.database_name:
                        raise UserError("Manifest database name mismatch")
        except zipfile.BadZipFile:
            raise UserError("Backup file is not a valid ZIP archive")
    
    def _verify_dump_backup(self, backup_file_path):
        """Verify PostgreSQL dump backup integrity."""
        # For dump files, we can try to parse the header
        try:
            with open(backup_file_path, 'rb') as f:
                header = f.read(5)
                # PostgreSQL custom format dumps start with 'PGDMP'
                if header != b'PGDMP':
                    raise UserError("File is not a valid PostgreSQL dump")
        except Exception as e:
            raise UserError(f"Failed to verify dump file: {e}")
    
    def _preflight_database(self):
        """Raise before the dump when the configured database is missing.

        ``database_name`` is a plain stored field on the configuration: a
        configuration created on one database and then carried over to another
        (a restored copy, a staging clone, a test instance) keeps the original
        name.  Every run then died in the middle of the dump with a bare
        ``FATAL: database "x" does not exist`` — *after* the storage providers
        had been probed and reported as ready, which reads as if the provider
        were the problem.

        ``pg_database`` is cluster-wide, so the current cursor answers the
        question for any database name on this server: exactly the server the
        dump connects to.
        """
        self.ensure_one()

        self.env.cr.execute(
            "SELECT 1 FROM pg_database WHERE datname = %s",
            (self.database_name,))
        if self.env.cr.fetchone():
            self._log(
                "Pre-flight check passed for database '%s'"
                % self.database_name)
            return True

        hint = ''
        served = self.env.cr.dbname
        if self.database_name != served:
            hint = (" This configuration was created on another database — "
                    "this instance serves '%s'." % served)
        raise UserError(
            "Database '%s' does not exist on this server.%s Update the "
            "'Database Name' field on the backup configuration."
            % (self.database_name, hint))

    def _preflight_providers(self):
        """Raise before the dump if any configured provider is not usable.

        Every failure caught here is one the operator can fix in seconds,
        while the same failure *after* the dump costs the whole dump.
        Raises UserError with the provider name and the concrete reason.
        """
        self.ensure_one()

        for provider in self.config_id.all_providers:
            result = provider._preflight_check()
            if not result.get('success'):
                raise UserError(
                    "Storage provider '%s' is not ready: %s"
                    % (provider.name, result.get('message') or 'unknown reason')
                )
            self._log(
                "Pre-flight check passed for provider '%s' -> %s"
                % (provider.name, result.get('message') or 'ready')
            )

        return True

    def _upload_to_providers(self, backup_file_path):
        """Upload backup to all configured storage providers."""
        providers = self.config_id.all_providers

        # Encrypt before upload if enabled
        if self.config_id.encrypt_backup:
            backup_file_path = self._encrypt_backup_file(backup_file_path)

        return self._upload_to_providers_sequential(backup_file_path, providers)

    def _encrypt_backup_file(self, backup_file_path):
        """Encrypt the backup file with AES-256-GCM.

        The encryption key is read from the backup config. The encrypted file
        is written to a sibling path with a ``.enc`` suffix, and the caller
        (``_upload_to_providers``) uploads the encrypted one. The original
        unencrypted file is left in place for the caller's cleanup.

        Encrypted file format::

            [4B LE chunk_size][repeat: 12B nonce][4B LE ct_len][N B ct]

        Returns:
            str: Path to the encrypted backup file.
        """
        if not CRYPTOGRAPHY_AVAILABLE:
            raise UserError(
                'Encryption requires the ``cryptography`` package.\n'
                'Install it with: pip install cryptography'
            )

        key_raw = self.config_id.encrypt_key
        if not key_raw:
            raise UserError(
                'Encryption is enabled but no encryption key is set. '
                'Go to the backup configuration and click '
                '"Generate Encryption Key".'
            )

        import base64
        try:
            key = base64.b64decode(key_raw)
        except Exception as e:
            raise UserError('Invalid encryption key (not valid base64): %s' % e)

        if len(key) != 32:
            raise UserError(
                'Encryption key must be exactly 32 bytes '
                '(got %d bytes after base64 decode).' % len(key)
            )

        enc_path = backup_file_path + '.enc'
        chunk_size = 16 * 1024 * 1024  # 16 MB
        nonce_len = 12
        aesgcm = AESGCM(key)

        self._log('Encrypting backup with AES-256-GCM')
        try:
            with open(backup_file_path, 'rb') as fin, \
                 open(enc_path, 'wb') as fout:
                # Write chunk_size as 4-byte LE for the decryptor
                fout.write(chunk_size.to_bytes(4, 'little'))

                while True:
                    chunk = fin.read(chunk_size)
                    if not chunk:
                        break
                    nonce = os.urandom(nonce_len)
                    ct = aesgcm.encrypt(nonce, chunk, None)
                    fout.write(nonce)         # 12 B
                    fout.write(len(ct).to_bytes(4, 'little'))  # 4 B
                    fout.write(ct)            # N B
        except Exception as e:
            if os.path.exists(enc_path):
                os.unlink(enc_path)
            raise UserError('Encryption failed: %s' % e)

        self._log('Encryption complete: %s' % enc_path)
        return enc_path

    @staticmethod
    def decrypt_backup_file(enc_path, output_path, key_raw):
        """Decrypt a backup file that was encrypted with ``_encrypt_backup_file``.

        This is a static method so the restore wizard can call it without
        a job record.

        Args:
            enc_path: Path to the ``.enc`` file.
            output_path: Where to write the decrypted output.
            key_raw: Base64-encoded 32-byte AES-256 key.

        Returns:
            str: ``output_path`` on success.
        """
        if not CRYPTOGRAPHY_AVAILABLE:
            raise UserError('Decryption requires ``cryptography`` package.')

        import base64
        try:
            key = base64.b64decode(key_raw)
        except Exception as e:
            raise UserError('Invalid key: %s' % e)

        if len(key) != 32:
            raise UserError('Key must be 32 bytes.')

        aesgcm = AESGCM(key)

        with open(enc_path, 'rb') as fin, open(output_path, 'wb') as fout:
            chunk_size_bytes = fin.read(4)
            if len(chunk_size_bytes) < 4:
                raise UserError('Truncated encrypted file.')
            chunk_size = int.from_bytes(chunk_size_bytes, 'little')

            while True:
                nonce = fin.read(12)
                if not nonce:
                    break
                if len(nonce) < 12:
                    raise UserError('Truncated nonce in encrypted file.')
                ct_len_bytes = fin.read(4)
                if len(ct_len_bytes) < 4:
                    raise UserError('Truncated ciphertext length.')
                ct_len = int.from_bytes(ct_len_bytes, 'little')
                ct = fin.read(ct_len)
                if len(ct) < ct_len:
                    raise UserError('Truncated ciphertext.')
                plain = aesgcm.decrypt(nonce, ct, None)
                fout.write(plain)

        return output_path
    
    def _upload_to_providers_sequential(self, backup_file_path, providers):
        """Upload to providers sequentially."""
        results = {}
        
        for provider in providers:
            destination = provider._get_destination_path()
            label = "%s -> %s" % (provider.name, destination) if destination else provider.name
            self._log(f"Uploading to provider: {label}")
            
            try:
                result = provider.upload_backup(backup_file_path, self.backup_filename)
                results[provider.name] = result
                
                if result.get('success'):
                    self._log(f"Upload to {label} successful")
                else:
                    self._log(f"Upload to {label} failed: {result.get('message', 'Unknown error')}")
            except Exception as e:
                error_msg = f"Upload to {label} failed with exception: {e}"
                self._log(error_msg)
                results[provider.name] = {
                    'success': False,
                    'message': str(e),
                    'metadata': {}
                }
        
        return results
    
    def _serialize_provider_results(self, provider_results):
        """Serialize provider results to JSON, handling datetime objects."""
        def datetime_serializer(obj):
            """JSON serializer function for datetime objects."""
            if isinstance(obj, datetime.datetime):
                return obj.isoformat()
            elif isinstance(obj, datetime.date):
                return obj.isoformat()
            raise TypeError(f"Object of type {type(obj)} is not JSON serializable")
        
        try:
            return json.dumps(provider_results, indent=2, default=datetime_serializer)
        except Exception as e:
            # Fallback - convert to string representation
            _logger.warning("Failed to serialize provider results to JSON: %s", str(e))
            return str(provider_results)
    
    def _log(self, message):
        """Add entry to backup job log."""
        timestamp = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        log_entry = f"[{timestamp}] {message}"
        
        if self.log_entries:
            self.log_entries += f"\n{log_entry}"
        else:
            self.log_entries = log_entry

        # Cap the stored log: log_entries is an unpruned Text column and _log
        # runs on every step, so a chatty backup must not grow the row forever.
        max_log_length = 200000
        if len(self.log_entries) > max_log_length:
            self.log_entries = (
                '[log truncated]\n' + self.log_entries[-max_log_length:]
            )
        
        # Also log to system logger. Use %s (not %d) so this also works on
        # non-persisted records (.new()), where self.id is a NewId.
        _logger.info("Backup Job %s: %s", self.id or 'new', message)

    @staticmethod
    def _safe_rmtree(path, label='temp dir'):
        """Remove a directory tree, logging the reason if it can't be fully
        removed, then retrying with ignore_errors=True so we never leave
        behind a partially-cleaned path *and* never mask the original
        exception by re-raising from a finally block.
        """
        if not path or not os.path.exists(path):
            return
        try:
            shutil.rmtree(path)
        except Exception as e:
            _logger.warning(
                "Could not fully remove %s %s: %s — retrying with ignore_errors",
                label, path, e,
            )
            shutil.rmtree(path, ignore_errors=True)
            if os.path.exists(path):
                _logger.error("Leaked %s: %s still exists after cleanup", label, path)

    @classmethod
    def _mark_temp_dir_owner(cls, path):
        """Write the creating process PID into the temp dir (owner marker).

        The stale sweep uses this to protect backups that are legitimately
        still running — however long they take — while still reclaiming
        dirs whose owner process is gone (SIGKILL, OOM, restart).
        """
        try:
            with open(os.path.join(path, cls._TEMP_OWNER_MARKER), 'w') as fh:
                fh.write(str(os.getpid()))
        except OSError as e:
            # Never fail a backup over the marker; the sweep falls back to
            # age-based cleanup for dirs without one.
            _logger.warning("Could not write owner marker in %s: %s", path, e)

    @staticmethod
    def _pid_is_alive(pid):
        """Return True if a process with this PID currently exists."""
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return False
        except PermissionError:
            return True  # exists but owned by another user
        except OSError:
            return False
        return True

    @classmethod
    def _temp_dir_owner_alive(cls, path):
        """Return True if the temp dir's owner marker names a live process."""
        try:
            with open(os.path.join(path, cls._TEMP_OWNER_MARKER)) as fh:
                pid = int(fh.read().strip())
        except (OSError, ValueError):
            # No/unreadable marker (e.g. dir created by a pre-marker version
            # of this module): fall back to pure age-based cleanup.
            return False
        return cls._pid_is_alive(pid)

    @classmethod
    def _cleanup_stale_temp_files(cls, max_age_seconds=2 * 3600,
                                  hard_max_age_seconds=24 * 3600):
        """Sweep the system temp dir for leftover backup temp dirs and remove
        the ones that no longer belong to a running backup.

        This is the safety net for cases the per-run try/finally can't cover:
        the worker getting SIGKILL'd by the OOM killer, an Odoo restart in
        the middle of a long filestore copy, or shutil.rmtree silently
        failing under disk pressure with ignore_errors=True.

        A dir is removed only when ALL of these hold:
        - it is older than ``max_age_seconds``, and
        - its owner marker (the PID of the process that created it) does not
          name a live process — so a backup that legitimately runs for many
          hours is never swept out from under the worker writing to it, and
        - or, regardless of the owner, it is older than
          ``hard_max_age_seconds`` (caps leakage if a recycled PID happens to
          match an unrelated live process).
        """
        tmp_root = tempfile.gettempdir()
        now = time.time()
        cutoff = now - max_age_seconds
        hard_cutoff = now - hard_max_age_seconds
        removed = []
        for prefix in cls._TEMP_DIR_PREFIXES:
            for path in glob.glob(os.path.join(tmp_root, prefix + '*')):
                try:
                    mtime = os.path.getmtime(path)
                    if mtime >= cutoff:
                        continue  # recent — likely an in-progress backup
                    if (
                        os.path.isdir(path)
                        and mtime >= hard_cutoff
                        and cls._temp_dir_owner_alive(path)
                    ):
                        continue  # long-running backup still owned by a live process
                    if os.path.isdir(path):
                        shutil.rmtree(path, ignore_errors=True)
                    else:
                        os.unlink(path)
                    if not os.path.exists(path):
                        removed.append(path)
                except Exception as e:
                    _logger.warning(
                        "Could not remove stale backup temp path %s: %s", path, e,
                    )
        if removed:
            _logger.info(
                "Backup temp sweep removed %d stale path(s): %s",
                len(removed), ', '.join(removed),
            )

    @api.model
    def _cleanup_stuck_jobs(self, max_age_hours=6, batch_limit=500):
        """Mark backups left 'running'/'pending' long past their start as errors.

        ``_commit_progress`` makes an in-flight job visible even when the
        worker is killed, but nothing ever closes such a row: the UI would show
        a backup that never ends and the failure would never be reported.
        Called from the daily cleanup cron (backup.config.cleanup_old_backups).
        """
        cutoff = fields.Datetime.now() - datetime.timedelta(hours=max_age_hours)
        stuck = self.search([
            ('status', 'in', ('running', 'pending')),
            ('start_time', '<', cutoff),
        ], limit=batch_limit)
        for job in stuck:
            job.write({
                'status': 'error',
                'end_time': fields.Datetime.now(),
                'error_message': 'Backup was interrupted: the worker stopped '
                                 'before the backup could finish. Check the '
                                 'system log and retry.',
            })
            job._log(
                'Marked as failed: no completion within %d hour(s).' % max_age_hours
            )
        if stuck:
            _logger.warning(
                "Marked %d interrupted backup job(s) as failed", len(stuck)
            )
        return len(stuck)

    def _assert_backup_admin(self):
        """Reject backup execution for read-only users."""
        if not self.env.user.has_group('backup_versatile.group_backup_admin'):
            raise AccessDenied(self.env._(
                'Backup administrator rights are required for this operation.'
            ))

    def retry_backup(self):
        """Retry a failed backup job."""
        self._assert_backup_admin()
        self.ensure_one()
        
        if self.status not in ['error', 'warning']:
            raise UserError("Can only retry failed or warning backups")
        
        # Reset job status
        self.write({
            'status': 'pending',
            'end_time': False,
            'error_message': False,
            'log_entries': False,
            'provider_results': False,
            'verification_status': 'not_verified',
            'verification_details': False,
        })
        
        # Process the backup
        return self._process_backup()
    
    def view_provider_results(self):
        """View detailed provider results."""
        self.ensure_one()
        
        if not self.provider_results:
            raise UserError("No provider results available")
        
        try:
            results = json.loads(self.provider_results)
            formatted_results = json.dumps(results, indent=2)
        except:
            formatted_results = self.provider_results
        
        return {
            'type': 'ir.actions.act_window',
            'name': 'Provider Results',
            'res_model': 'backup.job',
            'view_mode': 'form',
            'res_id': self.id,
            'target': 'new',
            'context': {
                'default_provider_results': formatted_results,
            },
        }
