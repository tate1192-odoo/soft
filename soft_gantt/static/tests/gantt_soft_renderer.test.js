import { after, beforeEach, describe, expect, getFixture, test } from "@odoo/hoot";
import { queryAll, queryFirst, queryOne } from "@odoo/hoot-dom";
import { animationFrame } from "@odoo/hoot-mock";
import { App } from "@odoo/owl";
import { getTemplate, registerTemplate } from "@web/core/templates";
import { allowTranslations } from "@web/../tests/web_test_helpers";

import { GanttSoftRenderer } from "@soft_gantt/gantt/gantt_renderer";
import { windowRange } from "@soft_gantt/gantt/gantt_utils";

const TEMPLATE_NAME = "soft_gantt.GanttRenderer";
const TEMPLATE_URL = "/soft_gantt/static/src/gantt/gantt_renderer.xml";

/**
 * The renderer writes every date it shows in the user's timezone, and hoot's
 * default zone is not UTC (it is Europe/Brussels): pin it so the UTC-shaped
 * expectations below are the same instant on every machine. The tests that are
 * *about* the timezone set their own inside the test.
 */
const ORIGINAL_ZONE = luxon.Settings.defaultZone;
beforeEach(() => {
    luxon.Settings.defaultZone = "UTC";
});
after(() => {
    luxon.Settings.defaultZone = ORIGINAL_ZONE;
});

let templatePromise = null;

/**
 * Make sure the renderer template is registered.
 *
 * The unit test runner registers the templates of the modules a test file
 * reaches through its imports. A presentation component is reached straight
 * from its own file, so the template is registered here from the very file the
 * browser is served, which also checks that this file is the one under test.
 */
async function ensureRendererTemplate() {
    templatePromise ||= (async () => {
        if (!getTemplate(TEMPLATE_NAME)) {
            const response = await fetch(TEMPLATE_URL);
            registerTemplate(TEMPLATE_NAME, TEMPLATE_URL, await response.text());
        }
    })();
    await templatePromise;
}

/** Row height the renderer assumes, kept in sync with its own constant. */
const ROW_HEIGHT = 38;

/** The renderer only reads the fields it draws with, so a partial arch fits. */
function makeArchInfo(overrides = {}) {
    return {
        dateStart: "date_start",
        dateStartType: "datetime",
        dateStop: "date_deadline",
        dateStopType: "datetime",
        progressField: "",
        colorField: "",
        fieldNodes: {},
        ...overrides,
    };
}

function makeRecord(id, start, stop, extra = {}) {
    return {
        id,
        display_name: `Task ${id}`,
        date_start: start,
        date_deadline: stop,
        ...extra,
    };
}

/** `2026-01-01 + offset` days, as the server formats a datetime. */
function day(offset) {
    const date = new Date(Date.UTC(2026, 0, 1 + offset));
    return `${date.toISOString().slice(0, 10)} 00:00:00`;
}

/**
 * Mount the renderer with plain OWL.
 *
 * It is a presentation component: it reads its props and calls back into the
 * controller, and it uses no service. The web test environment is deliberately
 * left out here: creating it starts the mail services, whose first RPC
 * (discuss.channel) has nothing to do with what is under test. A bare app also
 * keeps the assertions exact, since nothing else is mounted next to it.
 */
async function mountRenderer({
    records,
    scale = "day",
    archInfo = makeArchInfo(),
    window = undefined,
    canEdit = true,
    collapsed = undefined,
    onBarClick = () => {},
    onReschedule = () => {},
    onResize = () => {},
    onToggleGroup = () => {},
}) {
    const target = document.createElement("div");
    // The fixture is where the assertions look: it is the root node hoot
    // defines for the current test, not `document.body`.
    getFixture().append(target);
    // The renderer shows a translated label: without this the translation
    // helper refuses to resolve a string that was never loaded.
    allowTranslations();
    await ensureRendererTemplate();
    const app = new App(GanttSoftRenderer, {
        props: {
            archInfo,
            records,
            scale,
            window,
            canEdit,
            collapsed,
            onBarClick,
            onReschedule,
            onResize,
            onToggleGroup,
        },
        // Odoo keeps its templates (static XML files, view extensions) in its
        // own registry, and hands them to Owl through this hook: `env.js`
        // wires the very same one when it mounts a component.
        getTemplate,
        test: true,
    });
    app.mount(target);
    after(() => {
        app.destroy();
        target.remove();
    });
    await animationFrame();
}

