import { Domain } from "@web/core/domain";
import { KeepLast } from "@web/core/utils/concurrency";
import { Model } from "@web/model/model";
import { getFieldsSpec } from "@web/model/relational_model/utils";
import { orderByToString } from "@web/search/utils/order_by";

import { serializeOdooDate } from "./gantt_utils";

/**
 * Data source of the Gantt view.
 *
 * A Gantt shows every record at once: there is no paging and no grouping, so
 * the full `RelationalModel` machinery would be wasted here. This model does
 * one thing: turn the current search parameters (domain, context, order) into
 * a single `web_search_read` and keep the resulting records.
 *
 * Because the search parameters are read on every `load`, the filters, the
 * favourites and the search bar actually reload the view.
 */
export class GanttSoftModel extends Model {
    setup(params) {
        this.keepLast = new KeepLast();
        this.resModel = params.resModel;
        this.fields = params.fields;
        this.activeFields = params.activeFields;
        this.archInfo = params.archInfo;
        this.defaultOrderBy = this.archInfo.defaultOrder || [];
        this.records = [];
        this.config = {
            domain: params.domain || [],
            context: params.context || {},
            orderBy: [],
            // The window the view is on, when the caller knows one: it is what
            // keeps a table of thousands of records from being read at once.
            window: params.window || null,
        };
    }

    get context() {
        return { ...this.config.context };
    }

    /**
     * Order applied to the rows: the one the user chose in the search bar when
     * there is one, the view's `default_order` otherwise.
     */
    get orderBy() {
        return this.config.orderBy.length ? this.config.orderBy : this.defaultOrderBy;
    }

    async load(params = {}) {
        const config = { ...this.config };
        if ("domain" in params) {
            config.domain = params.domain || [];
        }
        if ("context" in params) {
            config.context = params.context || {};
        }
        if ("orderBy" in params) {
            config.orderBy = params.orderBy || [];
        }
        this.config = config;
        this.records = await this.keepLast.add(this._fetch(config));
        this.notify();
    }

    /** Re-read the records with the parameters already in use. */
    async reload() {
        this.records = await this.keepLast.add(this._fetch(this.config));
        this.notify();
    }

    /**
     * Move the view to another window and re-read it.
     *
     * @param {{start: number, end: number}} window timestamps in milliseconds
     */
    async setWindow(window) {
        this.config.window = window;
        this.records = await this.keepLast.add(this._fetch(this.config));
        this.notify();
    }

    /**
     * Domain keeping the records that overlap the window.
     *
     * Three shapes are kept, because a record may carry both dates, only its
     * start or only its stop:
     *
     * - both dates: the intervals overlap, `dateStart < end` and
     *   `dateStop >= start`;
     * - only a start: `dateStart` falls inside the window;
     * - only a stop: `dateStop` falls inside the window.
     *
     * The domain is built with the `Domain` combinators, never as a hand
     * written prefix list: the OR of the three shapes is easy to get wrong by
     * hand and the server refuses a malformed list with a `ValueError` before
     * any record is read.
     */
    _windowDomain(window) {
        if (!window) {
            return [];
        }
        const { dateStart, dateStop, dateStartType, dateStopType } = this.archInfo;
        // Each comparison is serialised for the type of the field it filters:
        // a `date` boundary is a calendar day, a `datetime` boundary an instant.
        const startAtStart = serializeOdooDate(window.start, dateStartType);
        const endAtStart = serializeOdooDate(window.end, dateStartType);
        const startAtStop = serializeOdooDate(window.start, dateStopType);
        const endAtStop = serializeOdooDate(window.end, dateStopType);
        return Domain.or([
            [
                [dateStart, "<", endAtStart],
                [dateStop, ">=", startAtStop],
            ],
            [
                [dateStart, "=", false],
                [dateStop, ">=", startAtStop],
                [dateStop, "<", endAtStop],
            ],
            [
                [dateStop, "=", false],
                [dateStart, ">=", startAtStart],
                [dateStart, "<", endAtStart],
            ],
        ]).toList();
    }

    async _fetch(config) {
        const domain = Domain.and([
            config.domain,
            this._windowDomain(config.window),
        ]).toList();
        const { records } = await this.orm.webSearchRead(this.resModel, domain, {
            specification: getFieldsSpec(this.activeFields, this.fields, config.context || {}),
            context: config.context,
            order: orderByToString(this.orderBy),
            limit: this.archInfo.limit,
        });
        return records;
    }
}
