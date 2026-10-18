import { after, beforeEach, describe, expect, test } from "@odoo/hoot";

import { buildTimeline, ensureDuration, snapToUnit, windowRange } from "@soft_gantt/gantt/gantt_utils";

/** A UTC timestamp, written as the date a human reads. */
const at = (text) => Date.parse(`${text}T00:00:00Z`);

/** One hour, to place a time inside a day. */
const HOUR = 60 * 60 * 1000;
const DAY = 24 * HOUR;

/**
 * The cells are cut on the user's local calendar and hoot's default zone is not
 * UTC: pin it so the UTC-shaped expectations below hold on every machine. The
 * test that is *about* the timezone sets its own inside the test.
 */
const ORIGINAL_ZONE = luxon.Settings.defaultZone;
beforeEach(() => {
    luxon.Settings.defaultZone = "UTC";
});
after(() => {
    luxon.Settings.defaultZone = ORIGINAL_ZONE;
});

describe("buildTimeline", () => {
    test("a day shows its hours", () => {
        const { unit, cells, bands } = buildTimeline("day", at("2026-03-03"), at("2026-03-04"));

        expect(unit).toBe("hour");
        expect(cells.length).toBe(24);
        expect(cells[0].start).toBe(at("2026-03-03"));
        expect(bands.length).toBe(1);
    });

    test("a week shows its days, weekends flagged", () => {
        // 2026-03-02 is a Monday.
        const { unit, cells, bands } = buildTimeline("week", at("2026-03-02"), at("2026-03-09"));

        expect(unit).toBe("day");
        expect(cells.length).toBe(7);
        expect(cells.map((cell) => cell.isWeekend)).toEqual([
            false,
            false,
            false,
            false,
            false,
            true,
            true,
        ]);
        expect(bands.length).toBe(1);
    });

    test("a month shows its days", () => {
        const { unit, cells, bands } = buildTimeline(
            "month",
            Date.UTC(2026, 2, 1),
            Date.UTC(2026, 3, 1)
        );

        expect(unit).toBe("day");
        expect(cells.length).toBe(31);
        expect(bands.length).toBe(1);
    });

    test("a quarter shows its weeks", () => {
        const { unit, cells } = buildTimeline("quarter", Date.UTC(2026, 0, 1), Date.UTC(2026, 3, 1));

        expect(unit).toBe("week");
        // 13 whole weeks, or 14 when the quarter starts mid week.
        expect(cells.length === 13 || cells.length === 14).toBe(true);
    });

    test("a year shows its months", () => {
        const { unit, cells } = buildTimeline("year", Date.UTC(2026, 0, 1), Date.UTC(2027, 0, 1));

        expect(unit).toBe("month");
        expect(cells.length).toBe(12);
    });

    test("coarsens the unit when the window is too wide to read", () => {
        // A month of hours is 744 stripes nobody can click: days are drawn.
        const { unit, cells } = buildTimeline("day", Date.UTC(2026, 2, 1), Date.UTC(2026, 3, 1));

        expect(unit).toBe("day");
        expect(cells.length).toBe(31);
    });

    test("the bands are never drawn at the unit of the cells", () => {
        for (const scale of ["day", "week", "month", "quarter", "year"]) {
            const { unit, bandUnit } = buildTimeline(
                scale,
                Date.UTC(2026, 2, 1),
                Date.UTC(2026, 3, 1)
            );
            expect(bandUnit).not.toBe(unit);
        }
    });
});

