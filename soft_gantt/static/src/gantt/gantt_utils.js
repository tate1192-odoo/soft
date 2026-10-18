/**
 * Date helpers for the Gantt view.
 *
 * Three calendars live in this file and they must not be confused:
 *
 * - A `datetime` record carries an instant, stored in UTC. `parseOdooFieldDate`
 *   reads the UTC string the server sends for a datetime field and
 *   `serializeOdooDate` writes it back unchanged, so a task never shifts by a
 *   day when it is dragged.
 * - A `date` record carries a calendar day, with no timezone. It is read and
 *   written as the user's own day (luxon's default zone, which Odoo sets from
 *   the user), so a deadline of 2026-03-05 is that day in Turkey and that day in
 *   New York, not a UTC midnight that lands on the 4th in the Americas.
 * - The *timeline* is the calendar of the person reading it. The columns of a
 *   Gantt are the hours of their day, the days of their week, the weeks of their
 *   month, so a job starting at 07:00 in Turkey must land in the 07:00 column and
 *   not in a column three hours away. That calendar is built with luxon on the
 *   user's timezone, which also means a DST day is 23 or 25 hours long because
 *   luxon says so, not because this file counted milliseconds.
 *
 * Every function works on millisecond timestamps. The formatting helpers use
 * Odoo's l10n formatters, so a label follows the user's language.
 */

import { formatDate } from "@web/core/l10n/dates";

const { DateTime } = luxon;

export const DAY_MS = 24 * 60 * 60 * 1000;

/** One hour, in milliseconds: the finest unit a timeline draws. */
export const HOUR_MS = 60 * 60 * 1000;

/**
 * Above this many cells a timeline stops being readable, so the finest unit is
 * coarsened one step (hours -> days -> weeks -> months) before drawing it.
 */
const MAX_COLUMNS = 120;

/**
 * Finest unit drawn for each scale.
 *
 * A scale names the context a planner thinks in; the cells show what that
 * context is made of: the hours of a day, the days of a week or of a month, the
 * weeks of a quarter, the months of a year.
 */
export const SCALE_UNITS = {
    day: "hour",
    week: "day",
    month: "day",
    quarter: "week",
    year: "month",
};

/** Window a scale zooms to when the user picks it in the control panel. */
export const SCALE_WINDOWS = {
    day: "day",
    week: "week",
    month: "month",
    quarter: "quarter",
    year: "year",
};

/** The coarsening ladder, finest unit first. */
const UNIT_STEPS = ["hour", "day", "week", "month", "quarter", "year"];

const pad = (value) => String(value).padStart(2, "0");

/**
 * Parse an Odoo datetime string (`2026-05-11 08:30:00`) into an UTC timestamp.
 *
 * A `date` value must be read with `parseOdooFieldDate`, which keeps it on the
 * user's calendar instead of turning it into a UTC midnight.
 *
 * @param {string|number|null|undefined} value
 * @returns {number|null} the timestamp, or null when the value is empty or
 *   cannot be read as a datetime.
 */
export function parseOdooDate(value) {
    if (value === null || value === undefined || value === false || value === "") {
        return null;
    }
    if (typeof value === "number") {
        return Number.isFinite(value) ? value : null;
    }
    const text = String(value).trim().replace("T", " ").replace(/Z$/, "");
    const [datePart, timePart = ""] = text.split(" ");
    const [year, month, day] = datePart.split("-").map(Number);
    if (!year || !month || !day) {
        return null;
    }
    const [hour = 0, minute = 0, second = 0] = timePart.split(":").map(Number);
    const stamp = Date.UTC(year, month - 1, day, hour, minute, second);
    return Number.isNaN(stamp) ? null : stamp;
}

/**
 * Parse a record value for a field of the given type.
 *
 * A datetime is an instant stored in UTC, a date is a calendar day read in the
 * user's timezone. Both come back as a millisecond timestamp so the geometry
 * code has a single representation.
 *
 * @param {string|number|null|undefined} value
 * @param {string} fieldType `date` or `datetime`
 * @returns {number|null}
 */
