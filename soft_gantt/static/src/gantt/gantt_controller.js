import { Component, useState } from "@odoo/owl";

import { useBus, useService } from "@web/core/utils/hooks";
import { _t } from "@web/core/l10n/translation";
import { formatDate, formatDateTime, parseDate, parseDateTime } from "@web/core/l10n/dates";
import { usePopover } from "@web/core/popover/popover_hook";
import { useModel } from "@web/model/model";
import {
    addFieldDependencies,
    extractFieldsFromArchInfo,
    makeActiveField,
} from "@web/model/relational_model/utils";
import { useSetupAction } from "@web/search/action_hook";
import { CogMenu } from "@web/search/cog_menu/cog_menu";
import { Layout } from "@web/search/layout";
import { SearchBar } from "@web/search/search_bar/search_bar";
import { useSearchBarToggler } from "@web/search/search_bar/search_bar_toggler";
import { standardViewProps } from "@web/views/standard_view_props";

import { addFieldDays, fieldText, formatWindowLabel, parseOdooFieldDate, serializeOdooDate, shiftWindow, windowRange, SCALE_WINDOWS, WINDOW_RANGES } from "./gantt_utils";
import { GanttSoftPopover } from "./gantt_popover";

const SCALE_LABELS = {
    day: _t("Day"),
    week: _t("Week"),
    month: _t("Month"),
};

/**
 * Controller of the Gantt view.
 *
 * It owns the search integration (the records come from the action domain plus
 * the search bar), the current scale, and the two writes the renderer can ask
 * for: opening a record and rescheduling it.
 */
export class GanttSoftController extends Component {
    static template = "soft_gantt.GanttController";
    static components = { Layout, SearchBar, CogMenu };
    static props = {
        ...standardViewProps,
        Model: Function,
        Renderer: Function,
        archInfo: Object,
    };

    setup() {
        this.orm = useService("orm");
        this.notification = useService("notification");
        // The card is anchored on the bar it belongs to, and escapes the view
        // when a click would otherwise take the reader to another screen. Its
        // own container class is what lets the stylesheet theme the card (and
        // nothing else) when the view is dark.
        this.popover = usePopover(GanttSoftPopover, {
            position: "right-start",
            popoverClass: "o_gantt_soft_popover_host",
        });

        const archInfo = this.props.archInfo;
        const { activeFields, fields } = extractFieldsFromArchInfo(archInfo, this.props.fields);

        // Fields the view needs beyond the ones it declares: the two dates, the
        // bar label, and the optional progress / colour fields.
        const requiredFields = [
            "display_name",
            archInfo.dateStart,
            archInfo.dateStop,
            archInfo.labelField,
            archInfo.progressField,
            archInfo.colorField,
            archInfo.groupByField,
        ].filter(Boolean);
        for (const name of requiredFields) {
            if (!activeFields[name]) {
                activeFields[name] = makeActiveField();
            }
        }
        addFieldDependencies(
            activeFields,
            fields,
            requiredFields.map((name) => ({ name }))
        );

        const scale = archInfo.scales.includes(this.props.state?.scale)
            ? this.props.state.scale
            : archInfo.scale;
        // The window is kept as a reference date: which calendar unit it covers
        // depends on the range, and that is derived from it everywhere else.
        const windowStart = Number.isFinite(this.props.state?.windowStart)
            ? this.props.state.windowStart
            : Date.now();
        // `range` is the length of the window: the view opens on the one its
        // arch asks for, and picking a scale zooms to that scale's own window.
        const range = WINDOW_RANGES.includes(this.props.state?.range)
            ? this.props.state.range
            : archInfo.range || "month";
        // `collapsedGroups` folds grouped rows away and survives re-renders:
        // its keys are the stable group keys computed by the renderer (an id
        // for a many2one, the raw value otherwise, empty string for "Not set").
        this.state = useState({ scale, windowStart, range, collapsedGroups: {} });

        this.model = useModel(this.props.Model, {
            resModel: this.props.resModel,
            archInfo,
            fields: this.props.fields,
            activeFields,
            domain: this.props.domain,
            context: this.props.context,
            window: this.window,
        });
        useBus(this.model.bus, "update", () => this.render());

        this.searchBarToggler = useSearchBarToggler();

        useSetupAction({
            getLocalState: () => ({
                scale: this.state.scale,
                windowStart: this.state.windowStart,
                range: this.state.range,
            }),
        });
    }

