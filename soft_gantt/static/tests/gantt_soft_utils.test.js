import { after, beforeEach, describe, expect, test } from "@odoo/hoot";
import { user } from "@web/core/user";

import {
    addFieldDays,
    buildCsv,
    clampResize,
    csvEscape,
    fieldText,
    fitWindow,
    formatWindowLabel,
    parseOdooFieldDate,
    relationIds,
    serializeOdooDate,
} from "@soft_gantt/gantt/gantt_utils";

const ORIGINAL_ZONE = luxon.Settings.defaultZone;
const ORIGINAL_TIMEZONE = user.tz;
beforeEach(() => {
    luxon.Settings.defaultZone = "UTC";
    user.updateContext({ tz: "UTC" });
});
after(() => {
    luxon.Settings.defaultZone = ORIGINAL_ZONE;
    user.updateContext({ tz: ORIGINAL_TIMEZONE });
});

describe("fieldText", () => {
    test("a many2one is read from its display_name", () => {
        // The shape the Odoo 17+ relational model hands over. Rendering it as
        // it comes is what produced `[object Object]` on screen.
        expect(fieldText({ id: 7, display_name: "Acme Insaat" })).toBe("Acme Insaat");
    });

    test("the older [id, name] pair still reads", () => {
        expect(fieldText([7, "Acme Insaat"])).toBe("Acme Insaat");
    });

    test("an empty many2one reads as nothing", () => {
        expect(fieldText({ id: false, display_name: false })).toBe("");
    });

    test("a plain value is itself", () => {
        expect(fieldText("Bakim")).toBe("Bakim");
        expect(fieldText(42)).toBe("42");
        expect(fieldText(0)).toBe("0");
    });

    test("nothing at all reads as nothing", () => {
        expect(fieldText(false)).toBe("");
        expect(fieldText(null)).toBe("");
        expect(fieldText(undefined)).toBe("");
    });
});

/**
 * A date is a calendar day in the user's timezone, a datetime an UTC instant.
 * Reading a date as an UTC midnight moves it one day in the Americas, and
 * writing one that way moves it one day in a positive offset.
 */
describe("date and datetime fields", () => {
    test("a date is the user's local day, not an UTC midnight", () => {
        user.updateContext({ tz: "Europe/Istanbul" });
        expect(parseOdooFieldDate("2026-03-05", "date")).toBe(
            Date.parse("2026-03-04T21:00:00Z")
        );

        user.updateContext({ tz: "America/New_York" });
        expect(parseOdooFieldDate("2026-03-05", "date")).toBe(
            Date.parse("2026-03-05T05:00:00Z")
        );
    });

    test("a datetime is an UTC instant, whatever the user's zone", () => {
        user.updateContext({ tz: "Europe/Istanbul" });
        expect(parseOdooFieldDate("2026-03-05 08:00:00", "datetime")).toBe(
            Date.parse("2026-03-05T08:00:00Z")
        );
    });

    test("a date is written as the user's calendar day", () => {
        user.updateContext({ tz: "Europe/Istanbul" });
        const localMidnight = parseOdooFieldDate("2026-03-05", "date");
        expect(serializeOdooDate(localMidnight, "date")).toBe("2026-03-05");
    });

    test("a datetime is written in UTC", () => {
        user.updateContext({ tz: "Europe/Istanbul" });
        const instant = Date.parse("2026-03-05T08:00:00Z");
        expect(serializeOdooDate(instant, "datetime")).toBe("2026-03-05 08:00:00");
    });

    test("moving a date by a day follows the calendar across a DST switch", () => {
        // Europe/Brussels switches to summer time on 2026-03-29: that local day
        // is 23 hours long, and one day later is still the 29th.
        user.updateContext({ tz: "Europe/Brussels" });
        const before = parseOdooFieldDate("2026-03-28", "date");
        expect(serializeOdooDate(addFieldDays(before, 1, "date"), "date")).toBe("2026-03-29");
    });

    test("moving a datetime by a day keeps the UTC time of day", () => {
        const instant = Date.parse("2026-03-28T08:30:00Z");
        expect(serializeOdooDate(addFieldDays(instant, 1, "datetime"), "datetime")).toBe(
            "2026-03-29 08:30:00"
        );
    });

    test("an empty value has no date", () => {
        expect(parseOdooFieldDate(false, "date")).toBe(null);
        expect(parseOdooFieldDate(null, "datetime")).toBe(null);
        expect(parseOdooFieldDate("", "date")).toBe(null);
    });
});

describe("relationIds", () => {
    test("reads the ids of the Odoo 17+ list of objects", () => {
        expect(
            relationIds([
                { id: 3, display_name: "Pour" },
                { id: 9, display_name: "Cure" },
            ])
        ).toEqual([3, 9]);
    });

    test("reads the older [id, name] pairs", () => {
        expect(relationIds([[3, "Pour"], [9, "Cure"]])).toEqual([3, 9]);
    });

    test("an empty list, or a half-written one, gives nothing", () => {
        expect(relationIds(false)).toEqual([]);
        expect(relationIds([])).toEqual([]);
        expect(relationIds([{ id: false }])).toEqual([]);
    });
});

