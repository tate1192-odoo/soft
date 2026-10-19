/** @odoo-module **/

import { Model } from "@web/model/model";
import { orderByToString } from "@web/search/utils/order_by";

export class MapModel extends Model {
    static services = [];

    setup(params) {
        this.metaData = { ...params };
        this.data = { records: [], count: 0 };
        this._loadId = 0;
    }

    /**
     * Load the records to display on the map. The search params (domain,
     * context, orderBy, offset, limit) are injected by `useModelWithSampleData`
     * and kept in `metaData` so the view can restore its state.
     *
     * @param {Object} params search params
     */
    async load(params = {}) {
        const loadId = ++this._loadId;
        const metaData = { ...this.metaData, ...params };
        const orderBy =
            params.orderBy && params.orderBy.length
                ? params.orderBy
                : metaData.defaultOrder || [];

        const searchDomain = metaData.domain || [];
        const searchContext = metaData.context || {};
        const [records, count] = await Promise.all([
            this.orm.searchRead(
                metaData.resModel,
                searchDomain,
                metaData.fieldNames || [],
                {
                    limit: metaData.limit || 80,
                    offset: metaData.offset || 0,
                    order: orderByToString(orderBy) || undefined,
                    context: searchContext,
                }
            ),
            this.orm.searchCount(metaData.resModel, searchDomain, {
                context: searchContext,
            }),
        ]);

        if (loadId !== this._loadId) {
            // A newer load (search, pager, filter) started while this one
            // was in flight; discard the stale result.
            return;
        }
        this.metaData = metaData;
        this.data = { records, count };
        this.notify();
    }

    hasData() {
        return this.data.records.length > 0;
    }
}