    get rendererProps() {
        return {
            archInfo: this.props.archInfo,
            records: this.model.records,
            scale: this.state.scale,
            window: this.window,
            canEdit: this.canEdit,
            collapsed: this.state.collapsedGroups,
            onBarClick: this.onBarClick.bind(this),
            onReschedule: this.onReschedule.bind(this),
            onResize: this.onResize.bind(this),
            onToggleGroup: this.onToggleGroup.bind(this),
        };
    }

    /** The window the view is on: a whole calendar unit around a reference date. */
    get window() {
        return windowRange(this.state.windowStart, this.state.range);
    }

    /** Readable name of the current window, shown between the arrows. */
    get windowLabel() {
        // The format follows the range: a day window reads as a day, a month
        // window as its name. Formatting a day window with the month shape
        // would name a month the reader is not looking at.
        const { start, end } = this.window;
        return formatWindowLabel(this.state.range, start, end);
    }

    previousWindow() {
        this._showWindow(shiftWindow(this.state.windowStart, this.state.range, -1));
    }

    get previousTitle() {
        return _t("Previous period");
    }

    get todayTitle() {
        return _t("Show the period containing today");
    }

    get nextTitle() {
        return _t("Next period");
    }

    nextWindow() {
        this._showWindow(shiftWindow(this.state.windowStart, this.state.range, 1));
    }

    todayWindow() {
        this._showWindow(Date.now());
    }

    /**
     * Move to the window containing a date and read it.
     *
     * The record read is bounded by the window, so this is what keeps the view
     * on a table of thousands of records: only one calendar unit is fetched,
     * and the arrows are the paging.
     */
    _showWindow(reference) {
        this.state.windowStart = reference;
        this.model.setWindow(this.window);
    }

    get canEdit() {
        // The writable right is written into the arch by the server and read
        // by the arch parser into `activeActions`; it is not part of the view
        // `info` object.
        return Boolean(this.props.archInfo.activeActions?.edit);
    }

    scaleLabel(scale) {
        return SCALE_LABELS[scale] || scale;
    }

    /**
     * Picking a scale is a zoom: the window follows it, so a day shows the hours
     * of one day rather than a month of them.
     */
    setScale(scale) {
        this.state.scale = scale;
        this.state.range = SCALE_WINDOWS[scale] || this.state.range;
        this.model.setWindow(this.window);
    }

    onBarClick(row, element) {
        // `open_form_view="1"` asks for the form instead of the card, the same
        // meaning it has in the other views.
        if (this.props.archInfo.openFormView && this.props.selectRecord) {
            this.props.selectRecord(row.id, {});
            return;
        }
        this.popover.open(element, {
            title: row.label,
            fields: this._popoverFields(row.record),
            open: () => {
                this.popover.close();
                if (this.props.selectRecord) {
                    this.props.selectRecord(row.id, {});
                }
            },
        });
    }

    /**
     * The label / value pairs the card shows for a record: the two dates, then
     * every field the view declared, in the order the arch lists them.
     */
    _popoverFields(record) {
        const { archInfo, fields } = this.props;
        const rows = [];
        const add = (name, value) => {
            if (value === false || value === null || value === undefined || value === "") {
                return;
            }
            rows.push({ label: fields[name]?.string || name, value: String(value) });
        };
        for (const [name, type] of [
            [archInfo.dateStart, archInfo.dateStartType],
            [archInfo.dateStop, archInfo.dateStopType],
        ]) {
            const raw = record[name];
            if (!raw) {
                continue;
            }
            // `date` fields carry no time part, and the two are formatted with
            // the user's own formats and timezone.
            const parsed = (type === "date" ? parseDate : parseDateTime)(raw);
            add(name, parsed && (type === "date" ? formatDate : formatDateTime)(parsed));
        }
        for (const fieldInfo of Object.values(archInfo.fieldNodes)) {
            add(fieldInfo.name, this._fieldValue(fieldInfo.name, record[fieldInfo.name]));
        }
        return rows;
    }

