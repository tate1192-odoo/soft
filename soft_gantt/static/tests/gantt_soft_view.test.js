import { after, beforeEach, describe, expect, getFixture, test } from "@odoo/hoot";
import { click, queryAll, queryOne } from "@odoo/hoot-dom";
import { animationFrame, mockDate } from "@odoo/hoot-mock";
import { user } from "@web/core/user";
import {
    defineModels,
    fields,
    models,
    mountWithCleanup,
    parseViewProps,
} from "@web/../tests/web_test_helpers";
import { View } from "@web/views/view";

import "@soft_gantt/gantt/gantt_view";

/**
 * The whole view, mounted the way the action manager mounts it.
 *
 * This is the layer the unit tests cannot see: the arch parser, the model that
 * sends the window domain, the controller that decides whether the bars are
 * editable, and the renderer that paints them.
 */
class Task extends models.Model {
    _name = "project.task";

    name = fields.Char();
    date_start = fields.Datetime();
    date_deadline = fields.Datetime();
    color = fields.Integer();

    _records = [
        { id: 1, name: "In the window", date_start: "2026-03-02 00:00:00", date_deadline: "2026-03-05 00:00:00" },
        { id: 2, name: "Only an end", date_start: false, date_deadline: "2026-03-10 00:00:00" },
        { id: 3, name: "Only a start", date_start: "2026-03-20 00:00:00", date_deadline: false },
        { id: 4, name: "Out of the window", date_start: "2026-02-01 00:00:00", date_deadline: "2026-02-03 00:00:00" },
        { id: 5, name: "Ends at the window start", date_start: "2026-02-01 00:00:00", date_deadline: "2026-03-01 00:00:00" },
    ];

    _views = {
        gantt_soft: `
            <gantt_soft
                string="Gantt"
                date_start="date_start"
                date_stop="date_deadline"
                color="color"
                mode="month"
                scales="day,week,month"
            />
        `,
        form: `
            <form>
                <field name="name"/>
            </form>
        `,
        search: `
            <search>
                <field name="name"/>
            </search>
        `,
    };
}

defineModels([Task]);

const ORIGINAL_TIMEZONE = user.tz;
beforeEach(() => {
    user.updateContext({ tz: "UTC" });
});
after(() => {
    user.updateContext({ tz: ORIGINAL_TIMEZONE });
});

describe.current.tags("desktop");

/**
 * Mount the view without the main component container.
 *
 * The container starts every registered main component, including the mail
 * systray, whose store reads discuss.channel on startup. This test is about
 * the Gantt view, not about the mail store, so the container is left out.
 */
async function mountGanttView(params) {
    const actionManagerEl = document.createElement("div");
    actionManagerEl.classList.add("o_action_manager");
    getFixture().append(actionManagerEl);
    after(() => actionManagerEl.remove());
    return mountWithCleanup(View, {
        env: params.env,
        componentEnv: { config: params.config },
        props: parseViewProps(params),
        target: actionManagerEl,
        noMainContainer: true,
    });
}

/** A local month holding March 2026, so the window is deterministic. */
const MARCH_STATE = {
    scale: "month",
    range: "month",
    windowStart: Date.UTC(2026, 2, 15),
};

test("loads the records overlapping the window, including single date ones", async () => {
    await mountGanttView({
        type: "gantt_soft",
        resModel: "project.task",
        state: { ...MARCH_STATE },
    });

    // The two records carrying only one date are drawn on it, and the record
    // outside the window is not read at all.
    expect(".o_gantt_soft_bar").toHaveCount(3);
    expect(".o_gantt_soft_row").toHaveCount(3);
});

test("bars are editable when the view allows it", async () => {
    await mountGanttView({
        type: "gantt_soft",
        resModel: "project.task",
        state: { ...MARCH_STATE },
    });
    expect(queryAll(".o_gantt_soft_bar_draggable").length).toBe(3);
    expect(queryAll(".o_gantt_soft_bar_handle").length).toBe(6);
});

test("a read only view offers no drag and no grips", async () => {
    await mountGanttView({
        type: "gantt_soft",
        resModel: "project.task",
        state: { ...MARCH_STATE },
        arch: `
            <gantt_soft
                date_start="date_start"
                date_stop="date_deadline"
                edit="0"
            />
        `,
    });
    expect(".o_gantt_soft_bar_draggable").toHaveCount(0);
    expect(".o_gantt_soft_bar_handle").toHaveCount(0);
});