describe("snapToUnit", () => {
    test("leaves the hour view untouched", () => {
        // The hour scale is read by the time of day: moving it would lie.
        const start = at("2026-03-03") + 8 * HOUR;
        const stop = at("2026-03-03") + 12 * HOUR;

        expect(snapToUnit(start, stop, "hour")).toEqual({ start, stop });
    });

    test("a service within one day covers that whole day", () => {
        const start = at("2026-03-03") + 8 * HOUR;
        const stop = at("2026-03-03") + 12 * HOUR;

        const snapped = snapToUnit(start, stop, "day");
        expect(snapped.start).toBe(at("2026-03-03"));
        expect(snapped.stop).toBe(at("2026-03-04"));
    });

    test("a service spanning two days covers both", () => {
        const start = at("2026-03-03") + 8 * HOUR;
        const stop = at("2026-03-04") + 12 * HOUR;

        const snapped = snapToUnit(start, stop, "day");
        expect(snapped.start).toBe(at("2026-03-03"));
        expect(snapped.stop).toBe(at("2026-03-05"));
    });

    test("a record with only a start still gets one day", () => {
        const start = at("2026-03-03") + 8 * HOUR;

        const snapped = snapToUnit(start, null, "day");
        expect(snapped.start).toBe(at("2026-03-03"));
        expect(snapped.stop).toBe(at("2026-03-04"));
    });

    test("nothing at all stays nothing", () => {
        expect(snapToUnit(null, null, "day")).toEqual({ start: null, stop: null });
        expect(snapToUnit(undefined, undefined, "day")).toEqual({
            start: undefined,
            stop: undefined,
        });
    });

    test("a stop exactly on a day boundary is one day, not two", () => {
        // The shape a whole day service is stored in: midnight -> the next
        // midnight. That end is exclusive, so the bar covers one day.
        expect(snapToUnit(at("2026-03-05"), at("2026-03-06"), "day")).toEqual({
            start: at("2026-03-05"),
            stop: at("2026-03-06"),
        });
    });

    test("an empty service sitting on a boundary is given one day", () => {
        expect(snapToUnit(at("2026-03-05"), at("2026-03-05"), "day")).toEqual({
            start: at("2026-03-05"),
            stop: at("2026-03-06"),
        });
    });

    test("never produces a stop before the start", () => {
        // A stop sitting before the start is not a range to keep: the interval
        // collapses to the start's own day instead of inverting.
        const snapped = snapToUnit(at("2026-03-05"), at("2026-03-01"), "day");
        expect(snapped.stop >= snapped.start).toBe(true);
    });
});

/**
 * A record with no end is the norm in the user's data (7,158 of 13,258 rows),
 * and a real service lasts 15 to 120 minutes. A duration has to be invented
 * before the bar is drawn: one hour when the timeline is read in hours, a whole
 * day otherwise (the day snap then turns that into the record's day cell).
 */
describe("ensureDuration", () => {
    test("a start with no end becomes one hour in the hour view", () => {
        const start = at("2026-03-03") + 8 * HOUR;
        expect(ensureDuration(start, null, "hour")).toEqual({ start, stop: start + HOUR });
    });

    test("an end equal to the start becomes one hour in the hour view", () => {
        const start = at("2026-03-03") + 8 * HOUR;
        expect(ensureDuration(start, start, "hour")).toEqual({ start, stop: start + HOUR });
    });

    test("a real 30 minute service is left untouched", () => {
        const start = at("2026-03-03") + 8 * HOUR;
        const stop = start + 30 * 60 * 1000;
        expect(ensureDuration(start, stop, "hour")).toEqual({ start, stop });
    });

    test("a start with no end becomes one whole day in the day view", () => {
        const start = at("2026-03-03") + 8 * HOUR;
        expect(ensureDuration(start, null, "day")).toEqual({ start, stop: start + DAY });
    });

    test("an end before the start is still given a duration", () => {
        const start = at("2026-03-03") + 8 * HOUR;
        expect(ensureDuration(start, start - HOUR, "hour")).toEqual({ start, stop: start + HOUR });
    });

    test("nothing at all stays nothing", () => {
        expect(ensureDuration(null, null, "hour")).toEqual({ start: null, stop: null });
        expect(ensureDuration(undefined, undefined, "hour")).toEqual({
            start: undefined,
            stop: undefined,
        });
    });
});

/**
 * The cells of the timeline are cut on the user's local calendar. A day cell
 * has to start at the user's midnight, or the hours of the day are labelled and
 * placed three hours off in Turkey.
 */
describe("buildTimeline in the user's timezone", () => {
    test("a day cell starts at the user's local midnight", () => {
        luxon.Settings.defaultZone = "Europe/Istanbul";
        const { start, end } = windowRange(Date.parse("2026-03-03T00:00:00Z"), "week");
        // The local Monday is 2026-03-02: midnight there is 2026-03-01T21:00Z.
        const { unit, cells } = buildTimeline("week", start, end);
        expect(unit).toBe("day");
        expect(cells.length).toBe(7);
        expect(cells[0].start).toBe(Date.parse("2026-03-01T21:00:00Z"));
        expect(luxon.DateTime.fromMillis(cells[0].start).hour).toBe(0);
    });

    test("the hours of a local day are labelled in local time", () => {
        luxon.Settings.defaultZone = "Europe/Istanbul";
        const { start, end } = windowRange(Date.parse("2026-03-03T00:00:00Z"), "day");
        const { unit, cells } = buildTimeline("day", start, end);
        expect(unit).toBe("hour");
        expect(cells.length).toBe(24);
        // The first cell is the local midnight, which is 21:00Z the day before.
        expect(cells[0].start).toBe(Date.parse("2026-03-02T21:00:00Z"));
    });
});

