.. image:: https://img.shields.io/badge/license-AGPL--3-blue.svg
   :target: http://www.gnu.org/licenses/agpl-3.0-standalone.html
   :alt: License: AGPL-3

==========
Soft Gantt
==========

Odoo 19 Community ships **no** Gantt view: the ``gantt`` view type only exists
in the Enterprise add-on ``web_gantt``. This module adds a self-contained view
type, ``gantt_soft``, built the same way the core builds its own extra view
types (``web_hierarchy``): no Enterprise code, and no third-party JavaScript
library to vendor or to keep up to date.

Usage
=====

A Gantt view is declared like any other view::

    <record id="my_model_gantt_view" model="ir.ui.view">
        <field name="model">my.model</field>
        <field name="arch" type="xml">
            <gantt_soft date_start="date_start" date_stop="date_stop"/>
        </field>
    </record>

The action of that model then has to offer the mode. It is added to
``view_mode``, and ``ir.actions.act_window.view`` records are avoided for a
reason worth knowing: the ordered view list the client receives is built as
*the action's view records first, then the ``view_mode`` entries they do not
cover* (``ir.actions.act_window._compute_views``). Binding a single
``ir.actions.act_window.view`` record to an action that has none therefore
makes the Gantt the **default** view of that screen, instead of adding a button
to the view switcher. Because ``view_mode`` is a Char that a data record can
only replace, the mode is added from Python by the consumer module: see
`Consumer modules`_.

The view type names its own fields, so the same view type schedules any model
that has two suitable fields (field operations, tasks, manufacturing orders or
leaves) with no code change.

Consumer modules
================

This module ships **the view type and nothing else**: no view, no field, no
action. It depends on ``web`` alone, on purpose: a business dependency would
make the type unavailable to every model it does not depend on, and would tie
a view type to the first model that happened to use it. A module that
schedules a model is a *consumer*:

* it depends on ``soft_gantt`` (and on its own business module),
* it declares the ``<gantt_soft>`` view of its model, and the fields the chart
  reads when the model has no suitable ones (a completion percentage, a colour
  index),
* it adds the ``gantt_soft`` mode to the action of that model.

``field_operation_gantt`` is the reference consumer. Adding the mode deserves
care, because ``view_mode`` is a comma separated Char: a data record listing it
can only **replace** the whole string, so the last module to be updated wins and
silently drops the modes of the others. A consumer therefore adds the mode from
Python (read the modes, insert the new one after a known mode, write the value
back) and removes it again in an ``uninstall_hook``. ``field_operation_gantt``
does exactly that, with a test that pins the behaviour.

The Enterprise Gantt (``web_gantt``) answers the ``gantt`` view type. Offering
both in one database would give users two buttons for the same screen, so the
module declares ``excludes: ["web_gantt"]`` in its manifest: Odoo refuses to
install the two together.


Arch attributes
===============

====================== ======================================================
``date_start``         mandatory, Date/Datetime the bar starts at
``date_stop``          mandatory, Date/Datetime the bar ends at
``label``              optional field shown in front of each row; a selection
                       is read by its label. This is a *field name*: Odoo also
                       treats the ``label`` attribute as translatable text, so
                       never add that name to a ``.po`` file, or the translated
                       arch would carry a label instead of a field name
``progress``           optional Float/Integer drawn as a progress bar
``color``              optional Integer used for the bar colour (the Odoo
                       colour index, 0 to 11)
``mode``               initial scale: ``day``, ``week`` or ``month`` (month);
                       it must be one of the offered ``scales``
``scales``             comma separated scales offered to the user; unknown
                       names are refused
``default_range``      initial window: ``day``, ``week``, ``month``,
                       ``quarter`` or ``year`` (month)
``group_by``           optional field the rows are grouped by: one row per
                       value (a team, a customer), the records of that group
                       drawn along the timeline
``limit``              maximum number of records read per window (default 500)
``default_order``      ordering of the rows
``open_form_view``     ``1`` opens the record from a bar instead of showing the
                       details card
``create``             ``0`` hides the New button; default ``1``
``edit``               ``0`` disables drag and resize; default ``1``
``delete``             no effect: this view has no record selection
``duplicate``          no effect: this view has no record selection
====================== ======================================================

Every attribute that can be checked without a browser is validated when the
view is installed: a misspelled field name, a Char field used as a date, an
unknown attribute, a bad ``mode`` or ``scales``, a non-positive ``limit``, a
read-only field used as a group or a declared ``<field>`` of an unrenderable
type refuses the view with a message that names the problem. The client parser
runs the same checks on views built at runtime, so a broken view never shows an
empty schedule instead of an error.

Behaviour
=========

