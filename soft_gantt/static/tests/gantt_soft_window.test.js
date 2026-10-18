import { after, beforeEach, describe, expect, test } from "@odoo/hoot";

import {
    WINDOW_RANGES,
    formatWindowLabel,
    packLanes,
    shiftWindow,
    windowRange,
} from "@soft_gantt/gantt/gantt_utils";

/** A timestamp, written as the UTC date a human reads. */
const at = (text) => Date.parse(`${text}T00:00:00Z`);
const iso = (timestamp) => new Date(timestamp).toISOString();

/**
 * The windows are read in the user's timezone, and hoot's default zone is not
 * UTC (it is Europe/Brussels): pin it so the UTC-shaped expectations below are
 * exactly the same instant on every machine. The tests that are *about* the
 * timezone set their own zone inside the test.
 */
const ORIGINAL_ZONE = luxon.Settings.defaultZone;
beforeEach(() => {
    luxon.Settings.defaultZone = "UTC";
});
after(() => {
    luxon.Settings.defaultZone = ORIGINAL_ZONE;
});

describe("windowRange", () => {
    test("a day window is that day", () => {
        const { start, end } = windowRange(at("2026-10-07"), "day");
        expect(iso(start)).toBe("2026-10-07T00:00:00.000Z");
        expect(iso(end)).toBe("2026-10-08T00:00:00.000Z");
    });

    test("a week window starts on the Monday", () => {
        // 2026-10-07 is a Wednesday.
        const { start, end } = windowRange(at("2026-10-07"), "week");
        expect(iso(start)).toBe("2026-10-05T00:00:00.000Z");
        expect(iso(end)).toBe("2026-10-12T00:00:00.000Z");
    });

    test("a month window is the calendar month", () => {
        const { start, end } = windowRange(at("2026-10-07"), "month");
        expect(iso(start)).toBe("2026-10-01T00:00:00.000Z");
        expect(iso(end)).toBe("2026-11-01T00:00:00.000Z");
    });

    test("a quarter window is the calendar quarter", () => {
        const { start, end } = windowRange(at("2026-10-07"), "quarter");
        expect(iso(start)).toBe("2026-10-01T00:00:00.000Z");
        expect(iso(end)).toBe("2027-01-01T00:00:00.000Z");
    });

    test("a year window is the calendar year", () => {
        const { start, end } = windowRange(at("2026-10-07"), "year");
        expect(iso(start)).toBe("2026-01-01T00:00:00.000Z");
        expect(iso(end)).toBe("2027-01-01T00:00:00.000Z");
    });

    test("an unknown range falls back to a month", () => {
        const { start, end } = windowRange(at("2026-10-07"), "fortnight");
        expect(iso(start)).toBe("2026-10-01T00:00:00.000Z");
        expect(iso(end)).toBe("2026-11-01T00:00:00.000Z");
    });

    test("windows depend on the date, not on the time of day or the timezone", () => {
        const morning = at("2026-10-07") + 6 * 3600 * 1000;
        const evening = at("2026-10-07") + 23 * 3600 * 1000;
        expect(windowRange(morning, "month")).toEqual(windowRange(evening, "month"));
    });
    test("two records overlapping in time go on two lanes", () => {
        const bars = [
            { id: 1, start: at("2026-03-02"), stop: at("2026-03-06") },
            { id: 2, start: at("2026-03-04"), stop: at("2026-03-09") },
            { id: 3, start: at("2026-03-10"), stop: at("2026-03-11") },
        ];
        const { packed, laneCount } = packLanes(bars);

        expect(laneCount).toBe(2);
        expect(packed.map(({ row, lane }) => [row.id, lane])).toEqual([
            [1, 0],
            [2, 1],
            // The first lane is free again once the first bar is over.
            [3, 0],
        ]);
    });

    test("records that follow each other share one lane", () => {
        const { laneCount } = packLanes([
            { id: 1, start: at("2026-03-02"), stop: at("2026-03-03") },
            { id: 2, start: at("2026-03-03"), stop: at("2026-03-05") },
        ]);

        expect(laneCount).toBe(1);
    });

    test("a bar starting exactly when another ends shares its lane", () => {
        // Touching intervals are not an overlap: drawing them side by side is
        // what a planner reads as "one after the other".
        const { packed, laneCount } = packLanes([
            { id: 1, start: at("2026-03-02"), stop: at("2026-03-05") },
            { id: 2, start: at("2026-03-05"), stop: at("2026-03-08") },
        ]);

        expect(laneCount).toBe(1);
        expect(packed.map(({ lane }) => lane)).toEqual([0, 0]);
    });

    test("an empty group still needs one lane", () => {
        expect(packLanes([])).toEqual({ packed: [], laneCount: 1 });
    });
});

