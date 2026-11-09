import { Component, onMounted, onWillRender, useRef } from "@odoo/owl";
import { formatDate } from "@web/core/l10n/dates";
import { _t } from "@web/core/l10n/translation";
import { evaluateBooleanExpr } from "@web/core/py_js/py";
import { formatFloat, formatInteger } from "@web/views/fields/formatters";
import { useVirtualGrid } from "@web/core/virtual_grid_hook";

import {
    DAY_MS,
    addLocalDays,
    addLocalMonths,
    barGeometry,
    buildTimeline,
    dateTimeInUserZone,
    ensureDuration,
    fieldText,
    packLanes,
    parseOdooFieldDate,
    relationIds,
    snapToPrecision,
    snapToUnit,
    startOfLocalDay,
    startOfLocalMonth,
    startOfLocalWeek,
} from "./gantt_utils";

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
        fields: { type: Object, optional: true },
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
        // Opening the form on an empty cell / a group row, and starting with
        // every group folded: both are optional, so a bare renderer still
        // mounts without them.
        defaultCollapsed: { type: Boolean, optional: true },
        canCellCreate: { type: Boolean, optional: true },
        onCreateAt: { type: Function, optional: true },
    };

    setup() {
        // Set while a drag is being committed, so the click that the browser
        // fires right after the gesture does not open the record as well.
        this.suppressClick = false;

        this.viewportRef = useRef("viewport");
        // The dependency arrows are drawn in pixels over the timeline, so the
        // renderer needs the timeline's own width: a percentage cannot be used
        // as an SVG coordinate without distorting the stroke.
        this.timelineRef = useRef("timeline");
        this.timelineWidth = 0;
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
            this.timelineWidth = this.timelineRef.el?.clientWidth || 0;
            this.computedRows = this._buildRows();
            const heights = this.computedRows.map((row) => row.height);
            const signature = heights.join(",");
            if (this.syncedHeights !== signature) {
                this.syncedHeights = signature;
                this.syncedRowCount = heights.length;
                this.virtualGrid.setRowsHeights(heights);
            }
        });

        // The first render happens before the timeline exists, so its width is
        // still unknown and no arrow is drawn. One render after mount is what
        // measures it; without it the arrows would appear only on the next
        // interaction.
        onMounted(() => {
            if (!this.timelineWidth && this.timelineRef.el?.clientWidth) {
                this.render();
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
        const { dateStart, dateStop, dateStartType, dateStopType, milestoneField, dependenciesField } =
            this.props.archInfo;
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
                // A record the view flagged as a milestone is a point in time,
                // not a duration: it is drawn on its start date.
                milestone: Boolean(milestoneField && record[milestoneField]),
                dependsOn: dependenciesField ? relationIds(record[dependenciesField]) : [],
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
        const parts = this.props.archInfo.precision?.[this.props.scale]?.parts || 1;
        const columns = cells.map((cell) => ({
            ...place(cell),
            start: cell.start,
            end: cell.end,
            label: this._cellLabel(cell.start, unit),
            isWeekend: cell.isWeekend,
        }));
        // The subcells are a *reading* grid inside every column (a quarter hour
        // of the day scale, half a day of the week scale): they do not change
        // the columns, the labels or the window, only how fine the plan reads.
        const subcolumns = [];
        if (parts > 1) {
            for (const column of columns) {
                for (let index = 0; index < parts; index++) {
                    subcolumns.push({
                        key: `${column.key}:${index}`,
                        left: column.left + (column.width * index) / parts,
                        width: column.width / parts,
                    });
                }
            }
        }
        this._timeline = {
            unit,
            bandUnit,
            parts,
            columns,
            subcolumns,
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

    /** The subdivisions of the cells, empty when the scale is read whole. */
    get subcolumns() {
        return this.timeline.subcolumns;
    }

    /** How many subdivisions a cell has (1 when the view does not ask for any). */
    get cellParts() {
        return this.timeline.parts;
    }

    /**
     * Arrows joining the records a `dependencies` list declares.
     *
     * Every arrow joins two bars the viewport paints: a bar that is not drawn
     * (folded group, row scrolled away) has no end an arrow could reach, so the
     * pair is skipped rather than drawn to nowhere. The geometry is in pixels
     * because an SVG stroke cannot be described in percentages without being
     * distorted by the non-uniform scale the coordinates would need.
     *
     * The result is deliberately NOT memoised: it is a loop over the painted
     * bars (a function of the viewport, not of the whole table), and a cache
     * keyed on anything less than the bars themselves keeps drawing the
     * previous coordinates after a bar has been dragged or the records have
     * been reloaded.
     */
    get dependencyArrows() {
        const { start, end } = this.rowWindow;
        if (!this.props.archInfo.dependenciesField || !this.timelineWidth) {
            return [];
        }
        const bars = new Map();
        let top = this.paddingTop;
        for (let index = start; index <= end; index++) {
            const row = this.rows[index];
            if (!row) {
                break;
            }
            for (const bar of row.bars) {
                if (!bar.geometry || bar.collapsedGroup) {
                    continue;
                }
                bars.set(bar.id, {
                    x: (bar.geometry.left / 100) * this.timelineWidth,
                    width: (bar.geometry.width / 100) * this.timelineWidth,
                    y: top + bar.top + BAR_HEIGHT / 2,
                    dependsOn: bar.dependsOn || [],
                });
            }
            top += row.height;
        }
        const arrows = [];
        for (const [id, bar] of bars) {
            for (const blockerId of bar.dependsOn) {
                const blocker = bars.get(blockerId);
                if (!blocker) {
                    continue;
                }
                const x1 = blocker.x + blocker.width;
                const x2 = bar.x;
                const reach = Math.max(24, Math.abs(x2 - x1) / 2);
                arrows.push({
                    key: `${blockerId}:${id}`,
                    d: `M ${x1} ${blocker.y} C ${x1 + reach} ${blocker.y}, ${
                        x2 - reach
                    } ${bar.y}, ${x2} ${bar.y}`,
                });
            }
        }
        return arrows;
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
        const groupByFields = this.groupByFields;
        if (!groupByFields.length) {
            return bars.map((bar) => ({
                id: `record:${bar.id}`,
                label: bar.label,
                height: ROW_HEIGHT,
                bars: [{ ...bar, top: BAR_TOP }],
            }));
        }
        // One level is the one field case of the same recursion: the last level
        // holds the records (the bars), every other level is a row of its own.
        return this._buildGroupRows(bars, range, groupByFields, 0, "", []);
    }

    /** The levels the rows are grouped on, from the outer one to the inner one. */
    get groupByFields() {
        const { groupByFields, groupByField } = this.props.archInfo;
        if (Array.isArray(groupByFields) && groupByFields.length) {
            return groupByFields;
        }
        // A renderer mounted with a single level (a test, another view) still
        // works: the older single field is the one level list.
        return groupByField ? [groupByField] : [];
    }

    /**
     * The rows of one grouping level, recursively.
     *
     * Each level splits the records of its parent group by the value of its
     * field. The inner level holds the bars; the outer levels are header rows
     * that fold their whole subtree into one bar when collapsed. Keys are the
     * path of values ("7|cleaning"), so a value that appears under two parents
     * is two rows and folding one does not fold the other.
     *
     * @param {Array} bars records to group, already drawn
     * @param {Object} range the window
     * @param {string[]} groupByFields all levels
     * @param {number} depth the level being built
     * @param {string} parentKey the key path of the parent group, "" at the top
     * @param {Array} parentValues the group values of the parent path
     * @returns {Array} rows in display order (headers followed by their subtree)
     */
    _buildGroupRows(bars, range, groupByFields, depth, parentKey, parentValues) {
        const fieldName = groupByFields[depth];
        const isLeaf = depth === groupByFields.length - 1;
        const groups = new Map();
        for (const bar of bars) {
            // The key identifies the group, the label names it. A many2one is
            // grouped by id: two customers with the same name are two groups,
            // and folding one of them does not fold the other.
            const valueKey = this._groupKey(bar.record, fieldName);
            if (!groups.has(valueKey)) {
                groups.set(valueKey, {
                    valueKey,
                    label: this._groupLabel(bar.record, fieldName, valueKey),
                    bars: [],
                });
            }
            groups.get(valueKey).bars.push(bar);
        }
        const rows = [];
        const sorted = [...groups.values()].sort((a, b) =>
            a.label.localeCompare(b.label, undefined, { numeric: true })
        );
        for (const { valueKey, label, bars: groupBars } of sorted) {
            const nodeKey = parentKey ? `${parentKey}|${valueKey}` : String(valueKey);
            // The row counts its records (of the whole subtree) and, when the
            // view asks for it, sums a numeric field over them: the summary
            // that makes a folded or expanded group readable at a glance.
            const summary = this._groupSummaryLabel(label, groupBars);
            const groupValues = [...parentValues, { field: fieldName, value: valueKey }];
            // The avatar belongs to the outer level: the arch names a single
            // image field, and the outer row is the one that identifies the
            // plan (a team, a customer).
            const avatarUrl = depth === 0 ? this._groupAvatarUrl(valueKey) : null;
            if (this._isGroupCollapsed(nodeKey, depth)) {
                rows.push(
                    this._buildCollapsedGroup(
                        nodeKey,
                        summary,
                        groupBars,
                        range,
                        avatarUrl,
                        depth,
                        groupValues
                    )
                );
            } else if (isLeaf) {
                rows.push(
                    this._buildLeafGroup(
                        nodeKey,
                        summary,
                        groupBars,
                        avatarUrl,
                        depth,
                        groupValues
                    )
                );
            } else {
                rows.push(
                    this._buildBranchRow(nodeKey, summary, avatarUrl, depth, groupValues)
                );
                rows.push(
                    ...this._buildGroupRows(
                        groupBars,
                        range,
                        groupByFields,
                        depth + 1,
                        nodeKey,
                        groupValues
                    )
                );
            }
        }
        return rows;
    }

    /**
     * The header row of a grouping level that has children.
     *
     * It paints no bar of its own (the records below it do); folding it is what
     * turns the subtree into the single bar of ``_buildCollapsedGroup``.
     */
    _buildBranchRow(nodeKey, label, avatarUrl, depth, groupValues) {
        return {
            id: `group:${nodeKey}`,
            key: nodeKey,
            branch: true,
            // The state the row is drawn in, handed back on a toggle: a group
            // folded by the view's default has no entry in the collapsed map.
            collapsed: false,
            label,
            avatarUrl,
            depth,
            groupValues,
            height: LANE_HEIGHT,
            bars: [],
        };
    }

    /**
     * The innermost group row: the one holding the records.
     *
     * The records are laid out on lanes along the timeline, so two overlapping
     * the same day are two bars, and the row grows instead of hiding one behind
     * the other.
     */
    _buildLeafGroup(nodeKey, label, groupBars, avatarUrl, depth, groupValues) {
        const barsById = new Map(groupBars.map((bar) => [bar.id, bar]));
        const packable = groupBars.map((bar) => ({
            ...bar,
            start: bar.laneStart,
            stop: bar.laneStop,
        }));
        const { packed, laneCount } = packLanes(packable);
        return {
            id: `group:${nodeKey}`,
            key: nodeKey,
            collapsed: false,
            label,
            avatarUrl,
            depth,
            groupValues,
            height: laneCount * LANE_HEIGHT,
            bars: packed.map(({ row, lane }) => {
                // The original bar, not the copy the lanes were packed on: the
                // tooltip and the card describe the record, the card's dates
                // being formatted from its own interval.
                const bar = barsById.get(row.id);
                return {
                    ...bar,
                    // The row already names the group, so the bar names the
                    // record itself.
                    label: bar.record.display_name || bar.label,
                    title: this._barTitle(bar, true),
                    top: lane * LANE_HEIGHT + LANE_TOP,
                };
            }),
        };
    }

    /**
     * Stable identity of a group.
     *
     * A many2one is identified by its id, not by its display name: two
     * different records may share a name, and the display name can change. The
     * raw value identifies a selection, a char or a number; an unset value is
     * one group of its own (empty key).
     */
    /**
     * Whether a group row is folded.
     *
     * An explicit toggle wins. Otherwise ``collapse_first_level`` folds the
     * *outer* level only: a nested row starts open, so folding a team does not
     * also fold every service type inside it when the team is opened again.
     */
    _isGroupCollapsed(key, depth = 0) {
        const { collapsed, defaultCollapsed } = this.props;
        if (collapsed && Object.prototype.hasOwnProperty.call(collapsed, key)) {
            return Boolean(collapsed[key]);
        }
        return depth === 0 && Boolean(defaultCollapsed);
    }

    /**
     * The row label of a group: its name, the number of records it holds and,
     * when the view declares `group_total`, the sum of that field over them.
     * The count is part of the label so a reader knows how much a row stands
     * for without looking at the bars.
     */
    _groupSummaryLabel(label, groupBars) {
        let summary = _t("%s (%s)", label, groupBars.length);
        const fieldName = this.props.archInfo.groupTotalField;
        if (!fieldName) {
            return summary;
        }
        const total = groupBars.reduce(
            (sum, bar) => sum + (Number(bar.record[fieldName]) || 0),
            0
        );
        const field = (this.props.fields || {})[fieldName];
        summary = `${summary} · ${field?.string || fieldName}: ${this._formatTotal(total, field)}`;
        return summary;
    }

    /**
     * A group total, formatted like the field it sums.
     *
     * The formatters read the user's language (grouping, decimal separator),
     * which a renderer mounted outside the web client (a test, another view)
     * does not have: the number is then shown as read, instead of the whole
     * group row failing.
     */
    _formatTotal(total, field) {
        try {
            return field?.type === "integer"
                ? formatInteger(total)
                : formatFloat(total, { field: field || undefined });
        } catch {
            if (field?.type === "integer") {
                return String(total);
            }
            const digits = field?.digits?.[1] ?? 2;
            return String(Number(total.toFixed(digits)));
        }
    }

    /** The avatar of a group row, from the image field the arch names. */
    _groupAvatarUrl(key) {
        const groupByField = this.groupByFields[0];
        const { groupAvatarField } = this.props.archInfo;
        if (!groupByField || !groupAvatarField || !key) {
            return null;
        }
        const field = (this.props.fields || {})[groupByField];
        if (!field?.relation) {
            return null;
        }
        return `/web/image/${field.relation}/${key}/${groupAvatarField}`;
    }

    /**
     * The classes of the decorations whose expression matches a record.
     *
     * The expressions are evaluated on the record the bar stands for, like the
     * `decoration-*` attributes of a list row. An expression the record cannot
     * evaluate (a field that was not read) decorates nothing instead of
     * breaking the timeline.
     */
    _decorationClasses(record) {
        const classes = [];
        for (const { name, condition } of this.props.archInfo.decorations || []) {
            let matches = false;
            try {
                matches = evaluateBooleanExpr(condition, record);
            } catch {
                matches = false;
            }
            if (matches) {
                classes.push(`o_gantt_soft_decoration_${name}`);
            }
        }
        return classes;
    }

    /** Double click on an empty cell: open the form with that cell's dates. */
    onTimelineRowDblClick(ev, row) {
        if (!this.props.canCellCreate || !this.props.onCreateAt) {
            return;
        }
        // A bar has its own gestures (click opens the card, drag reschedules):
        // creating a record under a double clicked bar would be a surprise.
        if (ev.target.closest(".o_gantt_soft_bar")) {
            return;
        }
        const rect = ev.currentTarget.getBoundingClientRect();
        if (!rect.width) {
            return;
        }
        const percent = ((ev.clientX - rect.left) / rect.width) * 100;
        const column =
            this.columns.find((candidate) => percent >= candidate.left && percent < candidate.left + candidate.width) ||
            this.columns[this.columns.length - 1];
        if (!column) {
            return;
        }
        ev.stopPropagation();
        this.props.onCreateAt({ row, start: column.start, stop: column.end });
    }

    /** The "+" of a group row: open the form with the group defaulted. */
    onGroupAddClick(ev, row) {
        ev.stopPropagation();
        if (this.props.onCreateAt) {
            this.props.onCreateAt({ row, start: null, stop: null });
        }
    }

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
    _buildCollapsedGroup(
        key,
        label,
        groupBars,
        range,
        avatarUrl = null,
        depth = 0,
        groupValues = []
    ) {
        let start = groupBars[0].laneStart;
        let stop = groupBars[0].laneStop;
        for (const bar of groupBars) {
            start = Math.min(start, bar.laneStart);
            stop = Math.max(stop, bar.laneStop);
        }
        // The first bar lends its colour: a folded group keeps the look of its
        // records. It lends nothing else, so the bar cannot be dragged.
        const template = groupBars[0];
        const count = groupBars.length;
        return {
            id: `group:${key}`,
            key,
            collapsed: true,
            label,
            avatarUrl,
            depth,
            groupValues,
            height: LANE_HEIGHT,
            bars: [
                {
                    ...template,
                    collapsedGroup: true,
                    groupKey: key,
                    label: _t("%s record(s)", count),
                    title: `${label}\n${this._formatRange(start, stop)}`,
                    geometry: barGeometry(start, stop, range.start, range.end),
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
        const { start, stop } = snapToPrecision(
            duration.start,
            duration.stop,
            this.timeline.unit,
            this.timeline.parts
        );
        // A milestone is a point in time: it is placed on its date and holds no
        // width, so the bar's own box cannot describe a duration it does not
        // have. The diamond itself is drawn by the stylesheet.
        const geometry = row.milestone
            ? { left: this._pointPercent(duration.start, range), width: 0 }
            : barGeometry(start, stop, range.start, range.end);
        let progress = null;
        if (!row.milestone && progressField && typeof row.record[progressField] === "number") {
            progress = Math.max(0, Math.min(100, row.record[progressField]));
        }
        let colorClass = "";
        if (colorField) {
            const index = Math.abs(Number(row.record[colorField]) || 0) % COLOR_COUNT;
            colorClass = `o_gantt_soft_color_${index}`;
        }
        // Built here and not in the template: `t-att-class` takes an object
        // or a string, and this version of Owl has no array form.
        const barClass = [
            colorClass,
            this.props.canEdit && "o_gantt_soft_bar_draggable",
            row.milestone && "o_gantt_soft_bar_milestone",
            ...this._decorationClasses(row.record),
        ]
            .filter(Boolean)
            .join(" ");
        return {
            ...row,
            geometry,
            // The interval the bar actually paints. The lanes of a grouped row
            // are packed on it (two records whose bars overlap on screen must
            // not share a lane, even when their raw times do not); a milestone
            // is a point and holds its instant, never a snapped day.
            laneStart: row.milestone ? duration.start : start,
            laneStop: row.milestone ? duration.start : stop,
            progress,
            colorClass,
            barClass,
            title: row.milestone ? this._milestoneTitle(row) : this._barTitle(row),
            extra: this._extraFields(row),
        };
    }

    /** Where a single instant sits in a range, as a percentage. */
    _pointPercent(timestamp, range) {
        const span = range.end - range.start;
        if (!span) {
            return 0;
        }
        return Math.max(0, Math.min(100, ((timestamp - range.start) / span) * 100));
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
     * Clicking the name on the left shows the record it stands for. Only a row
     * holding one record can do that: a grouped row stands for a group, even
     * when the group happens to hold a single record, and the bars are the way
     * in.
     */
    onRowLabelClick(ev, row) {
        // A click on a row label never follows a bar drag: whatever a previous
        // gesture left behind must not be swallowed here.
        this.suppressClick = false;
        if (row.key === undefined && row.bars.length === 1) {
            this.onBarClick(ev, row.bars[0]);
        }
    }

    /** Fold or unfold a group: the toggle on the left of its row. */
    onToggleGroupClick(ev, row) {
        // The row's own click behaviour must not fire as well.
        ev.stopPropagation();
        if (this.props.onToggleGroup) {
            this.props.onToggleGroup(row.key, Boolean(row.collapsed));
        }
    }

    /** Tooltip of the "+" that creates a record in a group. */
    get newRecordTitle() {
        return _t("New record in this group");
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
                // A collapsed bar is drawn folded: the toggle opens it.
                this.props.onToggleGroup(row.groupKey, true);
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
        // A new gesture starts, so a click suppression left over by a previous
        // drag that ended away from the bar (no click was fired to consume it)
        // must not swallow this interaction.
        this.suppressClick = false;
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
        // As in `onBarPointerDown`: a fresh gesture clears a stale suppression.
        this.suppressClick = false;
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
     * The timestamp is read in the Odoo user's profile timezone, so a 07:00
     * start in Turkey is labelled 07:00 rather than 04:00.
     */
    _cellLabel(timestamp, unit) {
        const date = dateTimeInUserZone(timestamp);
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
        const date = dateTimeInUserZone(timestamp);
        switch (unit) {
            case "week": {
                const end = dateTimeInUserZone(addLocalDays(timestamp, 6));
                return `${formatDate(date, { format: "dd MMM" })} - ${formatDate(end, {
                    format: "dd MMM",
                })}`;
            }
            case "day":
                return formatDate(date, { format: "dd MMM yyyy" });
            case "quarter":
                // Odoo's date formatter does not expand luxon's `QQQ` macro (it
                // prints it literally), so the quarter is written from its
                // number, exactly as the window label is.
                return `Q${date.quarter} ${date.year}`;
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
        const from = dateTimeInUserZone(start);
        const to = dateTimeInUserZone(stop);
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

    /** Title of a milestone: the instant it stands for, not a range. */
    _milestoneTitle(row) {
        const lines = [
            row.record.display_name || row.label,
            `${_t("Milestone")}: ${formatDate(dateTimeInUserZone(row.start), {
                format: "dd MMM yyyy",
            })}`,
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