export function parseOdooFieldDate(value, fieldType) {
    if (fieldType !== "date") {
        return parseOdooDate(value);
    }
    if (value === null || value === undefined || value === false || value === "") {
        return null;
    }
    if (typeof value === "number") {
        return Number.isFinite(value)
            ? DateTime.fromMillis(value).startOf("day").toMillis()
            : null;
    }
    const [year, month, day] = String(value).trim().slice(0, 10).split("-").map(Number);
    if (!year || !month || !day) {
        return null;
    }
    const date = DateTime.fromObject({ year, month, day });
    return date.isValid ? date.toMillis() : null;
}

/** Format a timestamp as an Odoo date: `YYYY-MM-DD`. */
function formatOdooDate(timestamp) {
    const date = new Date(timestamp);
    return `${date.getUTCFullYear()}-${pad(date.getUTCMonth() + 1)}-${pad(date.getUTCDate())}`;
}

/** Format a timestamp as Odoo accepts a datetime: `YYYY-MM-DD HH:MM:SS`. */
function formatOdooDateTime(timestamp) {
    const date = new Date(timestamp);
    return (
        `${formatOdooDate(timestamp)} ` +
        `${pad(date.getUTCHours())}:${pad(date.getUTCMinutes())}:${pad(date.getUTCSeconds())}`
    );
}

/**
 * Serialise a timestamp for a field of the given type.
 *
 * A datetime is written in UTC, the representation the server stores. A date is
 * written as the user's calendar day: formatting the UTC date of a local
 * midnight would write the previous day in a positive UTC offset.
 *
 * @param {number} timestamp
 * @param {string} fieldType `date` or `datetime`
 */
export function serializeOdooDate(timestamp, fieldType) {
    if (fieldType === "date") {
        return DateTime.fromMillis(timestamp).toISODate();
    }
    return formatOdooDateTime(timestamp);
}

/** Shift a timestamp by whole UTC days, keeping the time of day. */
function addUtcDays(timestamp, days) {
    return timestamp + days * DAY_MS;
}

/**
 * Shift a record timestamp by whole days for a field of the given type.
 *
 * A datetime moves by 24 hour steps (the UTC representation never changes with
 * the timezone). A date moves by whole calendar days through luxon, so a DST
 * switch cannot turn "one day later" into 23 or 25 hours that land on another
 * date.
 */
export function addFieldDays(timestamp, days, fieldType) {
    return fieldType === "date" ? addLocalDays(timestamp, days) : addUtcDays(timestamp, days);
}

// ---------------------------------------------------------------------
// The user's calendar
//
// Everything below is bound to the timezone the user reads the screen in
// (`luxon`'s default zone, which Odoo sets from the user). It is what the
// columns of the timeline are made of; the UTC helpers above stay for the
// datetime record values themselves.
// ---------------------------------------------------------------------

/** Start of the user's local day containing the timestamp. */
export function startOfLocalDay(timestamp) {
    return DateTime.fromMillis(timestamp).startOf("day").toMillis();
}

/**
 * Start of the user's local week (Monday) containing the timestamp.
 *
 * Luxon's ISO weekday is 1 for Monday; stepping back by `weekday - 1` days
 * lands on Monday whatever the locale's first day is, and does it through
 * luxon so a week containing a DST switch is still seven local days.
 */
export function startOfLocalWeek(timestamp) {
    const day = DateTime.fromMillis(timestamp).startOf("day");
    return day.minus({ days: day.weekday - 1 }).toMillis();
}

/** First day of the user's local month containing the timestamp. */
export function startOfLocalMonth(timestamp) {
    return DateTime.fromMillis(timestamp).startOf("month").toMillis();
}

/** First day of the user's local quarter containing the timestamp. */
function startOfLocalQuarter(timestamp) {
    return DateTime.fromMillis(timestamp).startOf("quarter").toMillis();
}

/** First day of the user's local year containing the timestamp. */
function startOfLocalYear(timestamp) {
    return DateTime.fromMillis(timestamp).startOf("year").toMillis();
}

/** Shift a timestamp by whole local days, keeping the local time of day. */
export function addLocalDays(timestamp, days) {
    return DateTime.fromMillis(timestamp).plus({ days }).toMillis();
}

/** Shift a timestamp by whole local months, always landing on the 1st. */
export function addLocalMonths(timestamp, months) {
    return DateTime.fromMillis(timestamp).startOf("month").plus({ months }).toMillis();
}

