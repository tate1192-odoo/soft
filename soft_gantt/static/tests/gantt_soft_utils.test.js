import { after, beforeEach, describe, expect, test } from "@odoo/hoot";

import {
    addFieldDays,
    fieldText,
    parseOdooFieldDate,
    serializeOdooDate,
} from "@soft_gantt/gantt/gantt_utils";

const ORIGINAL_ZONE = luxon.Settings.defaultZone;
beforeEach(() => {
    luxon.Settings.defaultZone = "UTC";
});
after(() => {
    luxon.Settings.defaultZone = ORIGINAL_ZONE;
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
        luxon.Settings.defaultZone = "Europe/Istanbul";
        expect(parseOdooFieldDate("2026-03-05", "date")).toBe(
            Date.parse("2026-03-04T21:00:00Z")
        );

        luxon.Settings.defaultZone = "America/New_York";
        expect(parseOdooFieldDate("2026-03-05", "date")).toBe(
            Date.parse("2026-03-05T05:00:00Z")
        );
    });

    test("a datetime is an UTC instant, whatever the user's zone", () => {
        luxon.Settings.defaultZone = "Europe/Istanbul";
        expect(parseOdooFieldDate("2026-03-05 08:00:00", "datetime")).toBe(
            Date.parse("2026-03-05T08:00:00Z")
        );
    });

    test("a date is written as the user's calendar day", () => {
        luxon.Settings.defaultZone = "Europe/Istanbul";
        const localMidnight = parseOdooFieldDate("2026-03-05", "date");
        expect(serializeOdooDate(localMidnight, "date")).toBe("2026-03-05");
    });

    test("a datetime is written in UTC", () => {
        luxon.Settings.defaultZone = "Europe/Istanbul";
        const instant = Date.parse("2026-03-05T08:00:00Z");
        expect(serializeOdooDate(instant, "datetime")).toBe("2026-03-05 08:00:00");
    });

    test("moving a date by a day follows the calendar across a DST switch", () => {
        // Europe/Brussels switches to summer time on 2026-03-29: that local day
        // is 23 hours long, and one day later is still the 29th.
        luxon.Settings.defaultZone = "Europe/Brussels";
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
