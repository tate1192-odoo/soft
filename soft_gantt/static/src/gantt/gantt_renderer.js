import { Component, onWillRender, useRef } from "@odoo/owl";
import { formatDate } from "@web/core/l10n/dates";
import { _t } from "@web/core/l10n/translation";
import { useVirtualGrid } from "@web/core/virtual_grid_hook";

import {
    DAY_MS,
    addLocalDays,
    addLocalMonths,
    barGeometry,
    buildTimeline,
    ensureDuration,
    fieldText,
    packLanes,
    parseOdooFieldDate,
    snapToUnit,
    startOfLocalDay,
    startOfLocalMonth,
    startOfLocalWeek,
} from "./gantt_utils";

const { DateTime } = luxon;

/** Number of colours defined for the optional `color` field. */
const COLOR_COUNT = 12;

/**
 * Height of a row, in pixels.
 *
 * The virtual grid needs to know how tall the rows are to know which ones are
 * visible, so this constant and `$o-gantt-soft-row-height` in
 * ``gantt_soft.scss`` must stay equal. Changing one without the other shifts
 * the bars against their labels.
 */
const ROW_HEIGHT = 38;

/**
 * Height of one lane inside a grouped row.
 *
 * A row holding a group can hold several records on the same date: each gets a
 * lane of its own and the row grows by this much per lane.
 */
const LANE_HEIGHT = 30;

/**
 * Height of a bar, in pixels. It and `$o-gantt-soft-bar-height` in the
 * stylesheet must stay equal; the renderer positions the bar inside its row
 * and its lane with the two offsets below.
 */
const BAR_HEIGHT = 26;
const BAR_TOP = (ROW_HEIGHT - BAR_HEIGHT) / 2;
const LANE_TOP = (LANE_HEIGHT - BAR_HEIGHT) / 2;

/**
 * Draw the timeline.
 *
 * Rows come from the model, the visible range is derived from the records
 * themselves (a Gantt has no paging), and every position is a percentage of
 * that range, so the layout is resolution independent.
 *
 * Only the rows around the viewport are painted: the core ``useVirtualGrid``
 * hook reports which row indexes are visible (it listens to the scroll of the
 * viewport and to window resizes) and the renderer draws that slice, with a
 * spacer above and below so the scrollbar keeps its true size. The grid lines
 * of the timeline are painted once for the whole range rather than once per
 * row: a render therefore costs a function of the visible rows, not of
 * `records x columns`.
 */
export class GanttSoftRenderer extends Component {
    static template = "soft_gantt.GanttRenderer";
    static props = {
        archInfo: Object,
        records: Array,
        scale: String,
        window: { type: Object, optional: true },
        canEdit: Boolean,
        onBarClick: Function,
        onReschedule: Function,
        // Edge resize, group folding: both are optional so a bare use of the
        // renderer (a test, another view) still mounts without them.
        onResize: { type: Function, optional: true },
        collapsed: { type: Object, optional: true },
        onToggleGroup: { type: Function, optional: true },
    };

    setup() {
        // Set while a drag is being committed, so the click that the browser
        // fires right after the gesture does not open the record as well.
        this.suppressClick = false;

        this.viewportRef = useRef("viewport");
        this.computedRows = null;
        this.syncedRowCount = -1;
        this.syncedHeights = null;
        this.virtualGrid = useVirtualGrid({
            scrollableRef: this.viewportRef,
            bufferCoef: 0.5,
        });

        onWillRender(() => {
            // The rows are rebuilt once per render, and the virtual grid is
            // told their heights so it can tell which ones are visible. A row
            // holding a group has a height of its own, hence the signature of
            // the heights and not just their count.
            this.computedRows = this._buildRows();
            const heights = this.computedRows.map((row) => row.height);
            const signature = heights.join(",");
            if (this.syncedHeights !== signature) {
                this.syncedHeights = signature;
                this.syncedRowCount = heights.length;
                this.virtualGrid.setRowsHeights(heights);
            }
        });
    }

    // ------------------------------------------------------------------
    // Records
    // ------------------------------------------------------------------

