import { after, describe, expect, getFixture, test } from "@odoo/hoot";
import { queryAll, queryFirst } from "@odoo/hoot-dom";
import { animationFrame } from "@odoo/hoot-mock";
import { App } from "@odoo/owl";
import { getTemplate, registerTemplate } from "@web/core/templates";

import { GanttSoftPopover } from "@soft_gantt/gantt/gantt_popover";

const TEMPLATE_NAME = "soft_gantt.GanttPopover";
const TEMPLATE_URL = "/soft_gantt/static/src/gantt/gantt_popover.xml";

/**
 * Mount the card on its own: it holds no logic beyond what it is handed, so
 * the assertions can be exact about what a reader sees.
 */
async function mountPopover(props) {
    if (!getTemplate(TEMPLATE_NAME)) {
        const response = await fetch(TEMPLATE_URL);
        registerTemplate(TEMPLATE_NAME, TEMPLATE_URL, await response.text());
    }
    const target = document.createElement("div");
    getFixture().append(target);
    const app = new App(GanttSoftPopover, { props, getTemplate, test: true });
    app.mount(target);
    after(() => {
        app.destroy();
        target.remove();
    });
    await animationFrame();
}

function texts(selector) {
    return queryAll(selector).map((element) => element.textContent);
}

describe("GanttSoftPopover", () => {
    test("shows the title and the pairs it is given", async () => {
        await mountPopover({
            title: "ACME / Roof repair",
            fields: [
                { label: "Start", value: "02 Oct 2026 08:00:00" },
                { label: "Team", value: "North" },
            ],
            close: () => {},
        });

        expect(queryFirst(".o_gantt_soft_popover_title").textContent).toBe(
            "ACME / Roof repair"
        );
        expect(texts(".o_gantt_soft_popover_fields dt")).toEqual(["Start", "Team"]);
        expect(texts(".o_gantt_soft_popover_fields dd")).toEqual([
            "02 Oct 2026 08:00:00",
            "North",
        ]);
    });

    test("leaves out the values the record does not carry", async () => {
        await mountPopover({
            title: "Empty fields",
            fields: [
                { label: "Set", value: "kept" },
                { label: "Blank", value: "" },
                { label: "Missing", value: false },
            ],
            close: () => {},
        });

        expect(texts(".o_gantt_soft_popover_fields dt")).toEqual(["Set"]);
    });

    test("keeps a zero, which is a value", async () => {
        await mountPopover({
            title: "Zero",
            fields: [{ label: "Progress", value: 0 }],
            close: () => {},
        });

        expect(texts(".o_gantt_soft_popover_fields dd")).toEqual(["0"]);
    });

    test("shows no action when the view offers none", async () => {
        await mountPopover({ title: "Read only", fields: [], close: () => {} });

        expect(".o_gantt_soft_popover_fields").toHaveCount(0);
        expect(".popover-footer").toHaveCount(0);
    });

    test("opens the record through the action it is given", async () => {
        let opened = 0;
        await mountPopover({
            title: "ACME",
            fields: [],
            open: () => opened++,
            close: () => {},
        });

        queryFirst(".popover-footer button").dispatchEvent(
            new MouseEvent("click", { bubbles: true })
        );
        await animationFrame();
        expect(opened).toBe(1);
    });

    test("closes itself on the close button", async () => {
        let closed = 0;
        await mountPopover({ title: "ACME", fields: [], close: () => closed++ });

        queryFirst(".btn-close").dispatchEvent(new MouseEvent("click", { bubbles: true }));
        await animationFrame();
        expect(closed).toBe(1);
    });

    test("shows the actions it is given, before the form button", async () => {
        const clicked = [];
        await mountPopover({
            title: "ACME",
            fields: [],
            buttons: [
                {
                    key: "object:action_done",
                    label: "Done",
                    icon: "fa fa-check",
                    className: "btn-danger",
                    onClick: () => clicked.push("done"),
                },
                {
                    key: "action:base.action_partner_form",
                    label: "Open partner",
                    icon: "",
                    className: "",
                    onClick: () => clicked.push("open"),
                },
            ],
            open: () => {},
            close: () => {},
        });

        const actions = queryAll(".o_gantt_soft_popover_action");
        expect(actions.length).toBe(2);
        expect(actions.map((button) => button.textContent.trim())).toEqual([
            "Done",
            "Open partner",
        ]);
        expect(actions[0].classList.contains("btn-danger")).toBe(true);
        // The form button stays the explicit navigation after the actions.
        expect(queryAll(".popover-footer button").at(-1).textContent.trim()).toBe("Open");

        actions[0].dispatchEvent(new MouseEvent("click", { bubbles: true }));
        await animationFrame();
        expect(clicked).toEqual(["done"]);
    });

    test("shows the footer when there are only actions", async () => {
        await mountPopover({
            title: "No form",
            fields: [],
            buttons: [
                { key: "object:done", label: "Done", icon: "", className: "", onClick: () => {} },
            ],
            close: () => {},
        });

        expect(".popover-footer").toHaveCount(1);
        expect(".o_gantt_soft_popover_action").toHaveCount(1);
        // No form navigation when the view does not offer it.
        expect(".popover-footer .btn-primary").toHaveCount(0);
    });

    test("an icon only action has no text", async () => {
        await mountPopover({
            title: "Icon",
            fields: [],
            buttons: [
                { key: "object:done", label: "", icon: "fa fa-check", className: "", onClick: () => {} },
            ],
            close: () => {},
        });

        const action = queryFirst(".o_gantt_soft_popover_action");
        expect(action.textContent.trim()).toBe("");
        expect(action.querySelector(".fa-check")).not.toBe(null);
    });
});
