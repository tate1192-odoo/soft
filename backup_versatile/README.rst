=================
 Backup Versatile
=================

Database backups for Odoo 19, scheduled and monitored: a configuration decides
*what* to dump, *where* to send it and *how long* to keep it, and every run
leaves a job record behind. No Enterprise, no external service required for the
basic path.

Configuration
=============

``backup.config`` holds one backup schedule. A configuration names the database,
the format, one or more storage providers, the retention policy, the
notification addresses and whether the archive is encrypted.

Formats
-------

``zip``
    A ZIP archive of the ``pg_dump`` output together with the filestore, so the
    archive is a full restorable copy of the instance.
``dump``
    The plain ``pg_dump`` file: smaller, SQL only, no attachments.

Providers
=========

Providers are records, not settings, so one configuration can write the same
backup to several destinations.

``backup.provider.local``
    A directory on the server or on a mounted network share.
``backup.provider.sftp``
    A remote server over SSH/SFTP, driven by `paramiko`_. Password or private
    key authentication, host key verification with trust-on-first-use pinning,
    remote directory creation and an upload size check. Remote paths are
    sanitized before use: traversal, ``.``/``..`` segments, trailing slashes and
    null bytes are rejected (``tests/test_path_safety.py``).
``backup.provider.cloud``
    S3-compatible storage through `rclone`_ (primary engine, detected at
    runtime); an already configured rclone remote can be reused.

.. _paramiko: https://www.paramiko.org/
.. _rclone: https://rclone.org/

Retention
=========

``count``
    Keep the last *N* backups.
``days``
    Keep everything younger than *N* days.
``custom``
    Explicit policy, evaluated by the cleanup cron.

Cleanup runs from its own scheduled action and only ever deletes files that a
job record points at.

Jobs and monitoring
===================

``backup.job`` records one run: start and end time, duration, size, status,
message and the provider it went to. From the job list and the configuration
form the module reports the last run, the last status, the total number of
backups and the success rate; success and failure can each notify a list of
addresses.

With ``verify_backups`` set, the module reopens the produced archive after the run
and checks it, so a truncated backup fails the job instead of silently becoming
the only copy.

Restore
=======

``backup.restore.wizard`` restores one of a provider's archives. It is guarded on
both ends: the SQL it builds is checked so a ``DROP DATABASE`` cannot run without
its matching ``CREATE`` (``tests/test_restore_guard.py``), the archive name is
sanitized the same way the SFTP paths are, and only the *Administrator* group has
access to the wizard at all.

Security
========

Two groups. *User* reads schedules, providers and jobs (read-only ACL on every
model, no wizard). *Administrator* configures schedules and providers and is the
only group that can restore. Credentials live on the provider record and are
rendered as password fields; the encryption key is stored base64 encoded on the
configuration and is masked in the form.

Installation
============

::

    pip install "paramiko>=3.4,<6.0"    # SFTP provider
    # optional: rclone, for the cloud provider
    odoo-bin -d <database> -i backup_versatile --stop-after-init

The SFTP provider declares ``paramiko`` as an external dependency, so the module
refuses to install without it. Both scheduled actions ship **inactive**: a
backup schedule is enabled on the configuration, not by the install.

Tests
=====

``tests/`` holds 114 test methods in eleven files: file filtering, encryption,
path safety, provider preflight, database preflight, the rclone command line,
the restore guard, retention, the paramiko SFTP session and ZIP verification.
They run without a network or a remote server: the SFTP session and rclone are
stubbed.

License
=======

``LGPL-3``, like the rest of this repository — see the ``license`` key in the
manifest and ``README.md`` at the repository root.