    /**
     * Records that can be drawn, with their dates resolved.
     *
     * A record carrying a single date is kept and drawn on that date; a record
     * with no date at all is left out and counted as unscheduled, so it is
     * reported to the user instead of disappearing silently.
     *
     * The result is memoised on the identity of the records array: the getter
     * is read several times per render and parsing every record each time
     * would cost more than drawing them.
     */
    get scheduledRows() {
        if (this._scheduledSource !== this.props.records) {
            this._scheduledSource = this.props.records;
            this._scheduledRows = this._buildScheduledRows();
        }
        return this._scheduledRows;
    }

    _buildScheduledRows() {
        const { dateStart, dateStop, dateStartType, dateStopType } = this.props.archInfo;
        const rows = [];
        for (const record of this.props.records) {
            // A `date` is a calendar day in the user's timezone, a `datetime`
            // an UTC instant: the field's own type decides how it is read.
            let start = parseOdooFieldDate(record[dateStart], dateStartType);
            let stop = parseOdooFieldDate(record[dateStop], dateStopType);
            if (start === null && stop === null) {
                continue;
            }
            if (start === null) {
                start = stop;
            }
            if (stop === null) {
                stop = start;
            }
            if (stop < start) {
                [start, stop] = [stop, start];
            }
            rows.push({
                id: record.id,
                record,
                label: this._label(record),
                start,
                stop,
            });
        }
        return rows;
    }

    /**
     * Text of the row, on the left of the timeline.
     *
     * The view names the field it reads inside its own arch (`label="..."`);
     * without it the record's `display_name` is used, which is what every
     * other view of the model shows.
     */
    _label(record) {
        const { labelField, selectionLabels } = this.props.archInfo;
        if (labelField) {
            const text = fieldText(record[labelField]);
            if (text) {
                // A selection is shown by its label, not by its database key.
                const labels = selectionLabels?.[labelField] || {};
                return labels[text] || text;
            }
        }
        return record.display_name || `#${record.id}`;
    }

    get unscheduledCount() {
        // Records, not rows: with `group_by` a row stands for several records.
        return this.props.records.length - this.scheduledRows.length;
    }

    get unscheduledLabel() {
        return _t("%s record(s) without a date", this.unscheduledCount);
    }

    // ------------------------------------------------------------------
    // Timeline
    // ------------------------------------------------------------------

    /**
     * Visible range.
     *
     * The controller hands over the window the view is on (a whole calendar
     * unit) and that is what the timeline draws, whatever the records span.
     * Without a window (a plain use of the renderer) it falls back to the
     * extent of the records, padded to a whole unit of the current scale.
     */
    get range() {
        if (this.props.window) {
            return this.props.window;
        }
        const rows = this.scheduledRows;
        if (!rows.length) {
            return null;
        }
        const key = `${this.props.scale}:${rows.length}:${rows[0].start}:${rows[0].stop}`;
        if (this._rangeKey === key && this._rangeOwner === rows) {
            return this._range;
        }
        let min = rows[0].start;
        let max = rows[0].stop;
        for (const row of rows) {
            min = Math.min(min, row.start);
            max = Math.max(max, row.stop);
        }
        let range;
        switch (this.props.scale) {
            case "day":
                range = { start: startOfLocalDay(min), end: addLocalDays(startOfLocalDay(max), 1) };
                break;
            case "week":
                range = { start: startOfLocalWeek(min), end: addLocalDays(startOfLocalWeek(max), 7) };
                break;
            default:
                range = {
                    start: startOfLocalMonth(min),
                    end: addLocalMonths(startOfLocalMonth(max), 1),
                };
        }
        this._rangeKey = key;
        this._rangeOwner = rows;
        this._range = range;
        return range;
    }

