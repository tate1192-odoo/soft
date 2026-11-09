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
            // The metadata the server sends with a view: the two date fields are
            // also read with a domain, so the parser refuses one the ORM cannot
            // filter on (`searchable` is the server's `store or search`).
            stored_date: { type: "datetime", store: true, searchable: true },
            computed_date: { type: "datetime", store: false, searchable: false },
            searched_date: { type: "datetime", store: false, searchable: true },
            progress: { type: "float" },
            color_index: { type: "integer" },
            user_id: { type: "many2one", relation: "res.users" },
            tag_ids: { type: "many2many", relation: "project.tags" },
            depends_on: { type: "many2many", relation: "project.task" },
            is_milestone: { type: "boolean" },
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

    test("refuses a date field the window cannot be filtered on", () => {
        // A computed field without a search method: the server cannot read the
        // window with a domain on it, so the view must be refused instead of
        // installing and failing when it is opened.
        expect(() =>
            parse('<gantt_soft date_start="computed_date" date_stop="date_deadline"/>')
        ).toThrow(/must be stored or searchable/);
        expect(() =>
            parse('<gantt_soft date_start="date_start" date_stop="computed_date"/>')
        ).toThrow(/must be stored or searchable/);
    });

    test("accepts a searchable date field that is not stored", () => {
        const archInfo = parse(
            '<gantt_soft date_start="searched_date" date_stop="date_deadline"/>'
        );
        expect(archInfo.dateStart).toBe("searched_date");
        // A stored field carries no explicit metadata in a bare arch, and it is
        // accepted as before.
        expect(parse('<gantt_soft date_start="stored_date" date_stop="date_deadline"/>').dateStart).toBe(
            "stored_date"
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

    test("reads the milestone field", () => {
        const archInfo = parse(
            '<gantt_soft date_start="date_start" date_stop="date_deadline" milestone="is_milestone"/>'
        );
        expect(archInfo.milestoneField).toBe("is_milestone");
    });

    test("refuses a milestone field that is not a boolean", () => {
        expect(() =>
            parse('<gantt_soft date_start="date_start" date_stop="date_deadline" milestone="name"/>')
        ).toThrow(/must be of type boolean/);
    });

    test("reads the dependencies list", () => {
        const archInfo = parse(
            '<gantt_soft date_start="date_start" date_stop="date_deadline" dependencies="depends_on"/>'
        );
        expect(archInfo.dependenciesField).toBe("depends_on");
    });

    test("refuses a dependencies field that points at another model", () => {
        // An arrow joins two bars of this view: a list of tags has nothing to
        // join it to.
        expect(() =>
            parse(
                '<gantt_soft date_start="date_start" date_stop="date_deadline" dependencies="tag_ids"/>'
            )
        ).toThrow(/must point at project.task/);
    });

    test("refuses a dependencies field that is not a relational list", () => {
        expect(() =>
            parse(
                '<gantt_soft date_start="date_start" date_stop="date_deadline" dependencies="state"/>'
            )
        ).toThrow(/must be of type many2many\/one2many/);
    });

    test("accepts the quarter and year scales", () => {
        const archInfo = parse(
            '<gantt_soft date_start="date_start" date_stop="date_deadline" scales="day,week,month,quarter,year" mode="quarter"/>'
        );
        expect(archInfo.scales).toEqual(["day", "week", "month", "quarter", "year"]);
        expect(archInfo.scale).toBe("quarter");
    });

    test("reads decoration expressions", () => {
        const archInfo = parse(
            '<gantt_soft date_start="date_start" date_stop="date_deadline" ' +
                'decoration-danger="state == \'done\'" decoration-success="progress &gt;= 100"/>'
        );
        expect(archInfo.decorations).toEqual([
            { name: "danger", condition: "state == 'done'" },
            { name: "success", condition: "progress >= 100" },
        ]);
    });

    test("refuses an unknown decoration name", () => {
        expect(() =>
            parse(
                '<gantt_soft date_start="date_start" date_stop="date_deadline" decoration-whatever="true"/>'
            )
        ).toThrow(/Invalid decoration/);
    });

    test("refuses an empty decoration expression", () => {
        expect(() =>
            parse(
                '<gantt_soft date_start="date_start" date_stop="date_deadline" decoration-danger=""/>'
            )
        ).toThrow(/must be an expression/);
    });

    test("collects the fields a decoration reads", () => {
        // A runtime-built arch has no server-added hidden field node: the parser
        // reads the identifiers out of the expression so the read can request
        // the field the expression needs.
        const archInfo = parse(
            '<gantt_soft date_start="date_start" date_stop="date_deadline" decoration-danger="state == \'done\'"/>'
        );
        expect(archInfo.expressionFields.includes("state")).toBe(true);
        // Strings in the expression are not field names.
        expect(archInfo.expressionFields.includes("done")).toBe(false);
    });

    test("a hidden field is loaded but not rendered in the card", () => {
        const archInfo = parse(
            '<gantt_soft date_start="date_start" date_stop="date_deadline" ' +
                'decoration-danger="state == \'done\'"><field name="state" invisible="True"/></gantt_soft>'
        );
        expect(Object.keys(archInfo.fieldNodes)).toEqual([]);
        expect(archInfo.expressionFields.includes("state")).toBe(true);
    });

    test("reads the group_total field and its type", () => {
        const archInfo = parse(
            '<gantt_soft date_start="date_start" date_stop="date_deadline" group_by="user_id" group_total="progress"/>'
        );
        expect(archInfo.groupTotalField).toBe("progress");

        expect(() =>
            parse(
                '<gantt_soft date_start="date_start" date_stop="date_deadline" group_total="name"/>'
            )
        ).toThrow(/must be of type integer\/float/);
    });

    test("reads the group avatar and refuses it without a many2one group_by", () => {
        const archInfo = parse(
            '<gantt_soft date_start="date_start" date_stop="date_deadline" group_by="user_id" group_avatar="avatar_128"/>'
        );
        expect(archInfo.groupAvatarField).toBe("avatar_128");

        expect(() =>
            parse(
                '<gantt_soft date_start="date_start" date_stop="date_deadline" group_avatar="avatar_128"/>'
            )
        ).toThrow(/requires "group_by"/);

        expect(() =>
            parse(
                '<gantt_soft date_start="date_start" date_stop="date_deadline" group_by="state" group_avatar="avatar_128"/>'
            )
        ).toThrow(/requires a many2one "group_by"/);
    });

    test("reads collapse_first_level and cell_create, false by default", () => {
        const defaults = parse('<gantt_soft date_start="date_start" date_stop="date_deadline"/>');
        expect(defaults.collapseFirstLevel).toBe(false);
        expect(defaults.cellCreate).toBe(false);

        const archInfo = parse(
            '<gantt_soft date_start="date_start" date_stop="date_deadline" collapse_first_level="true" cell_create="1"/>'
        );
        expect(archInfo.collapseFirstLevel).toBe(true);
        expect(archInfo.cellCreate).toBe(true);
    });

    test("refuses a boolean spelling the client would read differently", () => {
        // `str2bool` accepts no/off as false while `exprToBoolean` reads them
        // as true: only the values both sides read the same way are accepted.
        for (const value of ["no", "off", "yes", "sometimes"]) {
            expect(() =>
                parse(
                    `<gantt_soft date_start="date_start" date_stop="date_deadline" cell_create="${value}"/>`
                )
            ).toThrow(/must be a boolean/);
        }
    });

    test("reads a group_by list as grouping levels", () => {
        const archInfo = parse(
            '<gantt_soft date_start="date_start" date_stop="date_deadline" group_by="user_id,state"/>'
        );
        expect(archInfo.groupByFields).toEqual(["user_id", "state"]);
        // The first level keeps its own name for the avatar and the default
        // folding, which are single level attributes.
        expect(archInfo.groupByField).toBe("user_id");
    });

    test("refuses an invalid field on any grouping level", () => {
        expect(() =>
            parse(
                '<gantt_soft date_start="date_start" date_stop="date_deadline" group_by="user_id,nope"/>'
            )
        ).toThrow(/Unknown field|not defined/);

        expect(() =>
            parse(
                '<gantt_soft date_start="date_start" date_stop="date_deadline" group_by="user_id,date_start"/>'
            )
        ).toThrow(/must be of type/);
    });

    test("refuses an empty group_by list", () => {
        expect(() =>
            parse('<gantt_soft date_start="date_start" date_stop="date_deadline" group_by=","/>')
        ).toThrow(/at least one field/);
    });

    test("the group avatar reads the outer level of a multi-level group", () => {
        // user_id is the outer many2one: the avatar is its image field.
        const archInfo = parse(
            '<gantt_soft date_start="date_start" date_stop="date_deadline" group_by="user_id,state" group_avatar="avatar_128"/>'
        );
        expect(archInfo.groupAvatarField).toBe("avatar_128");

        expect(() =>
            parse(
                '<gantt_soft date_start="date_start" date_stop="date_deadline" group_by="state,user_id" group_avatar="avatar_128"/>'
            )
        ).toThrow(/requires a many2one "group_by"/);

    });
    test("reads the buttons of the details card, in arch order", () => {
        const archInfo = parse(
            '<gantt_soft date_start="date_start" date_stop="date_deadline">' +
                '<button name="action_done" type="object" string="Done" icon="fa fa-check" ' +
                'confirm="Close the task?" class="btn-danger"/>' +
                '<button name="base.action_partner_form" type="action" string="Open"/>' +
                '</gantt_soft>'
        );
        expect(archInfo.buttons).toEqual([
            {
                name: "action_done",
                type: "object",
                string: "Done",
                icon: "fa fa-check",
                confirm: "Close the task?",
                class: "btn-danger",
            },
            {
                name: "base.action_partner_form",
                type: "action",
                string: "Open",
                icon: "",
                confirm: "",
                class: "",
            },
        ]);
    });

    test("an icon alone is enough for a card button", () => {
        const archInfo = parse(
            '<gantt_soft date_start="date_start" date_stop="date_deadline">' +
                '<button name="action_done" type="object" icon="fa fa-check"/></gantt_soft>'
        );
        expect(archInfo.buttons.length).toBe(1);
        expect(archInfo.buttons[0].string).toBe("");
        expect(archInfo.buttons[0].icon).toBe("fa fa-check");
    });

    test("refuses an invalid card button", () => {
        for (const button of [
            // No name.
            '<button type="object" string="Done"/>',
            // Not a supported type.
            '<button name="action_done" type="method" string="Done"/>',
            // Nothing would be drawn.
            '<button name="action_done" type="object"/>',
            // An attribute the card does not know.
            '<button name="action_done" type="object" string="Done" invisible="True"/>',
        ]) {
            expect(() =>
                parse(
                    `<gantt_soft date_start="date_start" date_stop="date_deadline">${button}</gantt_soft>`
                )
            ).toThrow(/button/);
        }
    });


    test("reads the precision of the scales", () => {
        const archInfo = parse(
            '<gantt_soft date_start="date_start" date_stop="date_deadline" ' +
                'scales="day,week,month" ' +
                'precision="{\'day\': \'hour:quarter\', \'week\': \'day:half\'}"/>'
        );
        expect(archInfo.precision).toEqual({
            day: { unit: "hour", parts: 4 },
            week: { unit: "day", parts: 2 },
        });
    });

    test("refuses a precision that does not fit the scale's cells", () => {
        for (const precision of [
            // The day scale's cells are hours.
            "{'day': 'day:half'}",
            // Only full, half and quarter exist.
            "{'day': 'hour:eighth'}",
            // Quarter cells (weeks) cannot be subdivided.
            "{'quarter': 'week:half'}",
            // Not a scale.
            "{'fortnight': 'day:half'}",
            // Not a dict at all.
            "'day'",
        ]) {
            expect(() =>
                parse(
                    `<gantt_soft date_start="date_start" date_stop="date_deadline" precision="${precision}"/>`
                )
            ).toThrow(/precision/);
        }
    });
});