describe("shiftWindow", () => {
    test("moves by one calendar unit, whichever the range", () => {
        const reference = at("2026-10-07");
        expect(iso(windowRange(shiftWindow(reference, "day"), "day").start)).toBe(
            "2026-10-08T00:00:00.000Z"
        );
        expect(iso(windowRange(shiftWindow(reference, "week"), "week").start)).toBe(
            "2026-10-12T00:00:00.000Z"
        );
        expect(iso(windowRange(shiftWindow(reference, "month"), "month").start)).toBe(
            "2026-11-01T00:00:00.000Z"
        );
        expect(iso(windowRange(shiftWindow(reference, "quarter"), "quarter").start)).toBe(
            "2027-01-01T00:00:00.000Z"
        );
        expect(iso(windowRange(shiftWindow(reference, "year"), "year").start)).toBe(
            "2027-01-01T00:00:00.000Z"
        );
    });

    test("goes back with a negative step", () => {
        const reference = at("2026-10-07");
        expect(iso(windowRange(shiftWindow(reference, "month", -1), "month").start)).toBe(
            "2026-09-01T00:00:00.000Z"
        );
    });

    test("windows touch: no gap and no overlap when moving forward", () => {
        const reference = at("2026-10-07");
        for (const range of WINDOW_RANGES) {
            const current = windowRange(reference, range);
            const next = windowRange(shiftWindow(reference, range, 1), range);
            expect(next.start).toBe(current.end);
        }
    });
});

/**
 * The timeline is the user's calendar, not UTC.
 *
 * Turkey is UTC+3 all year, so a start time stored as 04:00-10:00 UTC is a
 * 07:00-13:00 workday there: the columns must read 07:00 and the window must be
 * the local day, or every job is drawn three hours, and sometimes a whole day,
 * away from where the user put it.
 */
describe("the user's calendar", () => {
    const ISTANBUL = "Europe/Istanbul";

    test("a day window is the user's local day", () => {
        // 2026-03-03T00:00Z is 03:00 in Istanbul: the local day it belongs to
        // began three hours earlier, at 21:00Z on the 2nd.
        luxon.Settings.defaultZone = ISTANBUL;
        const { start, end } = windowRange(Date.parse("2026-03-03T00:00:00Z"), "day");
        expect(iso(start)).toBe("2026-03-02T21:00:00.000Z");
        expect(iso(end)).toBe("2026-03-03T21:00:00.000Z");
    });

    test("a week window starts on the user's local Monday", () => {
        luxon.Settings.defaultZone = ISTANBUL;
        // 2026-03-03 is a Tuesday; the local Monday of that week is the 2nd,
        // and its local midnight is 2026-03-01T21:00Z.
        const { start, end } = windowRange(Date.parse("2026-03-03T00:00:00Z"), "week");
        expect(iso(start)).toBe("2026-03-01T21:00:00.000Z");
        expect(iso(end)).toBe("2026-03-08T21:00:00.000Z");
    });

    test("a month window is the user's local month", () => {
        luxon.Settings.defaultZone = ISTANBUL;
        // 22:00Z on the last day of March is 01:00 on the 1st of April there.
        const { start, end } = windowRange(Date.parse("2026-03-31T22:00:00Z"), "month");
        expect(iso(start)).toBe("2026-03-31T21:00:00.000Z");
        expect(iso(end)).toBe("2026-04-30T21:00:00.000Z");
    });

    test("moving a day forward moves exactly one local day", () => {
        luxon.Settings.defaultZone = ISTANBUL;
        const reference = Date.parse("2026-03-03T00:00:00Z");
        // The same local wall clock, one local day later, not 24h earlier or
        // later as a millisecond shift across a DST change would give.
        const { start, end } = windowRange(shiftWindow(reference, "day", 1), "day");
        expect(iso(start)).toBe("2026-03-03T21:00:00.000Z");
        expect(iso(end)).toBe("2026-03-04T21:00:00.000Z");
    });

    test("consecutive local days still touch, across a DST switch", () => {
        // Europe/Brussels switches to summer time on 2026-03-29: the 29th is a
        // 23 hour day. Adding a day must still land on the next local midnight.
        luxon.Settings.defaultZone = "Europe/Brussels";
        const before = windowRange(Date.parse("2026-03-28T12:00:00Z"), "day");
        const after = windowRange(Date.parse("2026-03-29T12:00:00Z"), "day");
        expect(after.start).toBe(before.end);
    });
});

/**
 * The period label names what the reader is actually looking at: a day window
 * is a day, not the month it happens to fall in.
 */
describe("formatWindowLabel", () => {
    const label = (range, reference = at("2026-10-07")) => {
        const { start, end } = windowRange(reference, range);
        return formatWindowLabel(range, start, end);
    };

    test("a day window names its day", () => {
        expect(label("day")).toBe("07 Oct 2026");
    });

    test("a week window names its two ends", () => {
        expect(label("week")).toBe("05 Oct - 11 Oct 2026");
    });

    test("a month window names its month", () => {
        expect(label("month")).toBe("October 2026");
    });

    test("a quarter window names its quarter", () => {
        expect(label("quarter")).toBe("Q4 2026");
    });

    test("a year window names its year", () => {
        expect(label("year")).toBe("2026");
    });

    test("an unknown range falls back to the month shape", () => {
        expect(label("fortnight")).toBe("October 2026");
    });
});
