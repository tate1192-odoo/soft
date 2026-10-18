import { describe, expect, test } from "@odoo/hoot";
import { parseXML } from "@web/core/utils/xml";

import { GanttSoftArchParser } from "@soft_gantt/gantt/gantt_arch_parser";

/**
 * The arch parser runs on the client too, and this is where a view that the
 * server accepted at install time can still be refused: a view built at
 * runtime by another module never went through the server side check.
 */
const MODELS = {
    "project.task": {
        fields: {
            name: { type: "char", string: "Name" },
            date_start: { type: "datetime" },
            date_deadline: { type: "datetime" },
            planned_date: { type: "date" },
            progress: { type: "float" },
            color_index: { type: "integer" },
            user_id: { type: "many2one", relation: "res.users" },
            tag_ids: { type: "many2many", relation: "project.tags" },
            state: {
                type: "selection",
                selection: [
                    ["draft", "Draft"],
                    ["done", "Done"],
                ],
            },
        },
    },
};

function parse(arch, modelName = "project.task") {
    return new GanttSoftArchParser().parse(parseXML(arch), MODELS, modelName);
}

describe("GanttSoftArchParser", () => {
    test("reads the date fields and their types", () => {
        const archInfo = parse(
            '<gantt_soft date_start="date_start" date_stop="date_deadline" string="Tasks"/>'
        );
        expect(archInfo.dateStart).toBe("date_start");
        expect(archInfo.dateStop).toBe("date_deadline");
        expect(archInfo.dateStartType).toBe("datetime");
        expect(archInfo.dateStopType).toBe("datetime");
    });

    test("accepts a date field, and mixes it with a datetime one", () => {
        const archInfo = parse('<gantt_soft date_start="planned_date" date_stop="date_deadline"/>');
        expect(archInfo.dateStartType).toBe("date");
        expect(archInfo.dateStopType).toBe("datetime");
    });

    test("refuses a view without a start date", () => {
        expect(() => parse('<gantt_soft date_stop="date_deadline"/>')).toThrow(
            /"date_start" attribute is required/
        );
    });

    test("refuses a field that the model does not have", () => {
        expect(() => parse('<gantt_soft date_start="nope" date_stop="date_deadline"/>')).toThrow(
            /is not defined on project.task/
        );
    });

    test("refuses a field of the wrong type", () => {
        expect(() => parse('<gantt_soft date_start="user_id" date_stop="date_deadline"/>')).toThrow(
            /must be of type date\/datetime/
        );
    });

    test("reads the progress field, but only if it can hold a number", () => {
        const archInfo = parse(
            '<gantt_soft date_start="date_start" date_stop="date_deadline" progress="progress" color="color_index"/>'
        );
        expect(archInfo.progressField).toBe("progress");
        expect(archInfo.colorField).toBe("color_index");
        expect(() =>
            parse(
                '<gantt_soft date_start="date_start" date_stop="date_deadline" progress="user_id"/>'
            )
        ).toThrow(/must be of type float\/integer/);
    });

    test("refuses a colour field that is not a colour index", () => {
        expect(() =>
            parse(
                '<gantt_soft date_start="date_start" date_stop="date_deadline" color="name"/>'
            )
        ).toThrow(/must be of type integer/);
    });

    test("keeps the scales the view offers, in order", () => {
        const archInfo = parse(
            '<gantt_soft date_start="date_start" date_stop="date_deadline" scales="day,week,month" mode="week"/>'
        );
        expect(archInfo.scales).toEqual(["day", "week", "month"]);
        expect(archInfo.scale).toBe("week");
    });

    test("falls back to the first scale of the view", () => {
        const archInfo = parse(
            '<gantt_soft date_start="date_start" date_stop="date_deadline" scales="week"/>'
        );
        expect(archInfo.scale).toBe("week");
    });

    test("defaults to the month scale", () => {
        expect(parse('<gantt_soft date_start="date_start" date_stop="date_deadline"/>').scale).toBe(
            "month"
        );
    });

    test("refuses an empty scales list", () => {
        expect(() =>
            parse('<gantt_soft date_start="date_start" date_stop="date_deadline" scales=""/>')
        ).toThrow(/No usable scale/);
    });
    test("refuses a scale name it cannot draw", () => {
        expect(() =>
            parse(
                '<gantt_soft date_start="date_start" date_stop="date_deadline" scales="day,decade"/>'
            )
        ).toThrow(/Invalid scale/);
    });

    test("refuses a mode the client cannot draw", () => {
        expect(() =>
            parse('<gantt_soft date_start="date_start" date_stop="date_deadline" mode="decade"/>')
        ).toThrow(/Invalid mode/);
    });

    test("refuses a mode that is not one of the offered scales", () => {
        expect(() =>
            parse(
                '<gantt_soft date_start="date_start" date_stop="date_deadline" scales="week,month" mode="day"/>'
            )
        ).toThrow(/Invalid mode/);
    });

    test("refuses a limit that is not a positive number", () => {
        expect(() =>
            parse('<gantt_soft date_start="date_start" date_stop="date_deadline" limit="0"/>')
        ).toThrow(/positive integer/);
    });

    test("keeps the rights the server wrote into the arch", () => {
        // `ir.ui.view` writes create/delete/edit="False" when the user lacks
        // the matching right: the client must read them, not guess them.
        const archInfo = parse(
            '<gantt_soft date_start="date_start" date_stop="date_deadline" create="False" edit="False" delete="False"/>'
        );
        expect(archInfo.activeActions.create).toBe(false);
        expect(archInfo.activeActions.edit).toBe(false);
        expect(archInfo.activeActions.delete).toBe(false);

        const openInfo = parse('<gantt_soft date_start="date_start" date_stop="date_deadline"/>');
        expect(openInfo.activeActions.create).toBe(true);
        expect(openInfo.activeActions.edit).toBe(true);
    });

    test("reads the click behaviour the view asks for", () => {
        const archInfo = parse(
            '<gantt_soft date_start="date_start" date_stop="date_deadline" open_form_view="1"/>'
        );
        expect(archInfo.openFormView).toBe(true);
        expect(parse('<gantt_soft date_start="date_start" date_stop="date_deadline"/>').openFormView).toBe(false);
    });

    test("reads the window the view opens on", () => {
        const archInfo = parse(
            '<gantt_soft date_start="date_start" date_stop="date_deadline" default_range="quarter"/>'
        );
        expect(archInfo.range).toBe("quarter");
    });

    test("opens on a month when the arch says nothing", () => {
        expect(parse('<gantt_soft date_start="date_start" date_stop="date_deadline"/>').range).toBe(
            "month"
        );
    });

    test("refuses a window it cannot align", () => {
        expect(() =>
            parse(
                '<gantt_soft date_start="date_start" date_stop="date_deadline" default_range="fortnight"/>'
            )
        ).toThrow(/Invalid default_range/);
    });

    test("reads the field the rows are grouped by", () => {
        const archInfo = parse(
            '<gantt_soft date_start="date_start" date_stop="date_deadline" group_by="user_id"/>'
        );
        expect(archInfo.groupByField).toBe("user_id");
    });

    test("refuses a group field the model does not have", () => {
        expect(() =>
            parse('<gantt_soft date_start="date_start" date_stop="date_deadline" group_by="nope"/>')
        ).toThrow(/is not defined on project.task/);
    });

    test("refuses to group on the timeline itself", () => {
        // One row per date is not a schedule, so the field type is refused.
        expect(() =>
            parse(
                '<gantt_soft date_start="date_start" date_stop="date_deadline" group_by="date_start"/>'
            )
        ).toThrow(/must be of type char\/text\/selection\/integer\/many2one\/boolean/);
    });

    test("refuses to group on a relational list", () => {
        expect(() =>
            parse(
                '<gantt_soft date_start="date_start" date_stop="date_deadline" group_by="tag_ids"/>'
            )
        ).toThrow(/must be of type char\/text\/selection\/integer\/many2one\/boolean/);
    });

    test("carries the labels of the selection fields it reads", () => {
        const archInfo = parse(
            '<gantt_soft date_start="date_start" date_stop="date_deadline" label="state" group_by="state"><field name="state"/></gantt_soft>'
        );
        expect(archInfo.selectionLabels.state).toEqual({ draft: "Draft", done: "Done" });
    });

    test("collects the declared field nodes", () => {
        const archInfo = parse(
            '<gantt_soft date_start="date_start" date_stop="date_deadline"><field name="user_id"/><field name="progress"/></gantt_soft>'
        );
        expect(Object.keys(archInfo.fieldNodes).sort()).toEqual(["progress_0", "user_id_0"]);
        expect(archInfo.fieldNodes.user_id_0.name).toBe("user_id");
    });

    test("refuses a declared field it could not render", () => {
        expect(() =>
            parse(
                '<gantt_soft date_start="date_start" date_stop="date_deadline"><field name="tag_ids"/></gantt_soft>'
            )
        ).toThrow(/cannot be declared in a gantt_soft view/);
    });
});
