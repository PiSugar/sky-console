from __future__ import annotations

import re
import unittest
from pathlib import Path


STATIC_DIR = Path(__file__).parents[1] / "server" / "app" / "static"


class StaticAssetTests(unittest.TestCase):
    def test_leaflet_is_served_locally(self) -> None:
        index = (STATIC_DIR / "index.html").read_text(encoding="utf-8")

        self.assertNotIn("unpkg.com/leaflet", index)
        self.assertIn('/assets/vendor/leaflet/leaflet.css?v=1.9.4', index)
        self.assertIn('/assets/vendor/leaflet/leaflet.js?v=1.9.4', index)

    def test_leaflet_bundle_is_complete(self) -> None:
        vendor_dir = STATIC_DIR / "vendor" / "leaflet"
        stylesheet = (vendor_dir / "leaflet.css").read_text(encoding="utf-8")

        self.assertIn(".leaflet-pane", stylesheet)
        self.assertIn(".leaflet-tile", stylesheet)
        self.assertGreater((vendor_dir / "leaflet.js").stat().st_size, 100_000)

        image_paths = re.findall(r"url\((?:['\"])?([^)'\"]+)", stylesheet)
        local_image_paths = [path for path in image_paths if not path.startswith(("#", "data:"))]
        for image_path in local_image_paths:
            with self.subTest(image_path=image_path):
                self.assertTrue((vendor_dir / image_path).is_file())

    def test_domestic_and_international_map_sources_preserve_adsb_coordinates(self) -> None:
        index = (STATIC_DIR / "index.html").read_text(encoding="utf-8")
        script = (STATIC_DIR / "app.js").read_text(encoding="utf-8")

        self.assertIn("tile.openstreetmap.org", index)
        self.assertIn("tile.openstreetmap.org", script)
        self.assertIn("is.autonavi.com", index)
        self.assertIn("is.autonavi.com", script)
        self.assertIn("wgs84ToGcj02", script)
        self.assertIn("gcj02ToWgs84", script)
        self.assertIn("mapDisplayPosition", script)
        self.assertIn("switchMapSource", script)
        self.assertIn('id="map-source-toggle"', index)
        self.assertNotIn("coordinate-locator", index)
        self.assertIn("高德地图", script)
        self.assertIn("OpenStreetMap contributors", script)

    def test_map_uses_plain_wheel_zoom_and_dragging(self) -> None:
        index = (STATIC_DIR / "index.html").read_text(encoding="utf-8")
        script = (STATIC_DIR / "app.js").read_text(encoding="utf-8")
        stylesheet = (STATIC_DIR / "styles.css").read_text(encoding="utf-8")

        self.assertIn("scrollWheelZoom: true", script)
        self.assertIn("dragging: true", script)
        self.assertIn("touchZoom: true", script)
        self.assertNotIn("ctrlKey", script)
        self.assertNotIn("metaKey", script)
        self.assertNotIn("Ctrl + 滚轮", index)
        self.assertIn("滚轮直接缩放 · 空白处拖动平移", index)
        self.assertIn(".map-unavailable[hidden]", stylesheet)
        self.assertIn("pointer-events: none", stylesheet)

    def test_live_updates_use_websocket(self) -> None:
        script = (STATIC_DIR / "app.js").read_text(encoding="utf-8")
        stylesheet = (STATIC_DIR / "styles.css").read_text(encoding="utf-8")

        self.assertIn("new WebSocket(liveSocketUrl())", script)
        self.assertIn('/ws/v1/live', script)
        self.assertNotIn("setInterval(refreshLive", script)
        self.assertNotIn("setInterval(refreshStats", script)
        self.assertIn('className: `aircraft-marker${extraClass ? ` ${extraClass}` : ""}`', script)
        self.assertIn(".aircraft-marker", stylesheet)
        self.assertIn("predictAircraftPosition", script)
        self.assertIn("destinationPoint", script)
        self.assertIn("requestAnimationFrame(animateFlights)", script)
        self.assertIn("state.map.getZoom()", script)
        self.assertIn("updateIntervalMs", script)
        self.assertIn("serverClockOffsetMs", script)
        self.assertIn("aircraft.position_at_ms || aircraft.last_seen_ms", script)
        self.assertIn("aircraft.last_seen_ms", script)
        self.assertIn("aircraft.ground_speed", script)
        self.assertIn("unwrapHeading", script)
        self.assertIn('classList.add("map-is-zooming")', script)
        self.assertIn('classList.remove("map-is-zooming")', script)
        self.assertIn('classList.contains("map-is-zooming")', script)
        self.assertNotIn("--flight-duration", stylesheet)

    def test_hardware_controls_use_live_websocket(self) -> None:
        script = (STATIC_DIR / "app.js").read_text(encoding="utf-8")
        stylesheet = (STATIC_DIR / "styles.css").read_text(encoding="utf-8")

        self.assertIn('message.type === "hardware_control"', script)
        self.assertIn("if (document.hidden || !state.map", script)
        self.assertIn("function handleHardwareControl(message)", script)
        self.assertIn("state.map.panBy", script)
        self.assertIn("state.map.setZoom", script)
        self.assertIn("function selectNearestVisibleAircraft()", script)
        self.assertIn("bounds.contains(markerPosition)", script)
        self.assertIn("showAircraftQuickCard(nearest)", script)
        self.assertIn("playAircraftRadio(nearest)", script)
        self.assertIn("state.map.flyTo(nearestPosition", script)
        self.assertIn("state.map.setZoom(state.map.getZoom() + delta, { animate: true })", script)
        self.assertNotIn(".leaflet-tile-container,\n.leaflet-map-pane", stylesheet)

    def test_aircraft_detail_exposes_coordinate_verification(self) -> None:
        script = (STATIC_DIR / "app.js").read_text(encoding="utf-8")

        self.assertIn("coordinateVerificationMarkup", script)
        self.assertIn("ADS-B 原始坐标", script)
        self.assertIn("高德地图绘制坐标", script)
        self.assertIn("模拟位置覆盖", script)

    def test_flight_numbers_and_airline_names_are_localized(self) -> None:
        index = (STATIC_DIR / "index.html").read_text(encoding="utf-8")
        script = (STATIC_DIR / "app.js").read_text(encoding="utf-8")
        stylesheet = (STATIC_DIR / "styles.css").read_text(encoding="utf-8")

        self.assertIn("function flightNumbers(aircraft)", script)
        self.assertIn("route_callsign_iata", script)
        self.assertIn("route_callsign_icao", script)
        self.assertIn("旅客航班号", script)
        self.assertIn("ICAO / ADS-B", script)
        self.assertIn("navigator.languages", script)
        self.assertIn("function localizedAirlineName(aircraft)", script)
        self.assertIn('CSN: "中国南方航空"', script)
        self.assertIn("function localizedAirportDetail(aircraft, prefix)", script)
        self.assertIn('CAN: ["广州", "广州白云国际机场"]', script)
        self.assertIn('SHA: ["上海", "上海虹桥国际机场"]', script)
        self.assertIn("airportShortLabel", script)
        self.assertIn('id="map-quick-card"', index)
        self.assertIn("function showAircraftQuickCard(icao)", script)
        self.assertIn("localizedAirlineName(aircraft)", script)
        self.assertIn("aircraftModelLabel(aircraft)", script)
        self.assertIn(".map-quick-card:not([hidden])", stylesheet)
        self.assertIn(".quick-card-route", stylesheet)
        self.assertIn("(pointer: coarse)", stylesheet)

    def test_enrichment_uses_dedicated_endpoint(self) -> None:
        script = (STATIC_DIR / "app.js").read_text(encoding="utf-8")

        self.assertIn("function enrichmentUrl(icao, callsign = null)", script)
        self.assertIn('/enrichment${query ? `?${query}` : ""}', script)
        self.assertIn("refreshQuickCardEnrichment", script)
        self.assertIn("function scheduleQuickEnrichmentRefresh(icao, attempt = 0)", script)
        self.assertIn("quickEnrichmentRefreshTimer", script)
        self.assertIn("const data = await api(enrichmentUrl(icao, state.detailAircraft?.callsign));", script)

    def test_aircraft_click_queues_radio_playback(self) -> None:
        script = (STATIC_DIR / "app.js").read_text(encoding="utf-8")
        stylesheet = (STATIC_DIR / "styles.css").read_text(encoding="utf-8")

        self.assertIn("radioClickCooldowns", script)
        self.assertIn("async function playAircraftRadio(icao)", script)
        self.assertIn('/api/v1/aircraft/${icao}/radio', script)
        self.assertIn("playAircraftRadio(key);", script)
        self.assertIn("playAircraftRadio(button.dataset.icao);", script)
        self.assertIn("function finiteCoordinatePair(latitude, longitude)", script)

        selected_rule = re.search(
            r"\.aircraft-marker\.is-quick-selected \.plane-marker \{(?P<body>.*?)\}",
            stylesheet,
            flags=re.S,
        )
        self.assertIsNotNone(selected_rule)
        self.assertNotIn("scale(", selected_rule.group("body"))
        self.assertNotIn("background: var(--green)", selected_rule.group("body"))


if __name__ == "__main__":
    unittest.main()