/** Is the timestamp inside a local weekend (Saturday or Sunday)? */
function isLocalWeekend(timestamp) {
    const weekday = DateTime.fromMillis(timestamp).weekday; // 1 = Monday .. 7 = Sunday
    return weekday === 6 || weekday === 7;
}

/** Start of the local hour / day / week / month / quarter / year a timestamp is in. */
function startOfLocalUnit(timestamp, unit) {
    switch (unit) {
        case "hour":
            return DateTime.fromMillis(timestamp).startOf("hour").toMillis();
        case "week":
            return startOfLocalWeek(timestamp);
        case "month":
            return startOfLocalMonth(timestamp);
        case "quarter":
            return startOfLocalQuarter(timestamp);
        case "year":
            return startOfLocalYear(timestamp);
        default:
            return startOfLocalDay(timestamp);
    }
}

/** Move a local unit-aligned timestamp by whole local units. */
function addLocalUnit(timestamp, unit, step = 1) {
    switch (unit) {
        case "hour":
            // Luxon adds an hour of wall clock, so the DST hour that does not
            // exist (or happens twice) is skipped or repeated the way the
            // calendar does it, unlike millisecond arithmetic.
            return DateTime.fromMillis(timestamp).plus({ hours: step }).toMillis();
        case "week":
            return DateTime.fromMillis(timestamp).plus({ weeks: step }).toMillis();
        case "month":
            return addLocalMonths(timestamp, step);
        case "quarter":
            return addLocalMonths(timestamp, 3 * step);
        case "year":
            return addLocalMonths(timestamp, 12 * step);
        default:
            return addLocalDays(timestamp, step);
    }
}

/** The cells of one unit, covering a range. */
function buildUnitCells(unit, rangeStart, rangeEnd) {
    const cells = [];
    let cursor = startOfLocalUnit(rangeStart, unit);
    while (cursor < rangeEnd && cells.length <= MAX_COLUMNS) {
        const end = addLocalUnit(cursor, unit);
        cells.push({
            start: cursor,
            end,
            // Only a unit a weekend falls *inside* can be shaded: a week column
            // contains its own weekend, shading it would shade everything.
            isWeekend: (unit === "hour" || unit === "day") && isLocalWeekend(cursor),
        });
        cursor = end;
    }
    return cells;
}

/** The bands a coarser unit makes out of the cells. */
function buildUnitBands(cells, unit) {
    const bands = [];
    for (const cell of cells) {
        const start = startOfLocalUnit(cell.start, unit);
        const last = bands[bands.length - 1];
        if (last && last.start === start) {
            last.end = cell.end;
        } else {
            bands.push({ start, end: cell.end });
        }
    }
    return bands;
}

/**
 * Both header levels of a timeline: the coarse bands, the cells inside them and
 * the finest unit actually drawn.
 *
 * The unit named by the scale is coarsened while the window would ask for more
 * cells than a screen can show, so a month looked at with the hourly scale is
 * drawn in days rather than 744 stripes. The band unit is always coarser than
 * the cells, so the two rows never repeat each other.
 */
export function buildTimeline(scale, rangeStart, rangeEnd) {
    let unit = SCALE_UNITS[scale] || "day";
    let cells = buildUnitCells(unit, rangeStart, rangeEnd);
    while (cells.length > MAX_COLUMNS && unit !== "month") {
        unit = UNIT_STEPS[UNIT_STEPS.indexOf(unit) + 1];
        cells = buildUnitCells(unit, rangeStart, rangeEnd);
    }
    let bandUnit = SCALE_WINDOWS[scale] || "month";
    if (UNIT_STEPS.indexOf(bandUnit) <= UNIT_STEPS.indexOf(unit)) {
        bandUnit = UNIT_STEPS[Math.min(UNIT_STEPS.indexOf(unit) + 1, UNIT_STEPS.length - 1)];
    }
    return { unit, bandUnit, cells, bands: buildUnitBands(cells, bandUnit) };
}

/**
 * Ranges a window can be aligned on. `month` is what an arch that does not say
 * otherwise gets; the order is not otherwise significant.
 */
export const WINDOW_RANGES = ["month", "day", "week", "quarter", "year"];