describe("fitWindow", () => {
    test("covers the earliest start and the latest stop, padded to whole days", () => {
        const start = parseOdooFieldDate("2026-03-02 08:00:00", "datetime");
        const stop = parseOdooFieldDate("2026-03-05 12:00:00", "datetime");
        const window = fitWindow([start, start + 1000], [stop]);
        expect(serializeOdooDate(window.start, "datetime")).toBe("2026-03-02 00:00:00");
        expect(serializeOdooDate(window.end, "datetime")).toBe("2026-03-06 00:00:00");
    });

    test("single-date records contribute both ends of the fitted window", () => {
        const earlyStop = parseOdooFieldDate("2026-02-01 00:00:00", "datetime");
        const lateStart = parseOdooFieldDate("2026-03-20 00:00:00", "datetime");
        const window = fitWindow([lateStart], [earlyStop]);

        expect(serializeOdooDate(window.start, "datetime")).toBe("2026-02-01 00:00:00");
        expect(serializeOdooDate(window.end, "datetime")).toBe("2026-03-21 00:00:00");
        expect(fitWindow([lateStart], [])).toEqual({
            start: lateStart,
            end: lateStart + 24 * 60 * 60 * 1000,
        });
        expect(fitWindow([], [earlyStop])).not.toBe(null);

        // A stop-only point at midnight still needs its own day, unlike a real
        // half-open interval that ends at that same instant.
        const stopOnlyWindow = fitWindow([earlyStop, lateStart], [earlyStop, lateStart]);
        expect(stopOnlyWindow.end).toBe(lateStart + 24 * 60 * 60 * 1000);
    });

    test("an end exactly at midnight does not add an empty day", () => {
        const start = parseOdooFieldDate("2026-03-01 00:00:00", "datetime");
        const stop = parseOdooFieldDate("2026-03-02 00:00:00", "datetime");
        expect(fitWindow([start], [stop])).toEqual({ start, end: stop });
    });

    test("nothing to fit gives no window", () => {
        expect(fitWindow([], [])).toBe(null);
    });

    test("a fitted window is named by its two ends", () => {
        const start = parseOdooFieldDate("2026-03-02", "date");
        const end = parseOdooFieldDate("2026-03-06", "date");
        expect(formatWindowLabel("fit", start, end)).toBe("02 Mar 2026 - 05 Mar 2026");
    });
});

describe("CSV export", () => {
    test("a cell holding the separator, a quote or a newline is quoted", () => {
        expect(csvEscape("Kaba yıkama; ince yıkama")).toBe('"Kaba yıkama; ince yıkama"');
        expect(csvEscape('12" boru')).toBe('"12"" boru"');
        expect(csvEscape("iki\nsatır")).toBe('"iki\nsatır"');
        expect(csvEscape("Bakım")).toBe("Bakım");
        expect(csvEscape(false)).toBe("");
    });

    test("formula-like text is neutralized for spreadsheet applications", () => {
        expect(csvEscape("=1+1")).toBe("'=1+1");
        expect(csvEscape("+1+1")).toBe("'+1+1");
        expect(csvEscape("-2+3")).toBe("'-2+3");
        expect(csvEscape("@SUM(1;2)")).toBe("\"'@SUM(1;2)\"");
        expect(csvEscape(" \t=1+1")).toBe("' \t=1+1");
        expect(csvEscape(-12.5)).toBe("-12.5");
    });

    test("the document carries a byte order mark and one line per row", () => {
        const csv = buildCsv(["Name", "Start"], [["Bakım", "02 Mar 2026"]]);
        // Without the BOM Excel reads a UTF-8 file as the local code page.
        expect(csv.startsWith("\ufeff")).toBe(true);
        expect(csv.split("\r\n")).toEqual(["\ufeffName;Start", "Bakım;02 Mar 2026"]);
    });
});

describe("clampResize", () => {
    const value = (text, type = "datetime") => parseOdooFieldDate(text, type);

    test("a value that leaves the interval alone is kept", () => {
        const anchor = value("2026-03-05 09:00:00");
        // A start before the end and an end after the start: nothing to clamp.
        expect(clampResize(value("2026-03-03 10:00:00"), anchor, true, "datetime")).toBe(
            value("2026-03-03 10:00:00")
        );
        expect(clampResize(value("2026-03-07 10:00:00"), anchor, false, "datetime")).toBe(
            value("2026-03-07 10:00:00")
        );
    });

    test("a start dragged past the end stops one day before it", () => {
        const anchor = value("2026-03-05 09:00:00");
        expect(clampResize(value("2026-03-07 10:00:00"), anchor, true, "datetime")).toBe(
            addFieldDays(anchor, -1, "datetime")
        );
    });

    test("an end dragged before the start stops one day after it", () => {
        const anchor = value("2026-03-05 09:00:00");
        expect(clampResize(value("2026-03-05 08:00:00"), anchor, false, "datetime")).toBe(
            addFieldDays(anchor, 1, "datetime")
        );
    });

    test("the day to step is taken in the anchor's own calendar", () => {
        // A `date` anchor is a local calendar day: stepping it is done with the
        // local-day arithmetic, not the UTC one a datetime edge uses. The two
        // ends of a view may be of different types, and the clamp must not
        // compare or step them in the wrong calendar.
        const anchor = value("2026-03-05", "date");
        expect(clampResize(value("2026-03-07 10:00:00"), anchor, true, "date")).toBe(
            addFieldDays(anchor, -1, "date")
        );
    });

    test("a record carrying no anchor is left alone", () => {
        const newValue = value("2026-03-07 10:00:00");
        expect(clampResize(newValue, null, true, "datetime")).toBe(newValue);
    });
});