    /**
     * Both header levels of the timeline, placed as percentages of the range.
     *
     * The cells are the unit the scale is read with (the hours of a day, the
     * days of a week) and the bands above them are the coarser unit that
     * contains them, which is how a Gantt header is read.
     */
    get timeline() {
        const range = this.range;
        if (!range) {
            return { unit: "day", bandUnit: "month", columns: [], bands: [] };
        }
        const key = `${this.props.scale}:${range.start}:${range.end}`;
        if (this._timelineKey === key) {
            return this._timeline;
        }
        const span = range.end - range.start;
        const place = (item) => ({
            key: item.start,
            left: ((item.start - range.start) / span) * 100,
            width: ((item.end - item.start) / span) * 100,
        });
        const { unit, bandUnit, cells, bands } = buildTimeline(
            this.props.scale,
            range.start,
            range.end
        );
        this._timeline = {
            unit,
            bandUnit,
            columns: cells.map((cell) => ({
                ...place(cell),
                label: this._cellLabel(cell.start, unit),
                isWeekend: cell.isWeekend,
            })),
            bands: bands.map((band) => ({
                ...place(band),
                label: this._bandLabel(band.start, bandUnit),
            })),
        };
        this._timelineKey = key;
        return this._timeline;
    }

    get columns() {
        return this.timeline.columns;
    }

    get bands() {
        return this.timeline.bands;
    }

    /** Every drawable row, with its geometry and its bar decoration. */
    get rows() {
        if (!this.computedRows) {
            this.computedRows = this._buildRows();
        }
        return this.computedRows;
    }

    /**
     * The rows to paint, each holding one or more bars.
     *
     * Without `group_by` a row is a record: the plain Gantt. With it a row is a
     * group (a team, a customer) and the records of that group are laid out
     * on lanes along the timeline. That is what a schedule is read for: the
     * group vertically, its dates horizontally.
     */
    _buildRows() {
        const range = this.range;
        if (!range) {
            return [];
        }
        const bars = this.scheduledRows.map((row) => this._buildBar(row, range));
        const groupByField = this.props.archInfo.groupByField;
        if (!groupByField) {
            return bars.map((bar) => ({
                id: `record:${bar.id}`,
                label: bar.label,
                height: ROW_HEIGHT,
                bars: [{ ...bar, top: BAR_TOP }],
            }));
        }
        const groups = new Map();
        for (const bar of bars) {
            // The key identifies the group, the label names it. A many2one is
            // grouped by id: two customers with the same name are two groups,
            // and folding one of them does not fold the other.
            const key = this._groupKey(bar.record, groupByField);
            if (!groups.has(key)) {
                groups.set(key, {
                    key,
                    label: this._groupLabel(bar.record, groupByField, key),
                    bars: [],
                });
            }
            groups.get(key).bars.push(bar);
        }
        return [...groups.values()]
            .sort((a, b) => a.label.localeCompare(b.label, undefined, { numeric: true }))
            .map(({ key, label, bars: groupBars }) => {
                if (this.props.collapsed && this.props.collapsed[key]) {
                    return this._buildCollapsedGroup(key, label, groupBars, range);
                }
                const { packed, laneCount } = packLanes(groupBars);
                return {
                    id: `group:${key}`,
                    key,
                    label,
                    height: laneCount * LANE_HEIGHT,
                    bars: packed.map(({ row, lane }) => ({
                        ...row,
                        // The row already names the group, so the bar names the
                        // record itself.
                        label: row.record.display_name || row.label,
                        title: this._barTitle(row, true),
                        top: lane * LANE_HEIGHT + LANE_TOP,
                    })),
                };
            });
    }

    /**
     * Stable identity of a group.
     *
     * A many2one is identified by its id, not by its display name: two
     * different records may share a name, and the display name can change. The
     * raw value identifies a selection, a char or a number; an unset value is
     * one group of its own (empty key).
     */
    _groupKey(record, fieldName) {
        const value = record[fieldName];
        if (value === false || value === null || value === undefined || value === "") {
            return "";
        }
        if (Array.isArray(value)) {
            // The older `[id, name]` many2one shape.
            return value[0] ? String(value[0]) : "";
        }
        if (typeof value === "object") {
            return value.id ? String(value.id) : "";
        }
        return String(value);
    }

    /** Text of a group's row, read from the record it was built from. */
    _groupLabel(record, fieldName, key) {
        if (!key) {
            return _t("Not set");
        }
        const value = record[fieldName];
        if (Array.isArray(value)) {
            return value[1] || key;
        }
        if (value && typeof value === "object") {
            return value.display_name || value.name || key;
        }
        // The labels come with the arch; a renderer called without them (a
        // test, another view type) still gets the raw value instead of a crash.
        const labels = this.props.archInfo.selectionLabels?.[fieldName] || {};
        if (labels[key]) {
            return labels[key];
        }
        if (key === "true") {
            return _t("Yes");
        }
        if (key === "false") {
            return _t("No");
        }
        return key;
    }

