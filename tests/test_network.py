import pytest

from tello_controller.network import choose_tello_network, parse_current_ssid, parse_networks, wait_for_network

INTERFACES = """
There is 1 interface on the system:

    Name                   : WiFi
    Description            : Some adapter
    State                  : connected
    SSID                   : Home Network 5G
    BSSID                  : aa:bb:cc:dd:ee:ff
    Network type           : Infrastructure
"""

NETWORKS = """
Interface name : WiFi
There are 3 networks currently visible.

SSID 1 : Home Network 5G
    Network type            : Infrastructure
SSID 2 : TELLO-5A1B2C
    Network type            : Infrastructure
SSID 3 :
    Network type            : Infrastructure
"""


def test_parse_current_ssid_ignores_bssid():
    assert parse_current_ssid(INTERFACES) == "Home Network 5G"
    assert parse_current_ssid("State : disconnected") is None


def test_parse_networks_skips_hidden():
    assert parse_networks(NETWORKS) == ["Home Network 5G", "TELLO-5A1B2C"]


def test_single_tello_is_auto_selected():
    assert choose_tello_network(parse_networks(NETWORKS), interactive=False) == "TELLO-5A1B2C"
    assert choose_tello_network(["Home"], interactive=False) is None


class FakeRadio:
    """Tello appears after `appears_after` scans."""

    def __init__(self, appears_after, ssid="TELLO-ABC123"):
        self.scans = 0
        self.appears_after = appears_after
        self.ssid = ssid
        self.t = 0.0

    def scan(self):
        self.scans += 1

    def networks(self):
        return ["Home"] + ([self.ssid] if self.scans >= self.appears_after else [])

    def sleep(self, s):
        self.t += s

    def kwargs(self):
        return dict(scan=self.scan, list_networks=self.networks, sleep=self.sleep, clock=lambda: self.t)


def test_wait_returns_immediately_if_already_visible():
    radio = FakeRadio(appears_after=0)
    assert wait_for_network(**radio.kwargs()) == ["TELLO-ABC123"]
    assert radio.scans == 0


def test_wait_polls_until_tello_appears(capsys):
    radio = FakeRadio(appears_after=4)
    assert wait_for_network(poll_s=3, **radio.kwargs()) == ["TELLO-ABC123"]
    assert radio.scans == 4
    assert "Waiting for a TELLO-xxxx network" in capsys.readouterr().out


def test_wait_for_specific_ssid_ignores_other_tellos():
    radio = FakeRadio(appears_after=2, ssid="TELLO-OTHER")
    with pytest.raises(TimeoutError):
        wait_for_network("TELLO-MINE", poll_s=3, timeout_s=10, **radio.kwargs())


def test_wait_times_out():
    radio = FakeRadio(appears_after=999)
    with pytest.raises(TimeoutError):
        wait_for_network(poll_s=3, timeout_s=10, **radio.kwargs())
    assert radio.scans == 4  # 3s polls: 3, 6, 9, 12 -> gives up
