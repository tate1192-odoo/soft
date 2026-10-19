# Soft Web Map (Leaflet / OpenStreetMap)

Leaflet Map View for Odoo 19
===================================
This module integrates the Leaflet.js library with Odoo 19, allowing you to add a custom
map view (`leaflet_map`). The view is perfect for displaying geolocated data with markers on
OpenStreetMap.
Key Features:
-------------
- Interactive map view using Leaflet.js
- OpenStreetMap integration
- Marker clustering support
- Customizable map settings
- Responsive design
- Geolocation support (coordinates can be entered manually; install `base_geolocalize` for the
  Geolocate button)
- Contact address visualization

## Installation

The core module is standalone and provides the `leaflet_map` view type for any model.
Install the optional **Soft Web Map — Contacts** (`soft_web_map_contacts`) bridge module to
add the view to the Contacts application; the bridge also installs Contacts and
`base_geolocalize`.

## Enterprise

Odoo Enterprise already ships a map view and Leaflet through its `web_map`
module. `soft_web_map` declares `excludes: ["web_map"]`, so it is intended for
Odoo Community; on Enterprise use `web_map` instead.

## Configuration

- `soft_web_map.tile_url` (System Parameter): tile server URL. Defaults to
  `https://tile.openstreetmap.org/{z}/{x}/{y}.png`.
- `soft_web_map.copyright` (System Parameter): attribution HTML shown in the map's
  attribution control. Defaults to the OpenStreetMap copyright notice.

The default public OpenStreetMap tile server is intended for light usage.
Production deployments should use a tile provider that matches their traffic
and review the provider's usage policy.

Scroll-wheel zoom is disabled so the map does not capture page scrolling; use
the Leaflet +/- controls or the keyboard.

## View architecture

```xml
<leaflet_map latitude="partner_latitude"
             longitude="partner_longitude"
             limit="80"
             zoom="6"
             clustering="1"
             clustering_radius="80"
             hide_title="0"
             hide_name="0"
             hide_address="0"
             map_height="500px">
    <field name="display_name"/>
    <field name="email"/>
</leaflet_map>
```

| Attribute | Description |
|---|---|
| `latitude`, `longitude` | Coordinate fields. Defaults: `partner_latitude` / `partner_longitude`. |
| `limit` | Maximum records on the map (1-1000, default 80). |
| `zoom` | Initial zoom, used when there are no markers to fit. |
| `map_height` | Explicit CSS height (minimum 400px). Omit to fill the view. |
| `hide_title` | Hide the sidebar title. |
| `hide_name` | Hide the record name in the sidebar and popup. |
| `hide_address` | Hide the address in the popup. |
| `clustering` | Enable marker clustering (also enabled automatically above 100 records). |
| `clustering_radius` | Cluster radius in pixels (default 50). |
| `show_controls` | Show or hide the Leaflet zoom control. |
| `default_order` | Default `search_read` order, for example `name asc`. |
| `tile_url` | Override the tile URL for this view. |
| `panel_title` / `string` | Sidebar title; defaults to the action name. |

`<field name="..."/>` adds a field to the `search_read` field list. The popup
shows the name, address, email and phone when those fields are available. If the
record has a `display_address` field (for example `field.operation`), that value
is used as the popup address instead of the individual street/city components.
`<options>` supports `<tile_layer url="..."/>` and
`<clustering enabled="1" radius="80"/>`.

## Credits

This module is maintained by Softteknik Bilişim.

Bundled libraries:
- [Leaflet](https://leafletjs.com) 1.9.4, BSD 2-Clause.
- [Leaflet.markercluster](https://github.com/Leaflet/Leaflet.markercluster), MIT.

Bundled libraries keep their own license files under `static/lib/leaflet/`.

## License

LGPL-3 (module metadata).