    /**
     * One bar standing for a whole folded group.
     *
     * Folding a team away is how a long plan is read: the single bar still
     * shows when the group works, from its earliest start to its latest stop,
     * so the shape of the plan survives. The count, on the bar and on the row,
     * says how many records are hidden under it. The height is the one lane a
     * collapsed group takes, like any other grouped row.
     *
     * The bar stands for no single record: it cannot be moved or resized, and
     * clicking it unfolds the group again instead of opening a record.
     */
    _buildCollapsedGroup(key, label, groupBars, range) {
        let start = groupBars[0].start;
        let stop = groupBars[0].stop;
        for (const bar of groupBars) {
            start = Math.min(start, bar.start);
            stop = Math.max(stop, bar.stop);
        }
        const snapped = snapToUnit(start, stop, this.timeline.unit);
        // The first bar lends its colour: a folded group keeps the look of its
        // records. It lends nothing else, so the bar cannot be dragged.
        const template = groupBars[0];
        const count = groupBars.length;
        return {
            id: `group:${key}`,
            key,
            collapsed: true,
            label: _t("%s (%s)", label, count),
            height: LANE_HEIGHT,
            bars: [
                {
                    ...template,
                    collapsedGroup: true,
                    groupKey: key,
                    label: _t("%s record(s)", count),
                    title: `${label} (${count})\n${this._formatRange(snapped.start, snapped.stop)}`,
                    geometry: barGeometry(snapped.start, snapped.stop, range.start, range.end),
                    barClass: [template.colorClass, "o_gantt_soft_bar_collapsed"]
                        .filter(Boolean)
                        .join(" "),
                    top: LANE_TOP,
                },
            ],
        };
    }

    /** One bar: its place on the timeline and what makes it readable. */
    _buildBar(row, range) {
        const { progressField, colorField } = this.props.archInfo;
        // A record with no end (or an end equal to its start) is given a real
        // duration first, so the bar is a service rather than a sliver. The
        // timeline draws whole days at every unit but the hour, so a bar is
        // then snapped to the cells it touches before it is placed: an 08:00
        // start lands on the boundary of its day column instead of a sliver
        // inside it. At the hour unit the times are the point of the view and
        // are kept as they are, which is what keeps the one-hour default.
        const duration = ensureDuration(row.start, row.stop, this.timeline.unit);
        const { start, stop } = snapToUnit(duration.start, duration.stop, this.timeline.unit);
        const geometry = barGeometry(start, stop, range.start, range.end);
        let progress = null;
        if (progressField && typeof row.record[progressField] === "number") {
            progress = Math.max(0, Math.min(100, row.record[progressField]));
        }
        let colorClass = "";
        if (colorField) {
            const index = Math.abs(Number(row.record[colorField]) || 0) % COLOR_COUNT;
            colorClass = `o_gantt_soft_color_${index}`;
        }
        // Built here and not in the template: `t-att-class` takes an object
        // or a string, and this version of Owl has no array form.
        const barClass = [colorClass, this.props.canEdit && "o_gantt_soft_bar_draggable"]
            .filter(Boolean)
            .join(" ");
        return {
            ...row,
            geometry,
            progress,
            colorClass,
            barClass,
            title: this._barTitle(row),
            extra: this._extraFields(row),
        };
    }

    // ------------------------------------------------------------------
    // Virtualisation
    // ------------------------------------------------------------------

    /** First and last row index the viewport shows, both inclusive. */
    get rowWindow() {
        const count = this.rows.length;
        const indexes = this.virtualGrid.rowsIndexes;
        if (!indexes || indexes.length !== 2 || !count) {
            return { start: 0, end: count - 1 };
        }
        const [start, end] = indexes;
        return { start: Math.max(0, start), end: Math.min(count - 1, end) };
    }

