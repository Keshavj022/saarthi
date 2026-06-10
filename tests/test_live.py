"""Tests for the live-sim demand-route generation (pure, no SUMO)."""
from __future__ import annotations

from xml.dom.minidom import parseString

from sim.live import LiveConfig, _routes_xml


def test_routes_xml_is_wellformed_and_has_flows():
    routes = _routes_xml(LiveConfig(ew_vph=600, ns_vph=200, ped_per_hour=160, duration=300))
    parseString(routes)  # raises if malformed
    assert 'from="W_in" to="E_out"' in routes
    assert 'vehsPerHour="600"' in routes
    assert "personFlow" in routes


def test_routes_xml_zero_pedestrians_omits_personflow():
    routes = _routes_xml(LiveConfig(ped_per_hour=0))
    assert "personFlow" not in routes


def test_live_config_defaults():
    cfg = LiveConfig()
    assert cfg.controller in ("max_pressure", "fixed_time")
    assert cfg.duration > 0
