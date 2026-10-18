import { registry } from "@web/core/registry";

import { GanttSoftArchParser } from "./gantt_arch_parser";
import { GanttSoftController } from "./gantt_controller";
import { GanttSoftModel } from "./gantt_model";
import { GanttSoftRenderer } from "./gantt_renderer";

/**
 * The `gantt_soft` view type.
 *
 * Registering the type in the `views` registry, plus the `selection_add` on
 * `ir.ui.view.type` (server side), is what makes `<gantt_soft>` a first class
 * view: it can be listed in any action's `view_mode` and the view switcher
 * offers it like a list or a kanban.
 *
 * `searchMenuTypes` only advertises what the view really does: filters and
 * favourites reload the records, grouping is deliberately absent (offering a
 * menu entry that changes nothing is worse than not offering it).
 */
export const ganttSoftView = {
    type: "gantt_soft",
    display_name: "Gantt",
    icon: "fa fa-tasks",
    multiRecord: true,

    ArchParser: GanttSoftArchParser,
    Controller: GanttSoftController,
    Model: GanttSoftModel,
    Renderer: GanttSoftRenderer,

    searchMenuTypes: ["filter", "favorite"],

    props: (props, view) => {
        const { arch, relatedModels, resModel } = props;
        const archInfo = new view.ArchParser().parse(arch, relatedModels, resModel, props.jsClass);
        return {
            ...props,
            archInfo,
            Model: view.Model,
            Renderer: view.Renderer,
        };
    },
};

registry.category("views").add("gantt_soft", ganttSoftView);