    get visibleRows() {
        const { start, end } = this.rowWindow;
        return end < start ? [] : this.rows.slice(start, end + 1);
    }

    /**
     * Spacers that keep the scrollbar honest for the rows left unpainted.
     * Rows do not all have the same height once grouped, so they are summed.
     */
    get paddingTop() {
        let height = 0;
        for (let index = 0; index < this.rowWindow.start; index++) {
            height += this.rows[index].height;
        }
        return height;
    }

    get paddingBottom() {
        let height = 0;
        for (let index = this.rowWindow.end + 1; index < this.rows.length; index++) {
            height += this.rows[index].height;
        }
        return height;
    }

    /**
     * Height of the rows area, spacers included.
     *
     * The timeline stretches to the bottom of the viewport so it can hold the
     * today marker at full height, but the column lines must not: a gridline
     * running under the last record, through empty space, reads as another row
     * that is not there. The lines are therefore given the height of the rows
     * and stop where they stop. The spacers stand for the rows left unpainted,
     * so summing the painted rows between them counts every row exactly once.
     */
    get rowsHeight() {
        let height = this.paddingTop + this.paddingBottom;
        for (const row of this.visibleRows) {
            height += row.height;
        }
        return height;
    }

    get todayLeft() {
        const range = this.range;
        if (!range) {
            return null;
        }
        // Today is the user's local day: an evening job six hours ahead of UTC
        // already belongs to tomorrow, and the marker must agree with it.
        const today = startOfLocalDay(Date.now());
        if (today < range.start || today >= range.end) {
            return null;
        }
        return ((today - range.start) / (range.end - range.start)) * 100;
    }

    /**
     * Width of the column today falls in, so the day-column highlight covers
     * exactly that column instead of a guessed fraction. `todayLeft` is the
     * start of the user's local day, the same boundary the day columns are
     * built on, so the match is on the column's own left edge. A scale whose
     * columns are not days (the hour scale) still matches: the cell that holds
     * today is the one to tint. No match leaves the line alone, with no band.
     */
    get todayWidth() {
        const left = this.todayLeft;
        if (left === null) {
            return 0;
        }
        const column = this.columns.find(
            (col) => left >= col.left - 1e-6 && left < col.left + col.width
        );
        return column ? column.width : 0;
    }

    get isEmpty() {
        return this.props.records.length === 0;
    }

    get hasNothingScheduled() {
        return !this.isEmpty && !this.range;
    }

    // ------------------------------------------------------------------
    // Interactions
    // ------------------------------------------------------------------

    /**
     * Clicking the name on the left shows the record it stands for. A row
     * holding a group stands for several records: nothing single to open, the
     * bars are the way in.
     */
    onRowLabelClick(ev, row) {
        if (row.bars.length === 1) {
            this.onBarClick(ev, row.bars[0]);
        }
    }

    /** Fold or unfold a group: the toggle on the left of its row. */
    onToggleGroupClick(ev, key) {
        // The row's own click behaviour must not fire as well.
        ev.stopPropagation();
        if (this.props.onToggleGroup) {
            this.props.onToggleGroup(key);
        }
    }

    /** Tooltip of a group toggle, read before and after the fold. */
    toggleTitle(collapsed) {
        return collapsed ? _t("Expand group") : _t("Collapse group");
    }

    /**
     * Whole days a horizontal travel stands for, at the current range.
     *
     * One day is one column: the row width divided by the number of days the
     * range covers. Both gestures (moving a bar and dragging one of its edges)
     * measure themselves with this, so a drag of the same length always means
     * the same number of days.
     */
    _dayDelta(startX, clientX, rowWidth) {
        const range = this.range;
        if (!range || !rowWidth) {
            return 0;
        }
        const totalDays = Math.round((range.end - range.start) / DAY_MS);
        if (!totalDays) {
            return 0;
        }
        return Math.round(((clientX - startX) / rowWidth) * totalDays);
    }

