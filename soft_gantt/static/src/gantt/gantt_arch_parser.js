import { exprToBoolean } from "@web/core/utils/strings";
import { evaluateExpr } from "@web/core/py_js/py";
import { stringToOrderBy } from "@web/search/utils/order_by";
import { visitXML } from "@web/core/utils/xml";

import {
    CELL_PRECISIONS,
    PRECISION_SCALES,
    SCALE_UNITS,
    WINDOW_RANGES,
} from "./gantt_utils";
import { Field } from "@web/views/fields/field";
import { getActiveActions } from "@web/views/utils";

const SCALES = ["day", "week", "month", "quarter", "year"];

/** Values a boolean arch attribute can carry (kept in sync with the server). */
const BOOLEAN_VALUES = ["0", "1", "true", "false"];

/** Bar decorations, drawn as a ring on the bar whose record matches. */
export const DECORATIONS = ["danger", "info", "secondary", "success", "warning"];

/** The kinds of button the details card can offer. */
const BUTTON_TYPES = ["object", "action"];

/** Attributes a <button> child can carry (kept in sync with the server). */
const BUTTON_ATTRIBUTES = ["name", "type", "string", "icon", "confirm", "class"];

/** Arch attribute -> the field types it accepts (kept in sync with the server). */
const FIELD_ATTRIBUTES = {
    date_start: ["date", "datetime"],
    date_stop: ["date", "datetime"],
    label: ["char", "text", "selection", "integer", "float", "many2one"],
    progress: ["float", "integer"],
    color: ["integer"],
    // A record flagged by this boolean field is drawn as a milestone: a diamond
    // on its date instead of a bar.
    milestone: ["boolean"],
    // The list of records that must finish first: the renderer draws an arrow
    // from each of them to this record.
    dependencies: ["many2many", "one2many"],
    // The row a record is drawn on. A date is the timeline itself and a float
    // would give one row per value, so neither is accepted.
    group_by: ["char", "text", "selection", "integer", "many2one", "boolean"],
    // A numeric field summed over the records of a group, shown on its row.
    group_total: ["integer", "float"],
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
            groupByFields: [],
            groupTotalField: "",
            groupAvatarField: "",
            collapseFirstLevel: false,
            cellCreate: false,
            decorations: [],
            expressionFields: [],
            buttons: [],
            milestoneField: "",
            dependenciesField: "",
            selectionLabels: {},
            progressField: "",
            colorField: "",
            scales: [...SCALES],
            scale: "month",
            precision: {},
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
            // The window is read with a domain on the two dates, so a field the
            // server cannot filter on would make the view fail when it is
            // opened. `searchable` is computed by the server as "stored or has a
            // search method"; the metadata is absent on a bare test arch, which
            // is why the check is on an explicit `false`.
            if (fields[fieldName].searchable === false) {
                throw new Error(
                    `Field "${fieldName}" used as ${attribute} must be stored or searchable: the window is read with a domain on it.`
                );
            }
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

        const milestoneField = xmlDoc.getAttribute("milestone");
        if (milestoneField) {
            this._validateField(fields, modelName, milestoneField, FIELD_ATTRIBUTES.milestone, "milestone");
            archInfo.milestoneField = milestoneField;
        }

        const dependenciesField = xmlDoc.getAttribute("dependencies");
        if (dependenciesField) {
            this._validateField(
                fields,
                modelName,
                dependenciesField,
                FIELD_ATTRIBUTES.dependencies,
                "dependencies"
            );
            // An arrow joins two bars of this view, so the list must point back
            // at the view's own model: a list of another model has nothing to
            // join it to.
            if (fields[dependenciesField].relation !== modelName) {
                throw new Error(
                    `Field "${dependenciesField}" used as dependencies must point at ${modelName}, not at ${fields[dependenciesField].relation}.`
                );
            }
            archInfo.dependenciesField = dependenciesField;
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
            // A comma separated list groups on several levels: the first field
            // makes the outer rows, the second the rows inside them, and the
            // last one holds the records (the bars). A single field is the one
            // level case of the same tree.
            const groupByFields = groupBy
                .split(",")
                .map((fieldName) => fieldName.trim())
                .filter(Boolean);
            if (!groupByFields.length) {
                throw new Error(
                    `The "group_by" attribute of a gantt_soft view must name at least one field.`
                );
            }
            for (const fieldName of groupByFields) {
                this._validateField(
                    fields,
                    modelName,
                    fieldName,
                    FIELD_ATTRIBUTES.group_by,
                    "group_by"
                );
                this._rememberSelection(archInfo, fields, fieldName);
            }
            archInfo.groupByFields = groupByFields;
            // The first level keeps its own name: the optional group avatar is
            // read from it, and it is the level "first" refers to when the view
            // starts folded.
            archInfo.groupByField = groupByFields[0];
        }

        const groupTotal = xmlDoc.getAttribute("group_total");
        if (groupTotal) {
            this._validateField(
                fields,
                modelName,
                groupTotal,
                FIELD_ATTRIBUTES.group_total,
                "group_total"
            );
            archInfo.groupTotalField = groupTotal;
        }

        const groupAvatar = xmlDoc.getAttribute("group_avatar");
        if (groupAvatar) {
            if (!archInfo.groupByField) {
                throw new Error(
                    `The "group_avatar" attribute requires "group_by": there is no group row to draw it on.`
                );
            }
            if (fields[archInfo.groupByField].type !== "many2one") {
                throw new Error(
                    `The "group_avatar" attribute requires a many2one "group_by", not a ${fields[archInfo.groupByField].type}.`
                );
            }
            archInfo.groupAvatarField = groupAvatar;
        }

        // A bar carries a ring when its record matches an expression, the way a
        // list row is decorated: the expression is evaluated on the record by
        // the renderer. The fields it reads are collected below, from the arch
        // (the server adds them when they are not declared) and from the
        // expressions themselves (for views built at runtime).
        for (const name of xmlDoc.getAttributeNames()) {
            if (name.startsWith("decoration-")) {
                const decoration = name.slice("decoration-".length);
                if (!DECORATIONS.includes(decoration)) {
                    throw new Error(
                        `Invalid decoration "${name}" in a gantt_soft view (expected one of ${DECORATIONS.map(
                            (decoration) => `decoration-${decoration}`
                        ).join(", ")}).`
                    );
                }
                const condition = xmlDoc.getAttribute(name);
                if (!condition.trim()) {
                    throw new Error(`The "${name}" attribute of a gantt_soft view must be an expression.`);
                }
                archInfo.decorations.push({ name: decoration, condition });
            }
        }

        archInfo.collapseFirstLevel = this._readBoolean(xmlDoc, "collapse_first_level");
        archInfo.cellCreate = this._readBoolean(xmlDoc, "cell_create");

        const precisionAttribute = xmlDoc.getAttribute("precision");
        if (precisionAttribute !== null) {
            // The attribute is a Python literal, read like the expressions of
            // the other views: {"day": "hour:quarter", "week": "day:half"}.
            let precision;
            try {
                precision = evaluateExpr(precisionAttribute);
            } catch {
                throw new Error(
                    `The "precision" of a gantt_soft view must be a dict like {'day': 'hour:quarter'}.`
                );
            }
            if (!precision || typeof precision !== "object" || Array.isArray(precision)) {
                throw new Error(
                    `The "precision" of a gantt_soft view must be a dict like {'day': 'hour:quarter'}.`
                );
            }
            for (const [scale, specification] of Object.entries(precision)) {
                if (!SCALES.includes(scale)) {
                    throw new Error(
                        `Invalid scale "${scale}" in "precision" (expected one of ${SCALES.join(", ")}).`
                    );
                }
                if (!PRECISION_SCALES.includes(scale)) {
                    throw new Error(
                        `The "${scale}" scale has no cells that can be subdivided: "precision" is available on ${PRECISION_SCALES.join(", ")}.`
                    );
                }
                const cellUnit = SCALE_UNITS[scale];
                const [unit, precisionName] = String(specification).split(":");
                if (unit !== cellUnit || !(precisionName in CELL_PRECISIONS)) {
                    throw new Error(
                        `Invalid precision "${specification}" for the "${scale}" scale (expected "${cellUnit}:${Object.keys(
                            CELL_PRECISIONS
                        ).join("|")}").`
                    );
                }
                archInfo.precision[scale] = {
                    unit,
                    parts: CELL_PRECISIONS[precisionName],
                };
            }
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
            if (node.tagName === "button") {
                archInfo.buttons.push(this._parseButton(node));
                return;
            }
            if (node.tagName !== "field") {
                return;
            }
            const name = node.getAttribute("name");
            // The server adds a hidden <field> for a field only an expression
            // reads (a decoration): it has to be loaded, not rendered in the
            // card. The same shape lets a consumer declare a field it only uses
            // from an expression.
            const invisible = node.getAttribute("invisible");
            if (invisible === "True" || invisible === "1") {
                if (name && fields[name]) {
                    this._rememberSelection(archInfo, fields, name);
                    archInfo.expressionFields.push(name);
                }
                return;
            }
            const fieldInfo = Field.parseFieldNode(node, models, modelName, "gantt_soft", jsClass);
            if (!FIELD_NODE_TYPES.includes(fieldInfo.type)) {
                throw new Error(
                    `Field "${fieldInfo.name}" of type ${fieldInfo.type} cannot be declared in a gantt_soft view.`
                );
            }
            const fieldName = fieldInfo.name;
            this._rememberSelection(archInfo, fields, fieldName);
            fieldNextIds[fieldName] = fieldNextIds[fieldName] || 0;
            const fieldId = `${fieldName}_${fieldNextIds[fieldName]++}`;
            archInfo.fieldNodes[fieldId] = fieldInfo;
            node.setAttribute("field_id", fieldId);
        });

        // A view built at runtime has no server-added hidden field nodes: read
        // the identifiers out of the expressions and keep the ones naming a
        // field of the model, so the read can request them.
        const expressionFields = new Set(archInfo.expressionFields);
        for (const { condition } of archInfo.decorations) {
            for (const identifier of condition.match(/[A-Za-z_][A-Za-z0-9_]*/g) || []) {
                if (fields[identifier]) {
                    expressionFields.add(identifier);
                }
            }
        }
        archInfo.expressionFields = [...expressionFields];

        return archInfo;
    }

    /**
     * Read a boolean arch attribute.
     *
     * The server accepts the same values: ``str2bool``'s extra spellings
     * (``no``/``off``) are refused there because the client's
     * ``exprToBoolean`` would read them as true.
     */
    _readBoolean(xmlDoc, attribute) {
        const value = xmlDoc.getAttribute(attribute);
        if (value === null) {
            return false;
        }
        const normalized = value.trim().toLowerCase();
        if (!BOOLEAN_VALUES.includes(normalized)) {
            throw new Error(
                `The "${attribute}" attribute of a gantt_soft view must be a boolean (0, 1, true or false), got "${value}".`
            );
        }
        return normalized === "1" || normalized === "true";
    }

    /**
     * Read a ``<button>`` child of the view: an action offered by the card.
     *
     * ``object`` calls a public method on the record, ``action`` opens an
     * action; the server checks the method at install time, this pass covers a
     * view built at runtime. Either a label or an icon is required, otherwise
     * the card would draw an empty button.
     */
    _parseButton(node) {
        for (const attribute of node.getAttributeNames()) {
            if (!BUTTON_ATTRIBUTES.includes(attribute)) {
                throw new Error(
                    `Invalid attribute "${attribute}" on a <button> of a gantt_soft view (expected one of ${BUTTON_ATTRIBUTES.join(
                        ", "
                    )}).`
                );
            }
        }
        const name = (node.getAttribute("name") || "").trim();
        if (!name) {
            throw new Error(
                `A <button> of a gantt_soft view must name a method or an action.`
            );
        }
        const type = node.getAttribute("type");
        if (!BUTTON_TYPES.includes(type)) {
            throw new Error(
                `The type of a <button> of a gantt_soft view must be one of ${BUTTON_TYPES.join(
                    "/"
                )}, got "${type}".`
            );
        }
        const icon = node.getAttribute("icon") || "";
        if (!node.getAttribute("string") && !icon) {
            throw new Error(
                `A <button> of a gantt_soft view needs a string or an icon: the card would draw an empty button otherwise.`
            );
        }
        return {
            name,
            type,
            string: node.getAttribute("string") || "",
            icon,
            confirm: node.getAttribute("confirm") || "",
            class: node.getAttribute("class") || "",
        };
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