/**
 * The window a given range covers around a reference date.
 *
 * A window is a *whole* calendar unit, not "30 days from today": each unit
 * starts where the calendar starts it (the first of the month, the Monday, the
 * first of January), so moving from one window to the next never leaves a gap
 * and never shows the same day twice. The unit is read in the user's timezone:
 * the hours of *their* day and the days of *their* week are what the columns
 * show, so a Turkish user at 07:00 local must see 07:00 in the first column and
 * not 04:00.
 *
 * @param {number} reference a timestamp inside the window
 * @param {string} range one of `WINDOW_RANGES`
 * @returns {{start: number, end: number}} half open, `end` excluded
 */
export function windowRange(reference, range = "month") {
    switch (range) {
        case "day": {
            const start = startOfLocalDay(reference);
            return { start, end: addLocalDays(start, 1) };
        }
        case "week": {
            const start = startOfLocalWeek(reference);
            return { start, end: addLocalDays(start, 7) };
        }
        case "quarter": {
            const start = startOfLocalQuarter(reference);
            return { start, end: addLocalMonths(start, 3) };
        }
        case "year": {
            const start = startOfLocalYear(reference);
            return { start, end: addLocalMonths(start, 12) };
        }
        default: {
            const start = startOfLocalMonth(reference);
            return { start, end: addLocalMonths(start, 1) };
        }
    }
}

/**
 * Move a reference date by whole windows, for the previous / next buttons.
 *
 * @param {number} reference a timestamp inside the current window
 * @param {string} range one of `WINDOW_RANGES`
 * @param {number} steps how many windows to move, negative to go back
 * @returns {number} a timestamp inside the target window
 */
export function shiftWindow(reference, range = "month", steps = 1) {
    switch (range) {
        case "day":
            return addLocalDays(reference, steps);
        case "week":
            return addLocalDays(reference, 7 * steps);
        case "quarter":
            return addLocalMonths(reference, 3 * steps);
        case "year":
            return addLocalMonths(reference, 12 * steps);
        default:
            return addLocalMonths(reference, steps);
    }
}

/**
 * The label of the period shown between the arrows of the control panel.
 *
 * The format follows the range, not the dates: a day window reads as a day, a
 * week as its two ends, a month as its name, a quarter as Qn and a year as the
 * year. Formatting a day window with the month-only shape would tell a reader
 * looking at a single day that they are looking at a whole month.
 *
 * @param {string} range one of `WINDOW_RANGES`
 * @param {number} start window start timestamp
 * @param {number} end window end timestamp, excluded
 */
export function formatWindowLabel(range, start, end) {
    const from = DateTime.fromMillis(start);
    const to = DateTime.fromMillis(end - 1);
    switch (range) {
        case "day":
            return formatDate(from, { format: "dd MMM yyyy" });
        case "week":
            return (
                `${formatDate(from, { format: "dd MMM" })} - ` +
                `${formatDate(to, { format: "dd MMM yyyy" })}`
            );
        case "quarter":
            // Odoo's date formatter does not expand luxon's `QQQ` macro, so
            // the quarter is written from its number.
            return `Q${from.quarter} ${from.year}`;
        case "year":
            return formatDate(from, { format: "yyyy" });
        default:
            return formatDate(from, { format: "MMMM yyyy" });
    }
}

/**
 * A field value as the text a user reads.
 *
 * A many2one comes as `{id, display_name}` from the Odoo 17+ relational model
 * (the older `[id, name]` pair is still accepted, other code paths hand it
 * over), a date as its raw string, everything else as itself. Without this a
 * many2one is rendered as `[object Object]`.
 */
export function fieldText(value) {
    if (value === false || value === null || value === undefined) {
        return "";
    }
    if (Array.isArray(value)) {
        return fieldText(value[1] ?? false);
    }
    if (typeof value === "object") {
        // An empty many2one comes as `{id: false, display_name: false}`: a
        // falsy name is empty, not the text "false".
        return fieldText(value.display_name ?? value.name ?? false);
    }
    return String(value);
}

/**
 * Lay the bars of one row out on lanes.
 *
 * Two records overlapping in time would otherwise be drawn on top of each
 * other: sorted by start, each bar takes the first lane that is free when it
 * starts, so a row uses as many lanes as its busiest moment needs and no more.
 *
 * @param {Array} bars drawable rows, each with `start`, `stop` and `id`
 * @returns {{packed: Array<{row: object, lane: integer}>, laneCount: integer}}
 */