    /** A record value as text: dates, booleans, selections and many2ones included. */
    _fieldValue(name, value) {
        const field = this.props.fields[name];
        if (value === false || value === null || value === undefined || value === "") {
            return "";
        }
        if (field?.type === "selection") {
            const option = (field.selection || []).find(([key]) => key === value);
            return option ? option[1] : value;
        }
        if (field?.type === "date") {
            const parsed = parseDate(value);
            return parsed ? formatDate(parsed) : String(value);
        }
        if (field?.type === "datetime") {
            const parsed = parseDateTime(value);
            return parsed ? formatDateTime(parsed) : String(value);
        }
        if (field?.type === "boolean") {
            return value ? _t("Yes") : _t("No");
        }
        return fieldText(value);
    }

    /**
     * Move a record by a whole number of days.
     *
     * Both dates are shifted together so the duration is preserved. Each value
     * is read and written for the field's own type: a datetime stays an UTC
     * instant, a date stays the user's calendar day. A date the record does
     * not carry is left untouched.
     */
    async onReschedule(recordId, days) {
        const archInfo = this.props.archInfo;
        const record = this.model.records.find((rec) => rec.id === recordId);
        if (!record) {
            return;
        }
        const values = {};
        for (const [fieldName, fieldType] of [
            [archInfo.dateStart, archInfo.dateStartType],
            [archInfo.dateStop, archInfo.dateStopType],
        ]) {
            const timestamp = parseOdooFieldDate(record[fieldName], fieldType);
            if (timestamp === null) {
                continue;
            }
            values[fieldName] = serializeOdooDate(
                addFieldDays(timestamp, days, fieldType),
                fieldType
            );
        }
        if (!Object.keys(values).length) {
            return;
        }
        try {
            await this.orm.write(this.props.resModel, [recordId], values, {
                context: this.model.context,
            });
        } catch (error) {
            this.notification.add(error.message || error.toString(), { type: "danger" });
        }
        await this.model.reload();
    }

    /**
     * Change one end of a record by a whole number of days.
     *
     * Only the date on the edge being dragged moves; the other one anchors the
     * interval, so a resize can never invert it: when the new value would pass
     * the anchor, it is clamped to leave the record one day long. The value is
     * read and serialised for the field's own type.
     *
     * @param {number} recordId
     * @param {string} edge `start` or `end`
     * @param {number} days signed, whole days
     */
    async onResize(recordId, edge, days) {
        if (!days) {
            return;
        }
        const archInfo = this.props.archInfo;
        const record = this.model.records.find((rec) => rec.id === recordId);
        if (!record) {
            return;
        }
        const isStart = edge === "start";
        const fieldName = isStart ? archInfo.dateStart : archInfo.dateStop;
        const fieldType = isStart ? archInfo.dateStartType : archInfo.dateStopType;
        const anchorName = isStart ? archInfo.dateStop : archInfo.dateStart;
        const timestamp = parseOdooFieldDate(record[fieldName], fieldType);
        if (timestamp === null) {
            return;
        }
        let value = addFieldDays(timestamp, days, fieldType);
        const anchor = parseOdooFieldDate(record[anchorName], fieldType);
        if (anchor !== null) {
            // One day is the shortest interval a resize may leave behind.
            if (isStart && value > anchor) {
                value = addFieldDays(anchor, -1, fieldType);
            } else if (!isStart && value < anchor) {
                value = addFieldDays(anchor, 1, fieldType);
            }
        }
        try {
            await this.orm.write(
                this.props.resModel,
                [recordId],
                { [fieldName]: serializeOdooDate(value, fieldType) },
                { context: this.model.context }
            );
        } catch (error) {
            this.notification.add(error.message || error.toString(), { type: "danger" });
        }
        await this.model.reload();
    }

    /**
     * Fold a group away or show it again.
     *
     * The collapsed set lives in the view state, so it survives a re-render
     * and follows the reader through the scale and the window. A useState
     * object is reactive key by key, so writing straight into it is enough.
     */
    onToggleGroup(key) {
        this.state.collapsedGroups[key] = !this.state.collapsedGroups[key];
    }
}