    /**
     * Ask the controller to show the record's card, anchored on what was
     * clicked (the bar, or its name on the left).
     *
     * The whole bar travels with the event: it already carries the text and the
     * record it stands for, which depends on the view's `label` attribute. A
     * bar standing for a folded group has no single record to open: clicking
     * it unfolds the group.
     */
    onBarClick(ev, row) {
        if (this.suppressClick) {
            this.suppressClick = false;
            return;
        }
        if (row.collapsedGroup) {
            if (this.props.onToggleGroup) {
                this.props.onToggleGroup(row.groupKey);
            }
            return;
        }
        this.props.onBarClick(row, ev.currentTarget);
    }

    /**
     * Drag a bar horizontally to move the record by a whole number of days.
     *
     * The whole gesture stays in pixels; only the release converts the offset
     * into days, which the controller writes for the field's type. A
     * `pointercancel` (a touch gesture taken over by the browser) must leave
     * the bar where it was, with no write and no click swallowed.
     */
    onBarPointerDown(ev, row) {
        if (!this.props.canEdit || ev.button !== 0 || row.collapsedGroup) {
            return;
        }
        const lane = ev.currentTarget.parentElement;
        const laneWidth = lane ? lane.clientWidth : 0;
        const range = this.range;
        if (!laneWidth || !range) {
            return;
        }
        const barEl = ev.currentTarget;
        const startX = ev.clientX;
        const daysFrom = (clientX) => this._dayDelta(startX, clientX, laneWidth);
        const removeListeners = () => {
            window.removeEventListener("pointermove", onPointerMove);
            window.removeEventListener("pointerup", onPointerUp);
            window.removeEventListener("pointercancel", onPointerCancel);
        };

        const onPointerMove = (moveEv) => {
            barEl.style.transform = `translateX(${moveEv.clientX - startX}px)`;
        };
        const onPointerUp = (upEv) => {
            removeListeners();
            barEl.style.transform = "";
            const days = daysFrom(upEv.clientX);
            if (days !== 0) {
                this.suppressClick = true;
                this.props.onReschedule(row.id, days);
            }
        };
        const onPointerCancel = () => {
            removeListeners();
            barEl.style.transform = "";
        };
        window.addEventListener("pointermove", onPointerMove);
        window.addEventListener("pointerup", onPointerUp);
        window.addEventListener("pointercancel", onPointerCancel);
    }

    /**
     * Drag a bar's edge to change one of its two dates.
     *
     * The mirror of the move drag: pixels over the row width, read as whole
     * days at the release. Only the edge being dragged moves, so the preview
     * shifts `left` and `width` for the start and `width` alone for the end,
     * and the bar is never allowed to close on itself: at least one day is
     * kept, which is also what the controller clamps on.
     */
    onResizePointerDown(ev, row, edge) {
        if (!this.props.canEdit || ev.button !== 0) {
            return;
        }
        // The bar has a move handler of its own: it must not start a drag.
        ev.stopPropagation();
        const barEl = ev.currentTarget.parentElement;
        const rowEl = barEl ? barEl.parentElement : null;
        const rowWidth = rowEl ? rowEl.clientWidth : 0;
        const range = this.range;
        if (!barEl || !rowWidth || !range) {
            return;
        }
        const totalDays = Math.round((range.end - range.start) / DAY_MS);
        if (!totalDays) {
            return;
        }
        const dayPercent = 100 / totalDays;
        const startX = ev.clientX;
        const baseLeft = parseFloat(barEl.style.left) || 0;
        const baseWidth = parseFloat(barEl.style.width) || 0;
        const originalLeft = barEl.style.left;
        const originalWidth = barEl.style.width;
        // Shifting the start can only eat the width down to one column, and
        // the same for the end: the bar keeps at least one day.
        const maxShift = Math.max(0, Math.floor(baseWidth / dayPercent - 1));
        const daysFrom = (clientX) => {
            const raw = this._dayDelta(startX, clientX, rowWidth);
            return edge === "start" ? Math.min(raw, maxShift) : Math.max(raw, -maxShift);
        };

        const onPointerMove = (moveEv) => {
            const delta = daysFrom(moveEv.clientX) * dayPercent;
            if (edge === "start") {
                barEl.style.left = `${baseLeft + delta}%`;
                barEl.style.width = `${baseWidth - delta}%`;
            } else {
                barEl.style.width = `${baseWidth + delta}%`;
            }
        };
        const restore = () => {
            barEl.style.left = originalLeft;
            barEl.style.width = originalWidth;
        };
        const removeListeners = () => {
            window.removeEventListener("pointermove", onPointerMove);
            window.removeEventListener("pointerup", onPointerUp);
            window.removeEventListener("pointercancel", onPointerCancel);
        };
        const onPointerUp = (upEv) => {
            removeListeners();
            restore();
            const days = daysFrom(upEv.clientX);
            if (days !== 0) {
                // The click the browser fires after the gesture must not open
                // the record as well.
                this.suppressClick = true;
                if (this.props.onResize) {
                    this.props.onResize(row.id, edge, days);
                }
            }
        };
        const onPointerCancel = () => {
            removeListeners();
            restore();
        };
        window.addEventListener("pointermove", onPointerMove);
        window.addEventListener("pointerup", onPointerUp);
        window.addEventListener("pointercancel", onPointerCancel);
    }