export function packLanes(bars) {
    const laneEnds = [];
    const packed = [];
    for (const bar of [...bars].sort((a, b) => a.start - b.start || a.id - b.id)) {
        let lane = laneEnds.findIndex((end) => end <= bar.start);
        if (lane === -1) {
            lane = laneEnds.length;
        }
        laneEnds[lane] = bar.stop;
        packed.push({ row: bar, lane });
    }
    return { packed, laneCount: Math.max(laneEnds.length, 1) };
}

/**
 * Snap a record's interval to the cells a timeline draws.
 *
 * A day / week / month view is read in whole days, but a datetime record
 * carries a time of day (a service from 08:00 to 12:00, say). Drawn as it
 * comes, such a bar starts an eighth of the way into its day cell and reads as
 * shifted off the grid. Rounding the start down to its day and the stop up to
 * the end of its day makes the record cover exactly the cells it touches. The
 * hour view is left alone on purpose: an hour is a point on the axis and moving
 * it would lie about the schedule.
 *
 * @param {number|null|undefined} start
 * @param {number|null|undefined} stop
 * @param {string} unit the unit the timeline is drawn with
 * @returns {{start: (number|null|undefined), stop: (number|null|undefined)}}
 */
export function snapToUnit(start, stop, unit) {
    if (unit === "hour") {
        return { start, stop };
    }
    const hasStart = start !== null && start !== undefined;
    const hasStop = stop !== null && stop !== undefined;
    if (!hasStart && !hasStop) {
        return { start, stop };
    }
    // A record carrying a single date is a one day service: the missing end is
    // the day of the one that is there. The day is the local day, the same one
    // the columns are cut on, so the bar covers exactly the cells it touches.
    const from = startOfLocalDay(hasStart ? start : stop);
    // The interval is half open, so a stop sitting exactly on a day boundary
    // already ends the range and must NOT be rounded up to the next day: a
    // record stored as "day -> next day midnight" covers one day, not two.
    // Only a stop strictly inside a day is rounded up to that day's end. A
    // range whose end is not after its start (inverted, or a single instant)
    // collapses to one day from the start rather than inverting the interval.
    const floorStop = startOfLocalDay(hasStop ? stop : start);
    const atBoundary = hasStop && stop === floorStop;
    const rawTo = atBoundary ? floorStop : addLocalDays(floorStop, 1);
    const to = rawTo > from ? rawTo : addLocalDays(from, 1);
    return { start: from, stop: to };
}

/**
 * Give a record a duration before it is drawn.
 *
 * A record routinely carries a start and no end, and a few carry an end equal
 * to the start. Drawn as they come they would be a zero-width sliver or, worse,
 * the whole day the bar geometry invents to keep them visible. A service is a
 * duration, not a point, so a start with no believable end is extended by one
 * hour when the timeline is read in hours, and by one day otherwise (the day
 * snap right after this turns that into the record's whole day cell anyway).
 *
 * Nulls are left alone: a record with no start has nothing to extend from.
 *
 * @param {number|null|undefined} start
 * @param {number|null|undefined} stop
 * @param {string} unit the unit the timeline is drawn with
 * @returns {{start: (number|null|undefined), stop: (number|null|undefined)}}
 */
export function ensureDuration(start, stop, unit) {
    if (start === null || start === undefined) {
        return { start, stop };
    }
    if (stop === null || stop === undefined || stop <= start) {
        return { start, stop: start + (unit === "hour" ? HOUR_MS : DAY_MS) };
    }
    return { start, stop };
}

/**
 * Position of a bar inside a range, as percentages.
 *
 * The two ends are clamped to the range, so a record that starts before the
 * window (or ends after it) is drawn as reaching the edge instead of
 * disappearing, and a zero length record is given one day so it stays visible.
 */
export function barGeometry(start, stop, rangeStart, rangeEnd) {
    const span = rangeEnd - rangeStart;
    if (!span) {
        return null;
    }
    let from = start;
    let to = stop;
    if (to < from) {
        [from, to] = [to, from];
    }
    if (to === from) {
        to = from + DAY_MS;
    }
    const left = ((from - rangeStart) / span) * 100;
    const width = ((to - from) / span) * 100;
    const clampedLeft = Math.max(0, Math.min(100, left));
    const clampedWidth = Math.max(0.5, Math.min(100 - clampedLeft, width));
    return { left: clampedLeft, width: clampedWidth };
}
