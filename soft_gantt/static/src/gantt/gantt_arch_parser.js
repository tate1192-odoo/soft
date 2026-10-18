import { exprToBoolean } from "@web/core/utils/strings";
import { stringToOrderBy } from "@web/search/utils/order_by";
import { visitXML } from "@web/core/utils/xml";

import { WINDOW_RANGES } from "./gantt_utils";
import { Field } from "@web/views/fields/field";
import { getActiveActions } from "@web/views/utils";

const SCALES = ["day", "week", "month"];

/** Arch attribute -> the field types it accepts (kept in sync with the server). */
const FIELD_ATTRIBUTES = {
    date_start: ["date", "datetime"],
    date_stop: ["date", "datetime"],
    label: ["char", "text", "selection", "integer", "float", "many2one"],
    progress: ["float", "integer"],
    color: ["integer"],
    // The row a record is drawn on. A date is the timeline itself and a float
    // would give one row per value, so neither is accepted.
    group_by: ["char", "text", "selection", "integer", "many2one", "boolean"],
};

/** Types a declared `<field>` node can render in a tooltip or the card. */
const FIELD_NODE_TYPES = [
    "char",
    "text",
    "selection",
    "integer",
    "float",
    "monetary",
    "many2one",
    "date",
    "datetime",
    "boolean",
];

const DEFAULT_LIMIT = 500;

/**
 * Read a `<gantt_soft>` arch.
 *
 * The view names its own date fields, so the type is generic. The parsing is
 * strict: a missing date field or an unknown field type throws immediately,
 * which is what turns a broken view into a readable error instead of an empty
 * screen. The server does the same checks at install time; this second pass
 * also covers views built at runtime by other modules.
 */
