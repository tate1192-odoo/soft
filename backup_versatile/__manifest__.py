# -*- coding: utf-8 -*-
{
    'name': "Backup Versatile",

    'summary': "Automated database backups with Local + SFTP storage, retention policies, integrity verification, and monitoring",

    'description': """
        Backup Versatile - Flexible Database Backup Solution
        ====================================================

        A reliable database backup solution for Odoo with local and SFTP
        remote storage, automated scheduling, retention policies, and comprehensive monitoring.

        Core Features
        -------------
        * **Local Storage**: Store backups on local filesystem or network-mounted drives
        * **SFTP Remote Storage**: Securely transfer backups to remote servers via SSH/SFTP
        * **Backup Formats**: ZIP archives (with filestore) or PostgreSQL dumps
        * **Integrity Verification**: Automatic verification after backup creation
        * **Flexible Scheduling**: Automated backups via configurable cron jobs
        * **Retention Policies**: Keep last N backups or retain for N days
        * **Automated Cleanup**: Automatic removal of old backups based on policy
        * **Job Monitoring**: Track backup history, status, duration, and file sizes
        * **Email Notifications**: Get notified on backup success or failure
        * **Success Rate Tracking**: Monitor backup reliability over time

        SFTP Provider Features
        ----------------------
        * Reliable transfers powered by Paramiko (no conflicting dependencies)
        * Password-based and SSH private key authentication
        * SSH host key verification with trust-on-first-use pinning
        * Automatic remote directory creation
        * Upload verification (size check)
        * Configurable connection and transfer timeouts

        Security Features
        -----------------
        * Two-tier access control: User and Administrator roles.
        * Secure credential storage
        * Granular model-level permissions
    """,

    'author': "Softteknik Bilişim",
    'website': "https://softteknik.com",
    'category': 'Administration',
    'version': '19.0.1.0.6',

    # Module dependencies
    'depends': ['base'],

    # External dependencies
    'external_dependencies': {
        'python': ['paramiko'],
    },

    # Data files
    'data': [
        # Security
        'security/backup_security.xml',
        'security/ir.model.access.csv',

        # Data
        'data/backup_cron.xml',
        'data/backup_provider_data.xml',

        # Views
        'views/backup_config_views.xml',
        'views/backup_job_views.xml',
        'views/backup_provider_views.xml',
        'views/backup_provider_cloud_views.xml',
        'views/backup_restore_wizard_views.xml',
        'views/menus.xml'
    ],

    'installable': True,
    'auto_install': False,
    'application': True,

    'license': 'LGPL-3',

    # Images
    'images': [
        'static/description/banner.png',
    ],
}