    // ------------------------------------------------------------------
    // Helpers
    // ------------------------------------------------------------------

    /**
     * Label of one cell, read at the unit the timeline is drawn with: the hour
     * of an hour cell, the day and its weekday of a day cell, and so on.
     *
     * The timestamp is read in the user's timezone: `DateTime.fromMillis` uses
     * luxon's default zone, which Odoo sets from the user, so a 07:00 start in
     * Turkey is labelled 07:00 rather than 04:00.
     */
    _cellLabel(timestamp, unit) {
        const date = DateTime.fromMillis(timestamp);
        switch (unit) {
            case "hour":
                return formatDate(date, { format: "HH:mm" });
            case "week":
                return formatDate(date, { format: "dd MMM" });
            case "month":
                return formatDate(date, { format: "MMM yyyy" });
            default:
                // A day is read by its weekday first, its number second.
                return formatDate(date, { format: "dd ccc" });
        }
    }

    /** Label of a band: the week it covers, its day, its month, its quarter. */
    _bandLabel(timestamp, unit) {
        const date = DateTime.fromMillis(timestamp);
        switch (unit) {
            case "week": {
                const end = DateTime.fromMillis(addLocalDays(timestamp, 6));
                return `${formatDate(date, { format: "dd MMM" })} - ${formatDate(end, {
                    format: "dd MMM",
                })}`;
            }
            case "day":
                return formatDate(date, { format: "dd MMM yyyy" });
            case "quarter":
                return formatDate(date, { format: "QQQ yyyy" });
            case "year":
                return formatDate(date, { format: "yyyy" });
            default:
                return formatDate(date, { format: "MMMM yyyy" });
        }
    }

    get todayLabel() {
        return _t("Today");
    }

    _formatRange(start, stop) {
        const from = DateTime.fromMillis(start);
        const to = DateTime.fromMillis(stop);
        return `${formatDate(from, { format: "dd MMM yyyy" })} -> ${formatDate(to, {
            format: "dd MMM yyyy",
        })}`;
    }

    _barTitle(row, withRecordName = false) {
        // The dates the bar covers, not the raw record: they are snapped to
        // the cells the view draws, so a title can never describe a range the
        // bar does not paint (the hour unit snaps nothing and keeps the times).
        const { start: titleStart, stop: titleStop } = snapToUnit(
            row.start,
            row.stop,
            this.timeline.unit
        );
        const lines = [
            withRecordName ? row.record.display_name || row.label : row.label,
            this._formatRange(titleStart, titleStop),
        ];
        const extra = this._extraFields(row);
        if (extra) {
            lines.push(extra);
        }
        return lines.join("\n");
    }

    /** The declared `<field>` nodes, rendered as a one line summary. */
    _extraFields(row) {
        const parts = [];
        const { fieldNodes, selectionLabels } = this.props.archInfo;
        for (const fieldInfo of Object.values(fieldNodes)) {
            let text = fieldText(row.record[fieldInfo.name]);
            if (!text) {
                continue;
            }
            const labels = selectionLabels?.[fieldInfo.name];
            if (labels) {
                text = labels[text] || text;
            }
            parts.push(text);
        }
        return parts.join(" | ");
    }
}
