"""Tests for multi-network definitions + generic route generation (no SUMO)."""
from __future__ import annotations

from xml.dom.minidom import parseString

from sim.live import LiveConfig, _routes_xml
from sim.network_defs import NETWORKS, descriptor, edg_xml, nod_xml


def test_network_defs_xml_wellformed():
    for name in NETWORKS:
        parseString(nod_xml(name))
        parseString(edg_xml(name))


def test_tee_has_no_south():
    nod, edg = nod_xml("tee"), edg_xml("tee")
    assert '"S"' not in nod
    assert "S_in" not in edg and "S_out" not in edg
    assert "N_in" in edg and "E_in" in edg and "W_in" in edg


def test_asym_lane_counts():
    edg = edg_xml("asym")
    assert 'id="E_in"  from="E" to="C" numLanes="3"' in edg
    assert 'id="N_in"  from="N" to="C" numLanes="1"' in edg


def test_descriptor_shape():
    d = descriptor("cross")
    assert d["name"] == "cross" and d["arms"]["N"] == 2 and "label" in d


def test_routes_tee_excludes_south_flows():
    routes = _routes_xml(LiveConfig(network="tee", ped_per_hour=100))
    parseString(routes)
    assert "S_in" not in routes and "S_out" not in routes
    assert 'from="W_in" to="E_out"' in routes


def test_routes_mixed_traffic_has_vtypes():
    routes = _routes_xml(LiveConfig(network="cross", mix="mixed"))
    assert '<vType id="moto"' in routes and '<vType id="bus"' in routes
    assert "_moto" in routes and "_bus" in routes


def test_routes_cars_only_single_vtype():
    routes = _routes_xml(LiveConfig(network="cross", mix="cars"))
    assert "moto" not in routes and "bus" not in routes