test("the create button follows the arch", async () => {
    const created = [];
    await mountGanttView({
        type: "gantt_soft",
        resModel: "project.task",
        state: { ...MARCH_STATE },
        arch: `<gantt_soft date_start="date_start" date_stop="date_deadline"/>`,
        createRecord: () => created.push(true),
    });
    expect(".o_gantt_soft_button_add").toHaveCount(1);
    await click(queryOne(".o_gantt_soft_button_add"));
    expect(created).toEqual([true]);
});

test("create is not offered when the arch forbids it", async () => {
    const created = [];
    await mountGanttView({
        type: "gantt_soft",
        resModel: "project.task",
        state: { ...MARCH_STATE },
        arch: `<gantt_soft date_start="date_start" date_stop="date_deadline" create="0"/>`,
        createRecord: () => created.push(true),
    });
    expect(".o_gantt_soft_button_add").toHaveCount(0);
    expect(created).toEqual([]);
});

test("the fit button frames the whole search", async () => {
    await mountGanttView({
        type: "gantt_soft",
        resModel: "project.task",
        state: { ...MARCH_STATE },
    });
    expect(".o_gantt_soft_button_fit").toHaveCount(1);
    // The records span 2026-02-01 to the start-only record on 2026-03-20.
    await click(queryOne(".o_gantt_soft_button_fit"));
    await animationFrame();
    await animationFrame();
    expect(queryOne(".o_gantt_soft_window_label").textContent.trim()).toBe(
        "01 Feb 2026 - 20 Mar 2026"
    );
});

test("the CSV button downloads the records of the window", async () => {
    const blobs = [];
    const original = URL.createObjectURL;
    URL.createObjectURL = (blob) => {
        blobs.push(blob);
        return "blob:soft-gantt-test";
    };
    after(() => {
        URL.createObjectURL = original;
    });
    await mountGanttView({
        type: "gantt_soft",
        resModel: "project.task",
        state: { ...MARCH_STATE },
    });
    await click(queryOne(".o_gantt_soft_button_csv"));
    expect(blobs).toHaveLength(1);
    const csv = await blobs[0].text();
    const lines = csv.replace("\ufeff", "").split("\r\n");
    // The header names the two dates of the view and the computed duration.
    expect(lines[0].split(";")[0]).toBe("Name");
    expect(lines[0]).toInclude("Duration (days)");
    // The window holds three dated records; the fourth is out of it.
    expect(lines).toHaveLength(4);
    // One row per painted record, each with its own label in the first column.
    expect(lines.slice(1).every((line) => line.split(";")[0].length > 0)).toBe(true);
});

test("a day window is labelled as a day", async () => {
    await mountGanttView({
        type: "gantt_soft",
        resModel: "project.task",
        state: { scale: "day", range: "day", windowStart: Date.UTC(2026, 2, 5) },
        arch: `<gantt_soft date_start="date_start" date_stop="date_deadline" default_range="day"/>`,
    });
    expect(queryOne(".o_gantt_soft_window_label").textContent.trim()).toBe("05 Mar 2026");
});

test("a week view opens on the next week when today is the last day", async () => {
    // 2026-11-08 is a Sunday: the current week (02-08 Nov) has no day left to
    // plan, so a planning view opens on the week that starts the next morning.
    mockDate("2026-11-08T20:41:00Z");
    await mountGanttView({
        type: "gantt_soft",
        resModel: "project.task",
        arch: `<gantt_soft date_start="date_start" date_stop="date_deadline" default_range="week" mode="week"/>`,
    });
    expect(queryOne(".o_gantt_soft_window_label").textContent.trim()).toBe(
        "09 Nov - 15 Nov 2026"
    );
});

test("a week view still opens on the current week on a working day", async () => {
    // 2026-11-04 is a Wednesday: the rest of the week is still ahead.
    mockDate("2026-11-04T12:00:00Z");
    await mountGanttView({
        type: "gantt_soft",
        resModel: "project.task",
        arch: `<gantt_soft date_start="date_start" date_stop="date_deadline" default_range="week" mode="week"/>`,
    });
    expect(queryOne(".o_gantt_soft_window_label").textContent.trim()).toBe(
        "02 Nov - 08 Nov 2026"
    );
});
