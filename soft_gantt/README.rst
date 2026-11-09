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

The same module runs on **both editions**. Enterprise databases always have
``web_gantt`` installed (it is ``auto_install``), and that is not a conflict:
the two modules register two *different* view types (``gantt`` and
``gantt_soft``), so they live side by side. A consumer lists the type it wants
for its screen in the action's ``view_mode``: ``gantt_soft`` here, never both.
One code base, the same behaviour and the same tests on a Community and on an
Enterprise database.

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

The Enterprise Gantt (``web_gantt``) answers the ``gantt`` view type, which is
not the type this module adds: the two modules coexist, and a consumer chooses
the one its action lists. This is deliberate — ``web_gantt`` is
``auto_install`` on Enterprise, so an ``excludes`` entry would make this module
impossible to install on every Enterprise database. One consequence to keep in
mind: do **not** list both ``gantt`` and ``gantt_soft`` in the same action's
``view_mode``, or the view switcher will show two Gantt buttons for the same
screen.


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
``milestone``          optional Boolean field: a record flagged by it is drawn
                       as a diamond on its start date instead of a bar
``dependencies``       optional Many2many/One2many field pointing back at the
                       same model: the records it lists are the ones that must
                       finish first, and an arrow joins them to this record
``mode``               initial scale: ``day``, ``week``, ``month``,
                       ``quarter`` or ``year`` (month); it must be one of the
                       offered ``scales``
``scales``             comma separated scales offered to the user; unknown
                       names are refused
``precision``          subdivisions of the cell of a scale, as a Python dict:
                       ``precision="{'day': 'hour:quarter', 'week':
                       'day:half'}"``. The unit must be the scale's own cell
                       (hours of a day, days of a week or a month) and the
                       factor one of ``full``, ``half``, ``quarter``. On the
                       day scale the bars keep their real minutes (the grid is
                       a reading aid); on the week and month scales they snap
                       to the finer day parts
``default_range``      initial window: ``day``, ``week``, ``month``,
                       ``quarter`` or ``year`` (month)
``group_by``           optional field, or comma separated list of fields,
                       the rows are grouped by: one row per value of the first
                       field (a team, a customer), then one row per value of the
                       next one, ..., and the records of the last level are
                       drawn along the timeline (``group_by="team_id,type_id"``)
