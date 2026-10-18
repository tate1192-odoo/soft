import { Component } from "@odoo/owl";

/**
 * Card opened next to a bar.
 *
 * A click used to jump straight to the form, which took the reader away from
 * the chart they were scanning; the card shows the figures the bar carries and
 * offers the form as an explicit action instead. The popover service injects
 * `close`, and the controller decides what the pairs are.
 */
export class GanttSoftPopover extends Component {
    static template = "soft_gantt.GanttPopover";
    static props = {
        title: String,
        fields: Array,
        open: { type: Function, optional: true },
        close: Function,
    };

    /** Values the record does not carry are not worth a line. */
    get fields() {
        return this.props.fields.filter(
            (field) => field.value || field.value === 0
        );
    }
}