/** Click through the DOM: the bars have no size in a bare mount. */
async function clickBar(selector = ".o_gantt_soft_bar") {
    queryFirst(selector).dispatchEvent(new MouseEvent("click", { bubbles: true }));
    await animationFrame();
}

/** Inline percentages are serialized with a few digits: compare rounded values. */
function percentage(el, property = "left") {
    return Math.round(parseFloat(el.style[property]) * 100) / 100;
}

/**
 * The same inline percentage, unrounded.
 *
 * Two positions computed from the same expression keep every bit when they are
 * written to `style`, so comparing them raw is what proves a bar sits exactly
 * on the cell boundary rather than a rounded near miss.
 */
function floatPercentage(el, property = "left") {
    return parseFloat(el.style[property]);
}

describe("GanttSoftRenderer", () => {
    test("paints one bar per dated record, placed on the visible range", async () => {
        // The range covers 2026-03-02 to 2026-03-06 (4 days, exclusive end).
        await mountRenderer({
            records: [
                makeRecord(1, "2026-03-02 08:00:00", "2026-03-03 12:00:00"),
                makeRecord(2, "2026-03-03 00:00:00", "2026-03-05 00:00:00"),
            ],
        });

        expect(".o_gantt_soft_bar").toHaveCount(2);
        // The day scale is drawn in hours: four days of them.
        expect(".o_gantt_soft_cell").toHaveCount(96);

        const bars = queryAll(".o_gantt_soft_bar");
        // 8h into a 4 day range, 28h long.
        expect(percentage(bars[0])).toBe(8.33);
        expect(percentage(bars[0], "width")).toBe(29.17);
        // Starts on the second day, ends on the fourth.
        expect(percentage(bars[1])).toBe(25);
        expect(percentage(bars[1], "width")).toBe(50);
    });

    test("leaves an undated record out and reports it", async () => {
        await mountRenderer({
            records: [
                makeRecord(1, "2026-03-02 00:00:00", "2026-03-03 00:00:00"),
                makeRecord(2, false, false),
            ],
        });

        expect(".o_gantt_soft_bar").toHaveCount(1);
        expect(".o_gantt_soft_footer").toHaveText("1 record(s) without a date");
    });

    test("shows an explanation when no record carries a date", async () => {
        await mountRenderer({
            records: [makeRecord(1, false, false), makeRecord(2, false, false)],
        });

        // No empty grid with a header and no rows: the view explains itself.
        expect(".o_gantt_soft_grid").toHaveCount(0);
        expect(".o_gantt_soft_placeholder").toHaveText(
            "No record carries a date yet: set one to see it on the timeline."
        );
        // The footer would repeat the same count under the explanation.
        expect(".o_gantt_soft_footer").toHaveCount(0);
    });

    test("takes the colour and the progress from the arch", async () => {
        await mountRenderer({
            archInfo: makeArchInfo({ colorField: "color_index", progressField: "progress" }),
            records: [
                makeRecord(1, "2026-03-02 00:00:00", "2026-03-03 00:00:00", {
                    color_index: 3,
                    progress: 40,
                }),
            ],
        });

        expect(".o_gantt_soft_bar.o_gantt_soft_color_3").toHaveCount(1);
        expect(queryOne(".o_gantt_soft_bar_progress").style.width).toBe("40%");
    });

    test("only paints the rows around the viewport", async () => {
        const records = Array.from({ length: 200 }, (_, index) =>
            makeRecord(index + 1, day(index), day(index + 1))
        );
        await mountRenderer({ records });

        const painted = queryAll(".o_gantt_soft_row").length;
        expect(painted > 0).toBe(true);
        expect(painted < records.length).toBe(true);

        // The spacers keep the scroll height of the whole list, so the
        // scrollbar still describes 200 rows.
        const spacers = queryAll(".o_gantt_soft_rows > div").filter(
            (el) => !el.classList.contains("o_gantt_soft_row")
        );
        const total =
            spacers.reduce((sum, el) => sum + (parseFloat(el.style.height) || 0), 0) +
            painted * ROW_HEIGHT;
        expect(total).toBe(records.length * ROW_HEIGHT);
    });

    test("paints another slice of rows after scrolling", async () => {
        const records = Array.from({ length: 200 }, (_, index) =>
            makeRecord(index + 1, day(index), day(index + 1))
        );
        await mountRenderer({ records });

        const viewport = queryOne(".o_gantt_soft_viewport");
        viewport.style.height = "250px";
        viewport.style.overflow = "auto";
        const firstBefore = queryFirst(".o_gantt_soft_label span").textContent;

        viewport.scrollTop = 800;
        viewport.dispatchEvent(new Event("scroll"));
        await animationFrame();
        await animationFrame();

        expect(queryFirst(".o_gantt_soft_label span").textContent === firstBefore).toBe(false);
        // Everything above the window is now described by the top spacer.
        expect(parseFloat(queryFirst(".o_gantt_soft_side > div").style.height) > 0).toBe(true);
        expect(queryAll(".o_gantt_soft_row").length < records.length).toBe(true);
    });

    test("clicking a bar opens the record", async () => {
        const clicked = [];
        await mountRenderer({
            records: [makeRecord(1, "2026-03-02 00:00:00", "2026-03-03 00:00:00")],
            onBarClick: (row) => clicked.push(row.id),
        });

        await clickBar();
        expect(clicked).toEqual([1]);
    });

    test("dragging a bar reschedules by the number of columns crossed", async () => {
        const rescheduled = [];
        await mountRenderer({
            records: [makeRecord(1, "2026-03-02 00:00:00", "2026-03-05 00:00:00")],
            onReschedule: (id, days) => rescheduled.push([id, days]),
        });

        // 4 days across 300px: 75px is one column.
        queryFirst(".o_gantt_soft_row").style.width = "300px";
        queryFirst(".o_gantt_soft_bar").dispatchEvent(
            new PointerEvent("pointerdown", { clientX: 0, button: 0, bubbles: true })
        );
        window.dispatchEvent(new PointerEvent("pointermove", { clientX: 75, bubbles: true }));
        window.dispatchEvent(new PointerEvent("pointerup", { clientX: 75, bubbles: true }));

        expect(rescheduled).toEqual([[1, 1]]);
    });

    test("the click that follows a drag does not open the record", async () => {
        const clicked = [];
        const rescheduled = [];
        await mountRenderer({
            records: [makeRecord(1, "2026-03-02 00:00:00", "2026-03-05 00:00:00")],
            onBarClick: (row) => clicked.push(row.id),
            onReschedule: (id, days) => rescheduled.push([id, days]),
        });

        queryFirst(".o_gantt_soft_row").style.width = "300px";
        const bar = queryFirst(".o_gantt_soft_bar");
        bar.dispatchEvent(new PointerEvent("pointerdown", { clientX: 0, button: 0, bubbles: true }));
        window.dispatchEvent(new PointerEvent("pointermove", { clientX: 75, bubbles: true }));
        window.dispatchEvent(new PointerEvent("pointerup", { clientX: 75, bubbles: true }));
        await animationFrame();

        await clickBar();
        expect(rescheduled).toEqual([[1, 1]]);
        expect(clicked).toEqual([]);

        // The next click is a plain one again.
        await clickBar();
        expect(clicked).toEqual([1]);
    });

    test("a read only view does not move the bars", async () => {
        const rescheduled = [];
        await mountRenderer({
            records: [makeRecord(1, "2026-03-02 00:00:00", "2026-03-05 00:00:00")],
            canEdit: false,
            onReschedule: (id, days) => rescheduled.push([id, days]),
        });

        queryFirst(".o_gantt_soft_row").style.width = "300px";
        queryFirst(".o_gantt_soft_bar").dispatchEvent(
            new PointerEvent("pointerdown", { clientX: 0, button: 0, bubbles: true })
        );
        window.dispatchEvent(new PointerEvent("pointermove", { clientX: 75, bubbles: true }));
        window.dispatchEvent(new PointerEvent("pointerup", { clientX: 75, bubbles: true }));

        expect(rescheduled).toEqual([]);
        expect(".o_gantt_soft_bar.o_gantt_soft_bar_draggable").toHaveCount(0);
    });

    test("draws the window it is given, not the extent of the records", async () => {
        // A month long window on a day scale: 31 columns, so a single record
        // finds its place in a whole month whatever the other records span.
        await mountRenderer({
            window: { start: Date.UTC(2026, 2, 1), end: Date.UTC(2026, 3, 1) },
            records: [makeRecord(1, "2026-03-10 00:00:00", "2026-03-12 00:00:00")],
        });

        expect(".o_gantt_soft_cell").toHaveCount(31);
        expect(".o_gantt_soft_bar").toHaveCount(1);
    });

    test("a many2one label is read, not printed as an object", async () => {
        // A regression: a many2one comes as `{id, display_name}` from the
        // Odoo 17+ relational model, and printing it as it comes puts
        // `[object Object]` on screen, on the left column and inside the bar.
        await mountRenderer({
            archInfo: makeArchInfo({ labelField: "partner_id" }),
            records: [
                makeRecord(1, "2026-03-02 00:00:00", "2026-03-05 00:00:00", {
                    partner_id: { id: 3, display_name: "Acme Insaat" },
                }),
            ],
        });

        expect(queryOne(".o_gantt_soft_label").textContent).toBe("Acme Insaat");
        expect(queryOne(".o_gantt_soft_bar_label").textContent).toBe("Acme Insaat");
    });

    test("falls back to the record name when the label field is empty", async () => {
        await mountRenderer({
            archInfo: makeArchInfo({ labelField: "partner_id" }),
            records: [makeRecord(2, "2026-03-02 00:00:00", "2026-03-05 00:00:00")],
        });

        expect(queryOne(".o_gantt_soft_label").textContent).toBe("Task 2");
    });

    test("groups the records of one team on a single row, on lanes", async () => {
        const team = { id: 7, display_name: "Alpha" };
        await mountRenderer({
            archInfo: makeArchInfo({ groupByField: "team_id" }),
            records: [
                makeRecord(1, "2026-03-02 00:00:00", "2026-03-05 00:00:00", { team_id: team }),
                makeRecord(2, "2026-03-04 00:00:00", "2026-03-06 00:00:00", { team_id: team }),
            ],
        });

        // The team vertically, its dates horizontally: one row, two bars.
        expect(".o_gantt_soft_row").toHaveCount(1);
        expect(".o_gantt_soft_bar").toHaveCount(2);
        expect(queryOne(".o_gantt_soft_label").textContent).toBe("Alpha");
        // The two services overlap, so the second one drops to the next lane
        // instead of being drawn on top of the first.
        expect(queryAll(".o_gantt_soft_bar").map((el) => el.style.top)).toEqual(["2px", "32px"]);
        // The row names the team, the bars name the records.
        expect(queryAll(".o_gantt_soft_bar_label").map((el) => el.textContent)).toEqual([
            "Task 1",
            "Task 2",
        ]);
    });

    test("gives every group a row of its own, sorted", async () => {
        await mountRenderer({
            archInfo: makeArchInfo({ groupByField: "team_id" }),
            records: [
                makeRecord(1, "2026-03-02 00:00:00", "2026-03-05 00:00:00", {
                    team_id: { id: 8, display_name: "Beta" },
                }),
                makeRecord(2, "2026-03-03 00:00:00", "2026-03-06 00:00:00", {
                    team_id: { id: 7, display_name: "Alpha" },
                }),
            ],
        });

        expect(".o_gantt_soft_row").toHaveCount(2);
        expect(queryAll(".o_gantt_soft_label").map((el) => el.textContent)).toEqual([
            "Alpha",
            "Beta",
        ]);
        // One service each: both rows are a single lane tall.
        expect(queryAll(".o_gantt_soft_row").map((el) => el.style.height)).toEqual([
            "30px",
            "30px",
        ]);
    });

    test("keeps the records nobody is assigned to", async () => {
        await mountRenderer({
            archInfo: makeArchInfo({ groupByField: "team_id" }),
            records: [makeRecord(1, "2026-03-02 00:00:00", "2026-03-05 00:00:00")],
        });

        expect(".o_gantt_soft_row").toHaveCount(1);
        expect(queryOne(".o_gantt_soft_label").textContent).toBe("Not set");
    });

    test("groups by id, so two teams sharing a name stay apart", async () => {
        await mountRenderer({
            archInfo: makeArchInfo({ groupByField: "team_id" }),
            records: [
                makeRecord(1, "2026-03-02 00:00:00", "2026-03-05 00:00:00", {
                    team_id: { id: 7, display_name: "Alpha" },
                }),
                makeRecord(2, "2026-03-03 00:00:00", "2026-03-06 00:00:00", {
                    team_id: { id: 8, display_name: "Alpha" },
                }),
            ],
        });

        expect(".o_gantt_soft_row").toHaveCount(2);
        expect(queryAll(".o_gantt_soft_label").map((el) => el.textContent)).toEqual([
            "Alpha",
            "Alpha",
        ]);
    });

    test("groups the older [id, name] many2one shape by its id", async () => {
        await mountRenderer({
            archInfo: makeArchInfo({ groupByField: "team_id" }),
            records: [
                makeRecord(1, "2026-03-02 00:00:00", "2026-03-05 00:00:00", {
                    team_id: [7, "Alpha"],
                }),
            ],
        });

        expect(queryOne(".o_gantt_soft_label").textContent).toBe("Alpha");
    });

    test("counts the undated records, not the groups, when grouping", async () => {
        const team = { id: 7, display_name: "Alpha" };
        await mountRenderer({
            archInfo: makeArchInfo({ groupByField: "team_id" }),
            records: [
                makeRecord(1, "2026-03-02 00:00:00", "2026-03-03 00:00:00", { team_id: team }),
                makeRecord(2, "2026-03-04 00:00:00", "2026-03-05 00:00:00", { team_id: team }),
                makeRecord(3, false, false, { team_id: team }),
            ],
        });

        expect(".o_gantt_soft_row").toHaveCount(1);
        expect(".o_gantt_soft_footer").toHaveText("1 record(s) without a date");
    });

    test("a selection label field is read by its label", async () => {
        await mountRenderer({
            archInfo: makeArchInfo({
                labelField: "state",
                selectionLabels: { state: { draft: "Draft" } },
            }),
            records: [
                makeRecord(1, "2026-03-02 00:00:00", "2026-03-05 00:00:00", { state: "draft" }),
            ],
        });

        expect(queryOne(".o_gantt_soft_label").textContent).toBe("Draft");
        expect(queryOne(".o_gantt_soft_bar_label").textContent).toBe("Draft");
    });

    test("a grouped row does not open anything when its name is clicked", async () => {
        const clicked = [];
        await mountRenderer({
            archInfo: makeArchInfo({ groupByField: "team_id" }),
            records: [
                makeRecord(1, "2026-03-02 00:00:00", "2026-03-05 00:00:00", {
                    team_id: { id: 7, display_name: "Alpha" },
                }),
                makeRecord(2, "2026-03-04 00:00:00", "2026-03-06 00:00:00", {
                    team_id: { id: 7, display_name: "Alpha" },
                }),
            ],
            onBarClick: (row) => clicked.push(row.id),
        });

        queryFirst(".o_gantt_soft_label").dispatchEvent(new MouseEvent("click", { bubbles: true }));
        await animationFrame();

        // The row stands for two records: the bars are the way in.
        expect(clicked).toEqual([]);
    });

    test("draws a two level header: the bands over the cells of the scale", async () => {
        // A week at the week scale: seven day cells under one week band.
        await mountRenderer({
            scale: "week",
            window: { start: Date.UTC(2026, 2, 2), end: Date.UTC(2026, 2, 9) },
            records: [makeRecord(1, "2026-03-03 00:00:00", "2026-03-05 00:00:00")],
        });

        expect(".o_gantt_soft_cell").toHaveCount(7);
        expect(".o_gantt_soft_band").toHaveCount(1);
        // A week is read by its days, so the cells carry the weekday.
        expect(queryAll(".o_gantt_soft_cell").map((el) => el.textContent).slice(0, 3)).toEqual([
            "02 Mon",
            "03 Tue",
            "04 Wed",
        ]);
        expect(queryOne(".o_gantt_soft_band").textContent).toBe("02 Mar - 08 Mar");
    });

    test("draws the hours of the day at the day scale", async () => {
        await mountRenderer({
            scale: "day",
            window: windowRange(Date.parse("2026-03-03T00:00:00Z"), "day"),
            records: [makeRecord(1, "2026-03-03 08:00:00", "2026-03-03 12:00:00")],
        });

        expect(".o_gantt_soft_cell").toHaveCount(24);
        expect(queryFirst(".o_gantt_soft_cell").textContent).toBe("00:00");
        expect(".o_gantt_soft_band").toHaveCount(1);
        expect(queryOne(".o_gantt_soft_band").textContent).toBe("03 Mar 2026");
    });

    test("marks today when the window holds it", async () => {
        await mountRenderer({
            scale: "week",
            window: windowRange(Date.now(), "week"),
            records: [makeRecord(1, "2026-03-03 00:00:00", "2026-03-05 00:00:00")],
        });

        expect(".o_gantt_soft_today").toHaveCount(1);
        expect(queryOne(".o_gantt_soft_today_label").textContent).toBe("Today");
    });

    test("dragging the end edge resizes by the number of days crossed", async () => {
        const resized = [];
        await mountRenderer({
            records: [makeRecord(1, "2026-03-02 00:00:00", "2026-03-05 00:00:00")],
            onResize: (id, edge, days) => resized.push([id, edge, days]),
        });

        // 4 days across 300px: 75px is one day, so 150px is two of them.
        queryFirst(".o_gantt_soft_row").style.width = "300px";
        const handle = queryFirst(".o_gantt_soft_bar_handle_end");
        handle.dispatchEvent(
            new PointerEvent("pointerdown", { clientX: 0, button: 0, bubbles: true })
        );
        window.dispatchEvent(new PointerEvent("pointermove", { clientX: 150, bubbles: true }));
        window.dispatchEvent(new PointerEvent("pointerup", { clientX: 150, bubbles: true }));

        expect(resized).toEqual([[1, "end", 2]]);
    });

    test("dragging the start edge moves the start, not the end", async () => {
        const resized = [];
        await mountRenderer({
            records: [makeRecord(1, "2026-03-02 00:00:00", "2026-03-05 00:00:00")],
            onResize: (id, edge, days) => resized.push([id, edge, days]),
        });

        queryFirst(".o_gantt_soft_row").style.width = "300px";
        const handle = queryFirst(".o_gantt_soft_bar_handle_start");
        handle.dispatchEvent(
            new PointerEvent("pointerdown", { clientX: 0, button: 0, bubbles: true })
        );
        window.dispatchEvent(new PointerEvent("pointermove", { clientX: 75, bubbles: true }));
        window.dispatchEvent(new PointerEvent("pointerup", { clientX: 75, bubbles: true }));

        expect(resized).toEqual([[1, "start", 1]]);
    });

    test("a read only view shows no resize handles and cannot resize", async () => {
        const resized = [];
        await mountRenderer({
            records: [makeRecord(1, "2026-03-02 00:00:00", "2026-03-05 00:00:00")],
            canEdit: false,
            onResize: (id, edge, days) => resized.push([id, edge, days]),
        });

        expect(".o_gantt_soft_bar_handle").toHaveCount(0);
        expect(resized).toEqual([]);
    });

    test("a collapsed group is one bar spanning the whole group, with its count", async () => {
        const team = { id: 7, display_name: "Alpha" };
        await mountRenderer({
            archInfo: makeArchInfo({ groupByField: "team_id" }),
            records: [
                makeRecord(1, "2026-03-02 00:00:00", "2026-03-03 00:00:00", { team_id: team }),
                makeRecord(2, "2026-03-04 00:00:00", "2026-03-05 00:00:00", { team_id: team }),
            ],
            collapsed: { 7: true },
        });

        // One bar for the whole team, on the one lane a folded row takes.
        expect(".o_gantt_soft_row").toHaveCount(1);
        expect(".o_gantt_soft_bar").toHaveCount(1);
        expect(queryFirst(".o_gantt_soft_row").style.height).toBe("30px");

        const bar = queryFirst(".o_gantt_soft_bar");
        // From the earliest start to the latest stop: 03-02 to 03-05 of a
        // four day range.
        expect(percentage(bar)).toBe(0);
        expect(percentage(bar, "width")).toBe(75);
        expect(bar.style.top).toBe("2px");
        // The counts, on the bar and on the row.
        expect(queryOne(".o_gantt_soft_bar_label").textContent).toBe("2 record(s)");
        expect(queryOne(".o_gantt_soft_label").textContent).toBe("Alpha (2)");
        // A folded group is not a record: it has no resize grips.
        expect(".o_gantt_soft_bar_handle").toHaveCount(0);
        // The toggle is there, and shows the "unfold" state.
        expect(".o_gantt_soft_group_toggle").toHaveCount(1);
        expect(".o_gantt_soft_group_toggle_collapsed").toHaveCount(1);
    });

    test("a collapsed group bar unfolds the group and never moves a record", async () => {
        const toggled = [];
        const rescheduled = [];
        const clicked = [];
        const team = { id: 7, display_name: "Alpha" };
        await mountRenderer({
            archInfo: makeArchInfo({ groupByField: "team_id" }),
            records: [
                makeRecord(1, "2026-03-02 00:00:00", "2026-03-03 00:00:00", { team_id: team }),
                makeRecord(2, "2026-03-04 00:00:00", "2026-03-05 00:00:00", { team_id: team }),
            ],
            collapsed: { 7: true },
            onToggleGroup: (key) => toggled.push(key),
            onReschedule: (id, days) => rescheduled.push([id, days]),
            onBarClick: (row) => clicked.push(row.id),
        });

        queryFirst(".o_gantt_soft_row").style.width = "300px";
        const bar = queryFirst(".o_gantt_soft_bar");
        bar.dispatchEvent(new PointerEvent("pointerdown", { clientX: 0, button: 0, bubbles: true }));
        window.dispatchEvent(new PointerEvent("pointermove", { clientX: 75, bubbles: true }));
        window.dispatchEvent(new PointerEvent("pointerup", { clientX: 75, bubbles: true }));
        await animationFrame();

        // Dragging a group does not move its first record.
        expect(rescheduled).toEqual([]);
        expect(clicked).toEqual([]);

        // Clicking it unfolds the group instead of opening a record.
        await clickBar(".o_gantt_soft_bar");
        expect(toggled).toEqual(["7"]);
        expect(clicked).toEqual([]);
    });

    test("clicking the toggle of a grouped row asks for its group key", async () => {
        const toggled = [];
        const team = { id: 7, display_name: "Alpha" };
        await mountRenderer({
            archInfo: makeArchInfo({ groupByField: "team_id" }),
            records: [
                makeRecord(1, "2026-03-02 00:00:00", "2026-03-03 00:00:00", { team_id: team }),
                makeRecord(2, "2026-03-04 00:00:00", "2026-03-05 00:00:00", { team_id: team }),
            ],
            onToggleGroup: (key) => toggled.push(key),
        });

        const toggle = queryFirst(".o_gantt_soft_group_toggle");
        expect(toggle !== null).toBe(true);
        // An expanded group shows the "fold" arrow.
        expect(".o_gantt_soft_group_toggle_collapsed").toHaveCount(0);
        toggle.dispatchEvent(new MouseEvent("click", { bubbles: true }));
        await animationFrame();

        // The group key travels back, and the row's own click does not fire.
        expect(toggled).toEqual(["7"]);
    });

    test("snaps a bar to the day cell the header draws", async () => {
        // A week scale is read in days: a service starting at 08:00 must cover
        // the whole 03-03 cell, not the sliver an eighth of the way into it.
        await mountRenderer({
            scale: "week",
            window: { start: Date.UTC(2026, 2, 2), end: Date.UTC(2026, 2, 9) },
            records: [makeRecord(1, "2026-03-03 08:00:00", "2026-03-03 12:00:00")],
        });

        const cells = queryAll(".o_gantt_soft_cell");
        const bar = queryFirst(".o_gantt_soft_bar");
        // The bar starts exactly where the 03-03 cell starts, and is exactly
        // one cell wide, read from the cell positions themselves.
        expect(floatPercentage(bar)).toBe(floatPercentage(cells[1]));
        expect(floatPercentage(bar, "width")).toBe(floatPercentage(cells[1], "width"));
    });

    test("places a record in its local hour, not the UTC one", async () => {
        // The user is in Turkey (+03): the day they read is the local day of
        // 2026-03-04, which starts at 21:00Z on the 3rd. This record starts at
        // 21:30Z, i.e. 00:30 local, so it belongs in the first hour cell. A
        // forced-UTC placement would have thrown it to ~90% across the window,
        // and jobs at 07:00 local would have read 04:00.
        luxon.Settings.defaultZone = "Europe/Istanbul";
        await mountRenderer({
            scale: "day",
            window: windowRange(Date.parse("2026-03-04T00:00:00Z"), "day"),
            records: [makeRecord(1, "2026-03-03 21:30:00", "2026-03-03 22:30:00")],
        });

        expect(queryFirst(".o_gantt_soft_cell").textContent).toBe("00:00");
        const bar = queryFirst(".o_gantt_soft_bar");
        // Half an hour into a 24 hour window: comfortably inside 00:00-01:00.
        expect(floatPercentage(bar)).toBeCloseTo((0.5 / 24) * 100, { margin: 0.01 });
        expect(floatPercentage(bar)).toBeLessThan(100 / 24);
    });

    test("a date field keeps the user's calendar day in a negative offset", async () => {
        // A Date has no timezone: 2026-03-05 is the 5th in New York too. An
        // UTC-midnight reading would put the bar on the 4th there.
        luxon.Settings.defaultZone = "America/New_York";
        await mountRenderer({
            scale: "week",
            window: windowRange(Date.parse("2026-03-02T12:00:00Z"), "week"),
            archInfo: makeArchInfo({ dateStartType: "date", dateStopType: "date" }),
            records: [makeRecord(1, "2026-03-05", "2026-03-06")],
        });

        const cells = queryAll(".o_gantt_soft_cell");
        const bar = queryFirst(".o_gantt_soft_bar");
        expect(floatPercentage(bar)).toBe(floatPercentage(cells[3]));
        expect(floatPercentage(bar, "width")).toBe(floatPercentage(cells[3], "width"));
    });

    test("a record with no end is one hour wide in the hour view", async () => {
        await mountRenderer({
            scale: "day",
            window: windowRange(Date.parse("2026-03-03T00:00:00Z"), "day"),
            records: [makeRecord(1, "2026-03-03 00:00:00", false)],
        });

        const bar = queryFirst(".o_gantt_soft_bar");
        expect(floatPercentage(bar)).toBe(0);
        // They asked for a one hour bar: one hour of a 24 hour window.
        expect(floatPercentage(bar, "width")).toBeCloseTo(100 / 24, { margin: 0.05 });
    });

    test("the column lines stop where the rows stop", async () => {
        // Two rows in a mount area far taller than them: the lines must cover
        // the rows and their spacers only, not the empty space below.
        await mountRenderer({
            records: [
                makeRecord(1, "2026-03-02 00:00:00", "2026-03-03 00:00:00"),
                makeRecord(2, "2026-03-02 00:00:00", "2026-03-03 00:00:00"),
            ],
        });
        const viewport = queryOne(".o_gantt_soft_viewport");
        viewport.style.height = "600px";

        const rows = queryAll(".o_gantt_soft_row");
        const spacers = queryAll(".o_gantt_soft_rows > div").filter(
            (el) => !el.classList.contains("o_gantt_soft_row")
        );
        const rowsHeight = rows.reduce((sum, el) => sum + parseFloat(el.style.height), 0);
        const spacersHeight = spacers.reduce(
            (sum, el) => sum + (parseFloat(el.style.height) || 0),
            0
        );

        const gridlinesHeight = parseFloat(queryOne(".o_gantt_soft_gridlines").style.height);
        expect(gridlinesHeight).toBe(spacersHeight + rowsHeight);
        // The timeline itself still stretches, which is what the today line
        // needs: the lines are shorter than the timeline, not equal to it.
        expect(gridlinesHeight).toBeLessThan(queryOne(".o_gantt_soft_timeline").offsetHeight);
    });
});