``group_total``        optional Float/Integer field summed over the records of
                       a group and shown on its row ("Alpha (3) · Total work:
                       17.5")
``group_avatar``       optional binary image field of the outer group's record,
                       read on the comodel of the first ``group_by`` field and
                       drawn as an avatar on its row; requires that first level
                       to be a many2one
``collapse_first_level``  ``1`` starts with the outer groups folded (folded
                       into one bar each), which is how a long plan is read
                       before opening the groups one by one; nested rows stay
                       open when their parent is unfolded
``cell_create``        ``1`` turns the grid into a planning surface: a double
                       click on an empty cell opens the form with that cell's
                       dates defaulted, the ``+`` of a group row with the group
                       defaulted
``decoration-danger``  expression evaluated on the record; a matching bar is
``decoration-info``    drawn with a ring in that colour. The names are the list
``decoration-secondary`` view decorations: ``danger``, ``info``, ``secondary``,
``decoration-success``   ``success`` and ``warning``
``decoration-warning``
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
view is installed: a misspelled field name, a Char field used as a date, a date
field the ORM cannot search (the window is read with a domain on it), an
unknown attribute, a bad ``mode``, ``scales`` or ``precision``, a non-positive
``limit``, a
``group_by`` level naming an unknown field or a non-groupable type, a
``milestone`` field that is not a Boolean, a ``dependencies`` list that points at another model, an unknown ``decoration-*``
name or an empty decoration expression, a ``group_total`` that is not numeric, a
``group_avatar`` that names no binary field (or a non-many2one ``group_by``), a
``cell_create``/``collapse_first_level`` that is not one of ``0``/``1``/``true``/
``false`` (the only spellings the client reads the same way), or a declared
``<field>`` of an unrenderable type refuses the view with a message that names
the problem. The
client parser runs the same checks on views built at runtime, so a broken view
never shows an empty schedule instead of an error.

Children of the view
====================

``<field>`` nodes add a value to the tooltip and to the details card.
``<button>`` nodes add actions to the card, in arch order::

    <gantt_soft date_start="date_start" date_stop="date_stop" ...>
        <field name="partner_id"/>
        <button name="action_confirm" type="object" string="Confirm"
                icon="fa fa-check" confirm="Confirm this operation?"/>
        <button name="base.action_partner_form" type="action" string="Open partner"/>
    </gantt_soft>

``type="object"`` calls a public method on the record, ``type="action"`` opens an
action with that record as its active record. ``confirm`` shows the client's
confirmation dialog first, ``class`` adds Bootstrap classes to the button, and
either ``string`` or ``icon`` (or both) draws it. ``string`` and ``confirm`` are
translatable terms, like the button labels of the other views. The method of an
``object`` button is checked when the view is installed: a typo is a view error,
not a button that fails when a user clicks it. The card is a read-only surface,
so a button is a way to act without leaving the chart: the write rights are the
method's own and a user who cannot write sees the error of the method, not a
broken button.

Behaviour
=========

* **A window, not a table.** The view reads one *calendar unit* at a time (the
  month holding today by default, or whatever ``default_range`` asks for) and
  the records that overlap it. The arrows around the period in the control panel
  move that window, and the middle button comes back to today. A view without a
  saved state opens on the period being **planned**, not always on the one
  holding today: with ``default_range="week"`` that is the current week, except
  on Sunday, when the current week has no day left ahead and the next week opens
  instead. This is what makes the view usable on a table holding years of
  history: a hundred thousand operations cost the same one month of reading as
  a hundred, and paging is a click instead of a scrollbar. ``limit`` stays as a
  safety net for a window that is genuinely crowded; if a window holds more
  records than that, only the first ones are drawn.
* **A scale is a zoom, and the header has two levels.** The control panel
  buttons zoom in and out: ``Day`` shows the *hours* of one day, ``Week`` the
  days of one week, ``Month`` the days of one month, ``Quarter`` the weeks of a
  quarter and ``Year`` the months of a year. Picking a scale moves the
  window to that scale's own length, so the cells stay countable. The header is
  drawn on two levels, the coarse band over the cells, and today is marked by a
  line and a *Today* badge. Should a window ever be too wide for its unit, the
  unit is coarsened until the cells are readable rather than drawing thousand
  stripes. The period label follows the window: a day is named as a day, a week
  by its two ends, a month by its name. ``precision`` subdivides the cells of a
  scale into full, half or quarter cells (the hours of a day into quarter
  hours, the days of a week or a month into half days), drawn as a lighter grid
  inside the columns: on the day scale the bars keep their stored minutes, on
  the day-unit scales they snap to the finer day part.
* **One row per record, one row per group, or a tree of groups.** By default
  every record is a row. With ``group_by`` the rows are the values of that field
  (one per team, per customer) and the records of a group are drawn along it: the
  group vertically, its dates horizontally. ``group_by`` also takes a comma
  separated list: every level makes a row, the outer levels are header rows that
  count (and, with ``group_total``, sum) their whole subtree, and the last level
  holds the bars (``group_by="team_id,type_id"``: team, then service type inside
  it). A header row folds its whole subtree into one bar; nested rows start open
  when their parent is unfolded. Two bars that overlap *on screen* are given a
  lane each, so the row grows instead of hiding one behind the other: at a day
  scale that includes two services of the same team on the same day, whose times
  of day need not overlap. Records whose group is unset keep a row of their own
  ("Not set"). A many2one group is identified by its id, so two records sharing a
  name stay apart, and a nested group is identified by the *path* of its values,
  so the same service type under two teams is two rows. A milestone keeps a lane
  of its own from a bar starting at the same instant: its diamond is drawn around
  that point, so sharing the lane would put the bar's edge under it.
* **The grid creates records too.** With ``cell_create="1"`` the empty cells
  are a planning surface, not wallpaper: a double click opens the form of the
  model with the clicked cell's dates defaulted (in the format each date field
  reads), and the ``+`` on a group row opens it with that group defaulted. The
  view type stays generic: the form is the one the action already offers, so a
  consumer keeps its own defaults and its own access rights.
