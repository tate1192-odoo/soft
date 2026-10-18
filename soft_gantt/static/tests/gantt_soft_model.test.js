import { after, beforeEach, describe, expect, test } from "@odoo/hoot";

import { GanttSoftModel } from "@soft_gantt/gantt/gantt_model";
import { windowRange } from "@soft_gantt/gantt/gantt_utils";

const ORIGINAL_ZONE = luxon.Settings.defaultZone;
beforeEach(() => {
    luxon.Settings.defaultZone = "UTC";
});
after(() => {
    luxon.Settings.defaultZone = ORIGINAL_ZONE;
});

/**
 * A domain sent to the server must be a valid prefix expression. This is the
 * regression that matters most: a hand built list once came out as
 * `[A, "|", B, "&", C]`, which the server refuses with
 * `ValueError: Domain() malformed domain` before reading a single record.
 */
function isPrefixDomain(domain) {
    let expected = 1;
    for (const token of domain) {
        if (Array.isArray(token)) {
            expected -= 1;
        } else if (token === "&" || token === "|") {
            expected += 1;
        } else if (token === "!") {
            expected += 0;
        } else {
            return false;
        }
        if (expected < 0) {
            return false;
        }
    }
    return expected === 0;
}

const FIELDS = {
    name: { type: "char" },
    display_name: { type: "char" },
    date_start: { type: "datetime" },
    date_deadline: { type: "datetime" },
    planned_date: { type: "date" },
};

const ACTIVE_FIELDS = {
    name: {},
    display_name: {},
    date_start: {},
    date_deadline: {},
    planned_date: {},
};

function makeArchInfo(overrides = {}) {
    return {
        dateStart: "date_start",
        dateStartType: "datetime",
        dateStop: "date_deadline",
        dateStopType: "datetime",
        defaultOrder: [{ name: "date_start", asc: true }],
        limit: 500,
        ...overrides,
    };
}

function makeModel({ archInfo = makeArchInfo(), orm } = {}) {
    const calls = [];
    const fakeOrm = orm || {
        webSearchRead: async (resModel, domain, kwargs) => {
            calls.push({ resModel, domain, kwargs });
            return { records: [{ id: 1 }, { id: 2 }] };
        },
    };
    const model = new GanttSoftModel(
        {},
        {
            resModel: "project.task",
            fields: FIELDS,
            activeFields: ACTIVE_FIELDS,
            archInfo,
            domain: [],
            context: {},
            window: windowRange(Date.parse("2026-03-15T12:00:00Z"), "month"),
        },
        { orm: fakeOrm }
    );
    return { model, calls, fakeOrm };
}

describe("GanttSoftModel", () => {
    test("the window domain is a valid prefix expression", () => {
        const { model } = makeModel();
        const domain = model._windowDomain(
            windowRange(Date.parse("2026-03-15T12:00:00Z"), "month")
        );

        expect(isPrefixDomain(domain)).toBe(true);
        const flat = JSON.stringify(domain);
        // The three shapes: both dates, only a start, only a stop.
        expect(flat).toInclude('["date_start","<"');
        expect(flat).toInclude('["date_deadline",">="');
        expect(flat).toInclude('["date_start","=",false]');
        expect(flat).toInclude('["date_deadline","=",false]');
    });

    test("the window boundaries are serialised for each field's type", () => {
        luxon.Settings.defaultZone = "Europe/Istanbul";
        const { model } = makeModel({
            archInfo: makeArchInfo({
                dateStartType: "date",
                dateStopType: "datetime",
            }),
        });
        const domain = model._windowDomain(
            windowRange(Date.parse("2026-03-15T12:00:00Z"), "month")
        );
        const flat = JSON.stringify(domain);

        // A date boundary is the local calendar day, not the UTC date of the
        // local midnight (which is the previous day in Turkey).
        expect(flat).toInclude('"2026-03-01"');
        expect(flat).toInclude('"2026-04-01"');
        expect(flat).not.toInclude('"2026-02-28"');
        // A datetime boundary is the UTC instant of the local midnight.
        expect(flat).toInclude('"2026-02-28 21:00:00"');
        expect(flat).toInclude('"2026-03-31 21:00:00"');
    });

    test("load reads the window, the order and the limit in one call", async () => {
        const { model, calls } = makeModel();
        await model.load({ domain: [["id", ">", 0]], context: { lang: "en_US" } });

        expect(calls.length).toBe(1);
        const [{ domain, kwargs }] = calls;
        expect(isPrefixDomain(domain)).toBe(true);
        expect(domain).toInclude(["id", ">", 0]);
        expect(kwargs.order).toBe("date_start ASC");
        expect(kwargs.limit).toBe(500);
        expect(model.records).toHaveLength(2);
    });

    test("the arch default order is used until the search bar has one", async () => {
        const { model } = makeModel();
        expect(model.orderBy).toEqual([{ name: "date_start", asc: true }]);
        await model.load({ orderBy: [{ name: "name", asc: false }] });
        expect(model.orderBy).toEqual([{ name: "name", asc: false }]);
    });

    test("a window is optional: without one every record is read", async () => {
        const { model, calls } = makeModel();
        model.config.window = null;
        await model.reload();
        const domain = calls[0].domain;
        expect(domain).toEqual([]);
    });
});