* **A window, not a table.** The view reads one *calendar unit* at a time (the
  month holding today by default, or whatever ``default_range`` asks for) and
  the records that overlap it. The arrows around the period in the control panel
  move that window, and the middle button comes back to today. This is what
  makes the view usable on a table holding years of history: a hundred thousand
  operations cost the same one month of reading as a hundred, and paging is a
  click instead of a scrollbar. ``limit`` stays as a safety net for a window
  that is genuinely crowded; if a window holds more records than that, only the
  first ones are drawn.
* **A scale is a zoom, and the header has two levels.** The control panel
  buttons zoom in and out: ``Day`` shows the *hours* of one day, ``Week`` the
  days of one week, ``Month`` the days of one month. Picking a scale moves the
  window to that scale's own length, so the cells stay countable. The header is
  drawn on two levels, the coarse band over the cells, and today is marked by a
  line and a *Today* badge. Should a window ever be too wide for its unit, the
  unit is coarsened until the cells are readable rather than drawing thousand
  stripes. The period label follows the window: a day is named as a day, a week
  by its two ends, a month by its name.
* **One row per record, or one row per group.** By default every record is a
  row. With ``group_by`` the rows are the values of that field (one per team,
  per customer) and the records of a group are drawn along it: the group
  vertically, its dates horizontally. Two services of the same team overlapping
  in time are given a lane each, so the row grows instead of hiding one behind
  the other. Records whose group is unset keep a row of their own ("Not set").
  A many2one group is identified by its id, so two records sharing a name stay
  apart.
* **A bar carries its details.** Clicking a bar opens a card with the two dates
  and every ``<field>`` the arch declares (dates, booleans, selection labels and
  many2one names resolved), and an *Open* button that goes to the form. Moving
  the bar is a drag; reading it is a click, so the two never fight. With
  ``open_form_view="1"`` the click goes to the form directly.
* **Search first.** Records come from the action's domain plus whatever the
  search bar applies: filters and favourites really reload the view. Grouping
  through the search bar is not offered, because the rows of this view are the
  rows of ``group_by``; a menu entry that changes nothing is worse than no
  entry.
* **The timeline is the reader's calendar.** The columns are cut on the *user's*
  timezone (Odoo sets luxon's default zone from the user): the hours of their
  day, the days of their week, the Monday that starts it. A job stored as 04:00
  UTC is 07:00 in Turkey, and the 07:00 column is where it is drawn, instead of
  landing three hours away.
* **Date and Datetime are read differently.** A ``datetime`` is an instant
  stored in UTC: it is read and written in UTC, so nothing moves when a DST day
  is 23 or 25 hours long. A ``date`` is a calendar day with no timezone: it is
  read and written as the user's own day, so a deadline of 2026-03-05 stays the
  5th in Turkey and in New York.
* **Drag to reschedule.** Dragging a bar moves both dates by the same whole
  number of days; dragging one of its edges changes only that end and keeps at
  least one day. The value written back is computed for the field's own type, so
  a task is never shifted by a day in a UTC+ timezone.
* **One date is enough, and a missing end is a duration.** A record carrying
  only a start (or whose end equals its start) is given a real duration before it
  is drawn: one hour when the timeline is read in hours, and a whole day
  otherwise. A record with neither date is counted and reported under the
  timeline; when no record carries a date at all, the view says so instead of
  drawing an empty grid.
* **A folded group is one bar.** Clicking the group toggle folds a team away;
  the single bar spans the earliest start to the latest stop and shows the
  record count. It cannot be dragged or resized (it does not stand for one
  record), and clicking it unfolds the group again.
* **No surprises.** Bars are only draggable when the user may edit, and a failed
  write is reported instead of being swallowed.
* **Theme safe.** Every colour is a ``$o-gantt-soft-*`` SCSS variable. The light
  values live in ``gantt_soft.scss``, the dark ones in ``gantt_soft.dark.scss``,
  which is served through the ``web.assets_web_dark`` bundle when
  ``ir_http.color_scheme()`` is dark (Odoo 19 Community returns ``light`` by
  default; a colour-scheme module such as ``ica_web_responsive`` can return
  ``dark``). No media query and no theme attribute are involved.

Known limitations
=================

* ``delete`` and ``duplicate`` are accepted in the arch for compatibility but
  have no effect: the view has no record selection.
* ``limit`` truncates a window silently. A window holding more records than the
  limit draws the first ones only; narrow the window (a smaller scale or range)
  to see the rest.
* ``date_stop`` is a half-open end: a record ending exactly on a day boundary
  covers the days before it, not the boundary day itself.

Licence
=======

AGPL-3.0 or later, like the rest of the Softteknik add-ons.

Credits
=======

* Softteknik Bilişim (<https://softteknik.com>)