* **A group row says what it holds.** A grouped row reads as *name (count)* and,
  with ``group_total``, adds the sum of that field over the records of the group
  ("Alpha (3) · Total work: 17.5"). ``group_avatar`` puts the image of the group
  record (a team leader, a customer logo) next to the name, and
  ``collapse_first_level="1"`` starts with every group folded, which is how a
  plan of a year is read before opening the groups one by one.
* **Decorations are a second reading.** ``decoration-danger="status == 'cancel'"``
  (and the other four decoration names) evaluates the expression on the record
  and draws a ring inside the matching bars: the bar colour still says what the
  ``color`` field says, while the ring flags a second fact (late, priority,
  cancellation) without a new field for it. The fields an expression reads are
  requested with the window even when the arch does not declare them.
* **A bar carries its details and its actions.** Clicking a bar opens a card
  with the two dates and every ``<field>`` the arch declares (dates, booleans,
  selection labels and many2one names resolved), the ``<button>`` actions the
  arch declares (a method call or an action, with an optional confirmation),
  and an *Open* button that goes to the form. Moving the bar is a drag; reading
  it is a click, so the two never fight. With ``open_form_view="1"`` the click
  goes to the form directly.
* **Search first.** Records come from the action's domain plus whatever the
  search bar applies: filters and favourites really reload the view. Grouping
  through the search bar is not offered, because the rows of this view are the
  rows of ``group_by``; a menu entry that changes nothing is worse than no
  entry.
* **The timeline is the reader's calendar.** The columns are cut on the *user's*
  profile timezone (``user.tz``, with the browser zone as a fallback): the
  hours of their day, the days of their week, the Monday that starts it. A job
  stored as 04:00 UTC is 07:00 in Turkey, and the 07:00 column is where it is
  drawn, instead of landing three hours away.
* **Date and Datetime are read differently.** A ``datetime`` is an instant
  stored in UTC: it is read and written in UTC, so nothing moves when a DST day
  is 23 or 25 hours long. A ``date`` is a calendar day with no timezone: it is
  read and written as the user's own day, so a deadline of 2026-03-05 stays the
  5th in Turkey and in New York.
* **Drag to reschedule.** Dragging a bar moves both dates by the same whole
  number of days; dragging one of its edges changes only that end and keeps at
  least one day. The value written back is computed for the field's own type, and
  the other end (the anchor) is read for *its* own type, so a view mixing a
  ``date`` end with a ``datetime`` one is resized in the right calendar and a task
  is never shifted by a day in a UTC+ timezone.
* **One date is enough, and a missing end is a duration.** A record carrying
  only a start (or whose end equals its start) is given a real duration before it
  is drawn: one hour when the timeline is read in hours, and the rest of the day
  cell it starts in otherwise. That is what makes the bar exactly one column wide
  at a day scale, instead of spilling into the next cell. A record with neither
  date is counted and reported under the
  timeline; when no record carries a date at all, the view says so instead of
  drawing an empty grid.
* **A folded group is one bar.** Clicking the group toggle folds a team away;
  the single bar spans the earliest start to the latest stop and shows the
  record count. It cannot be dragged or resized (it does not stand for one
  record), and clicking it unfolds the group again.
* **A milestone is a point, and a dependency is an arrow.** A record flagged by
  the ``milestone`` field is drawn as a diamond on its start date: it carries no
  duration, so it offers no resize grips. A record listing its predecessors in
  the ``dependencies`` field is joined to them by an arrow, drawn from the end of
  the predecessor to the start of the record. Both are opt-in: a view that names
  neither behaves exactly like before.
* **Fit the search, and export the period.** The control panel offers *Fit*, which
  widens the window to the span of every record the current search returns, and
  *CSV*, which downloads the records of the window with the two dates, the
  duration and the fields the arch declares.
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
* A dependency arrow is drawn only between two bars the viewport paints: a folded
  group and a row scrolled out of view have no end to reach, so that pair is left
  out rather than drawn to nowhere.
* ``Fit`` reads the two date fields of the search once, bounded to 2000 records.
  Past that the fitted window describes the first records only, and the view says
  so in a notification. The first arrow press after a fit moves to the month
  holding the window, since a fitted window has no calendar unit to step by.

Licence
=======

AGPL-3.0 or later, like the rest of the Softteknik add-ons.

Credits
=======

* Softteknik Bilişim (<https://softteknik.com>)
