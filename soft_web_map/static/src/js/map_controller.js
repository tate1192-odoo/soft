/** @odoo-module **/

import { Component, onWillStart } from "@odoo/owl";

import { loadBundle } from "@web/core/assets";
import { useService } from "@web/core/utils/hooks";
import { useModelWithSampleData } from "@web/model/model";
import { useSetupAction } from "@web/search/action_hook";
import { Layout } from "@web/search/layout";
import { usePager } from "@web/search/pager_hook";
import { SearchBar } from "@web/search/search_bar/search_bar";
import { useSearchBarToggler } from "@web/search/search_bar/search_bar_toggler";
import { CogMenu } from "@web/search/cog_menu/cog_menu";
import { standardViewProps } from "@web/views/standard_view_props";

export class MapController extends Component {
    static template = "soft_web_map.MapView";
    static components = { Layout, SearchBar, CogMenu };
    static props = {
        ...standardViewProps,
        Model: Function,
        modelParams: Object,
        Renderer: Function,
        buttonTemplate: String,
    };

    setup() {
        this.action = useService("action");
        this.model = useModelWithSampleData(this.props.Model, this.props.modelParams);

        useSetupAction({
            getLocalState: () => this.model.metaData,
        });

        usePager(() => this.pagerProps);

        onWillStart(() => loadBundle("soft_web_map.assets_leaflet"));

        this.searchBarToggler = useSearchBarToggler();
    }

    get pagerProps() {
        return {
            offset: this.model.metaData.offset,
            limit: this.model.metaData.limit,
            total: this.model.data.count,
            onUpdate: ({ offset, limit }) => this.model.load({ offset, limit }),
        };
    }

    get rendererProps() {
        return {
            model: this.model,
            onMarkerClick: (recordId, newWindow) => this.openRecord(recordId, newWindow),
        };
    }

    /**
     * Open a record in the form view.
     *
     * @param {Number} recordId record id
     * @param {Boolean} [newWindow] open in a new browser window
     */
    openRecord(recordId, newWindow) {
        if (recordId === undefined || recordId === null) {
            return;
        }
        this.action.switchView("form", { resId: recordId }, { newWindow });
    }
}