export class GanttSoftArchParser {
    parse(xmlDoc, models, modelName, jsClass) {
        const fields = models[modelName].fields;
        if (!fields) {
            throw new Error(`Model "${modelName}" has no fields.`);
        }

        const archInfo = {
            activeActions: getActiveActions(xmlDoc),
            jsClass,
            fieldNodes: {},
            dateStart: "",
            dateStartType: "datetime",
            dateStop: "",
            dateStopType: "datetime",
            labelField: "",
            groupByField: "",
            selectionLabels: {},
            progressField: "",
            colorField: "",
            scales: [...SCALES],
            scale: "month",
            range: "month",
            limit: DEFAULT_LIMIT,
            openFormView: exprToBoolean(xmlDoc.getAttribute("open_form_view")),
            defaultOrder: stringToOrderBy(xmlDoc.getAttribute("default_order") || null),
        };

        for (const attribute of ["date_start", "date_stop"]) {
            const fieldName = xmlDoc.getAttribute(attribute);
            if (!fieldName) {
                throw new Error(`The "${attribute}" attribute is required in a gantt_soft view.`);
            }
            this._validateField(fields, modelName, fieldName, FIELD_ATTRIBUTES[attribute], attribute);
            if (attribute === "date_start") {
                archInfo.dateStart = fieldName;
                archInfo.dateStartType = fields[fieldName].type === "date" ? "date" : "datetime";
            } else {
                archInfo.dateStop = fieldName;
                archInfo.dateStopType = fields[fieldName].type === "date" ? "date" : "datetime";
            }
        }

        for (const attribute of ["progress", "color"]) {
            const fieldName = xmlDoc.getAttribute(attribute);
            if (!fieldName) {
                continue;
            }
            this._validateField(fields, modelName, fieldName, FIELD_ATTRIBUTES[attribute], attribute);
            if (attribute === "progress") {
                archInfo.progressField = fieldName;
            } else {
                archInfo.colorField = fieldName;
            }
        }

        const labelField = xmlDoc.getAttribute("label");
        if (labelField) {
            this._validateField(fields, modelName, labelField, FIELD_ATTRIBUTES.label, "label");
            archInfo.labelField = labelField;
            this._rememberSelection(archInfo, fields, labelField);
        }

        const scalesAttribute = xmlDoc.getAttribute("scales");
        if (scalesAttribute !== null) {
            const scales = scalesAttribute
                .split(",")
                .map((scale) => scale.trim())
                .filter(Boolean);
            if (!scales.length) {
                throw new Error(
                    `No usable scale in "scales" (expected a comma separated list of ${SCALES.join(", ")}).`
                );
            }
            const invalid = scales.filter((scale) => !SCALES.includes(scale));
            if (invalid.length) {
                throw new Error(
                    `Invalid scale(s) ${invalid.join(", ")} in "scales" (expected one of ${SCALES.join(", ")}).`
                );
            }
            archInfo.scales = [...new Set(scales)];
        }

        const mode = xmlDoc.getAttribute("mode");
        if (mode) {
            if (!archInfo.scales.includes(mode)) {
                throw new Error(
                    `Invalid mode "${mode}" (expected one of ${archInfo.scales.join(", ")}).`
                );
            }
            archInfo.scale = mode;
        } else {
            archInfo.scale = archInfo.scales.includes("month") ? "month" : archInfo.scales[0];
        }

        const groupBy = xmlDoc.getAttribute("group_by");
        if (groupBy) {
            this._validateField(
                fields,
                modelName,
                groupBy,
                FIELD_ATTRIBUTES.group_by,
                "group_by"
            );
            archInfo.groupByField = groupBy;
            this._rememberSelection(archInfo, fields, groupBy);
        }

        const defaultRange = xmlDoc.getAttribute("default_range");
        if (defaultRange) {
            if (!WINDOW_RANGES.includes(defaultRange)) {
                throw new Error(
                    `Invalid default_range "${defaultRange}" (expected one of ${WINDOW_RANGES.join(
                        ", "
                    )}).`
                );
            }
            archInfo.range = defaultRange;
        }

        const limit = xmlDoc.getAttribute("limit");
        if (limit) {
            const parsed = Number(limit);
            if (!Number.isInteger(parsed) || parsed <= 0) {
                throw new Error(`The "limit" of a gantt_soft view must be a positive integer, got "${limit}".`);
            }
            archInfo.limit = parsed;
        }

        // Optional <field> nodes: extra fields the view wants on the record,
        // shown in the bar tooltip and fetched in the same read.
        const fieldNextIds = {};
        visitXML(xmlDoc, (node) => {
            if (node.tagName !== "field") {
                return;
            }
            const fieldInfo = Field.parseFieldNode(node, models, modelName, "gantt_soft", jsClass);
            if (!FIELD_NODE_TYPES.includes(fieldInfo.type)) {
                throw new Error(
                    `Field "${fieldInfo.name}" of type ${fieldInfo.type} cannot be declared in a gantt_soft view.`
                );
            }
            const name = fieldInfo.name;
            this._rememberSelection(archInfo, fields, name);
            fieldNextIds[name] = fieldNextIds[name] || 0;
            const fieldId = `${name}_${fieldNextIds[name]++}`;
            archInfo.fieldNodes[fieldId] = fieldInfo;
            node.setAttribute("field_id", fieldId);
        });

        return archInfo;
    }

    /**
     * Remember the labels of a selection field.
     *
     * A selection is stored as a key (`in_progress`) while a human reads the
     * label (`In Progress`); the label is not in the record, so it comes from
     * the field description and travels with the arch info.
     */
    _rememberSelection(archInfo, fields, fieldName) {
        const field = fields[fieldName];
        if (field?.type === "selection") {
            archInfo.selectionLabels[fieldName] = Object.fromEntries(field.selection || []);
        }
    }

    _validateField(fields, modelName, fieldName, allowedTypes, attribute) {
        const field = fields[fieldName];
        if (!field) {
            throw new Error(
                `Field "${fieldName}" used as ${attribute} is not defined on ${modelName}.`
            );
        }
        if (!allowedTypes.includes(field.type)) {
            throw new Error(
                `Field "${fieldName}" used as ${attribute} must be of type ${allowedTypes.join("/")}, not ${field.type}.`
            );
        }
    }
}
