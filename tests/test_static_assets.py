from __future__ import annotations

import re
import unittest
from pathlib import Path


PROJECT_DIR = Path(__file__).parents[1]
STATIC_DIR = PROJECT_DIR / "server" / "app" / "static"


class StaticAssetTests(unittest.TestCase):
    def test_kiosk_close_uses_a_host_visible_request_marker(self) -> None:
        main_source = (PROJECT_DIR / "server" / "app" / "main.py").read_text(encoding="utf-8")
        compose = (PROJECT_DIR / "docker-compose.yml").read_text(encoding="utf-8")
        launcher = (PROJECT_DIR / "runtime" / "start-kiosk.sh").read_text(encoding="utf-8")
        script = (STATIC_DIR / "app.js").read_text(encoding="utf-8")

        self.assertIn("request_path.touch()", main_source)
        self.assertIn("./runtime/state:/run/skytrace", compose)
        self.assertIn('if [ -e "$SKYTRACE_CLOSE_MARKER" ]', launcher)
        self.assertIn('kill "$kiosk_pid"', launcher)
        self.assertIn("if (!response.ok) throw new Error", script)

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

        self.assertIn("/tiles/international/{z}/{x}/{y}.png", script)
        self.assertIn("/tiles/esri/{z}/{x}/{y}.png", script)
        self.assertIn("wgs84ToGcj02", script)
        self.assertIn("gcj02ToWgs84", script)
        self.assertIn("mapDisplayPosition", script)
        self.assertIn("switchMapSource", script)
        self.assertIn('id="map-source-toggle"', index)
        self.assertNotIn("coordinate-locator", index)
        self.assertIn("Map: Esri", script)
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
        self.assertIn("Scroll to zoom · Drag to pan", index)
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
        self.assertIn("focusAircraft(nearestPosition)", script)
        self.assertIn("state.map.setZoom(state.map.getZoom() + delta, { animate: true })", script)
        self.assertIn('message.action === "toggle_follow"', script)
        self.assertIn("function toggleAircraftFollow()", script)
        self.assertIn("function releaseAircraftFollow(notify = false)", script)
        self.assertIn('state.map.on("dragstart", () => releaseAircraftFollow(true))', script)
        self.assertNotIn('mapElement.addEventListener("pointerdown", () => {\n    releaseAircraftFollow(true);', script)
        self.assertIn("state.map.panTo(aircraftFocusCenter(followedMarker.getLatLng())", script)
        self.assertIn('id="map-follow-status"', (STATIC_DIR / "index.html").read_text(encoding="utf-8"))
        self.assertIn(".map-follow-status", stylesheet)
        self.assertIn("function aircraftFocusCenter(latLng", script)
        self.assertNotIn(".leaflet-tile-container,\n.leaflet-map-pane", stylesheet)

    def test_dialogue_status_and_real_aircraft_photo_are_rendered(self) -> None:
        script = (STATIC_DIR / "app.js").read_text(encoding="utf-8")
        index = (STATIC_DIR / "index.html").read_text(encoding="utf-8")
        stylesheet = (STATIC_DIR / "styles.css").read_text(encoding="utf-8")

        self.assertIn('id="dialogue-status"', index)
        self.assertIn('message.action === "dialogue_listening"', script)
        self.assertIn('message.action === "dialogue_transcribing"', script)
        self.assertIn('message.action === "dialogue_answer"', script)
        self.assertIn('message.action === "dialogue_unavailable"', script)
        self.assertIn('message.action === "dialogue_interrupted"', script)
        self.assertIn("aircraft.aircraft_photo_url", script)
        self.assertIn(".quick-card-photo", stylesheet)
        self.assertIn(".aircraft-photo", stylesheet)
        self.assertIn("background: rgba(0, 0, 0, 0.88)", stylesheet)
        self.assertIn("positionDialogueStatus();", script)
        self.assertIn("function showPilotAnswer(question, answer)", script)
        self.assertIn("window.setInterval(revealWord, 260)", script)
        self.assertIn("overflow-wrap: anywhere", stylesheet)
        self.assertIn("white-space: normal", stylesheet)

    def test_aircraft_photos_open_a_gesture_viewer(self) -> None:
        script = (STATIC_DIR / "app.js").read_text(encoding="utf-8")
        index = (STATIC_DIR / "index.html").read_text(encoding="utf-8")
        stylesheet = (STATIC_DIR / "styles.css").read_text(encoding="utf-8")
        main_source = (PROJECT_DIR / "server" / "app" / "main.py").read_text(encoding="utf-8")

        self.assertIn('id="photo-viewer"', index)
        self.assertIn('data-photo-full="${escapeHtml(photoUrl)}"', script)
        self.assertIn("function openPhotoViewer(url", script)
        self.assertIn('addEventListener("pointermove"', script)
        self.assertIn('addEventListener("wheel"', script)
        self.assertIn("point.y - point.startY > 90", script)
        self.assertIn('message.action === "photo_viewer_close"', script)
        self.assertIn(".photo-viewer-stage", stylesheet)
        self.assertIn("touch-action: none", stylesheet)
        self.assertIn('/api/v1/hardware/photo-viewer', main_source)

    def test_aircraft_detail_exposes_coordinate_verification(self) -> None:
        script = (STATIC_DIR / "app.js").read_text(encoding="utf-8")

        self.assertIn("coordinateVerificationMarkup", script)
        self.assertIn("Original ADS-B coordinates", script)
        self.assertIn("GCJ-02 comparison coordinates", script)
        self.assertIn("never overwrite the original coordinates", script)

    def test_flight_numbers_and_airline_names_are_localized(self) -> None:
        index = (STATIC_DIR / "index.html").read_text(encoding="utf-8")
        script = (STATIC_DIR / "app.js").read_text(encoding="utf-8")
        stylesheet = (STATIC_DIR / "styles.css").read_text(encoding="utf-8")

        self.assertIn("function flightNumbers(aircraft)", script)
        self.assertIn("route_callsign_iata", script)
        self.assertIn("route_callsign_icao", script)
        self.assertIn("Passenger flight number", script)
        self.assertIn("ICAO / ADS-B", script)
        self.assertIn("function localizedAirlineName(aircraft)", script)
        self.assertIn("return aircraft.airline_name || null", script)
        self.assertIn("function localizedAirportDetail(aircraft, prefix)", script)
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

    def test_selected_aircraft_is_shared_with_hardware_dialogue(self) -> None:
        script = (STATIC_DIR / "app.js").read_text(encoding="utf-8")

        self.assertIn('fetch("/api/v1/hardware/selection"', script)
        self.assertIn("setHardwareAircraft(icao);", script)
        self.assertIn("if (selectedIcao) setHardwareAircraft(selectedIcao);", script)


if __name__ == "__main__":
    unittest.main()
