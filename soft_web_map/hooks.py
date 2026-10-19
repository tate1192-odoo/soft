"""Uninstall hook for the ``leaflet_map`` view type.

The hook removes ``leaflet_map`` from window actions and deletes actions that
would be left without any view mode.  It is implemented with the ORM (no raw
SQL).
"""

import logging

_logger = logging.getLogger(__name__)


def uninstall_hook(env):
    """Remove ``leaflet_map`` from existing window actions on uninstall."""
    Action = env["ir.actions.act_window"]
    actions = Action.search(
        [
            "|",
            ("view_mode", "like", "leaflet_map"),
            ("mobile_view_mode", "like", "leaflet_map"),
        ]
    )
    to_delete = Action
    for action in actions:
        modes = [mode.strip() for mode in (action.view_mode or "").split(",")]
        cleaned = [mode for mode in modes if mode and mode != "leaflet_map"]
        if not cleaned:
            to_delete |= action
            continue

        if len(cleaned) != len(modes):
            action.view_mode = ",".join(cleaned)

        if action.mobile_view_mode:
            mobile_modes = [
                mode.strip()
                for mode in action.mobile_view_mode.split(",")
                if mode.strip() and mode.strip() != "leaflet_map"
            ]
            if mobile_modes:
                action.mobile_view_mode = ",".join(mobile_modes)
            else:
                # "kanban" is the web client default for mobile view modes.
                action.mobile_view_mode = "kanban"

    if to_delete:
        _logger.info("Removing %d leaflet_map-only actions", len(to_delete))
        to_delete.unlink()
