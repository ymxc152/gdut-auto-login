from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from gdut_autologin.network import (
    AdapterInfo,
    adapter_matches_keyword,
    login_account,
    normalize_mac,
    parse_login_success,
    select_adapter,
)
from gdut_autologin.storage import EventDatabase, mask_account, ordered_accounts


class NetworkCoreTests(unittest.TestCase):
    def test_mac_normalization(self):
        self.assertEqual(normalize_mac("00-11-22-33-44-55"), "001122334455")

    def test_select_adapter_prefers_configured_mac(self):
        adapters = [
            AdapterInfo("Wi-Fi", "AA-BB-CC-DD-EE-01", "已连接", ["192.168.1.2"], True),
            AdapterInfo(
                "Wired",
                "AA-BB-CC-DD-EE-02",
                "已连接",
                ["10.1.2.3"],
                True,
                profile_names=["GdUt"],
            ),
        ]
        with patch("gdut_autologin.network.list_adapters", return_value=adapters):
            selected = select_adapter(
                {"adapter_mac": "AA:BB:CC:DD:EE:02", "network_keyword": "gdut"}
            )
        self.assertEqual(selected.name, "Wired")

    def test_profile_keyword_is_case_insensitive_for_wifi(self):
        adapter = AdapterInfo(
            "WLAN",
            "AA-BB-CC-DD-EE-03",
            "已连接",
            ["10.2.3.4"],
            True,
            profile_names=["GDUT"],
        )
        self.assertTrue(adapter_matches_keyword(adapter, "gDuT"))

    def test_configured_adapter_is_rejected_without_gdut_profile(self):
        adapters = [
            AdapterInfo("Ethernet", "AA-BB-CC-DD-EE-04", "已连接", ["10.9.8.7"], True)
        ]
        with patch("gdut_autologin.network.list_adapters", return_value=adapters):
            selected = select_adapter(
                {"adapter_mac": "AA-BB-CC-DD-EE-04", "network_keyword": "gdut"}
            )
        self.assertIsNone(selected)

    def test_login_request_uses_selected_adapter_source_ip(self):
        config = {
            "portal_host": "10.0.3.2",
            "portal_port": 801,
            "wlan_ac_ip": "172.16.254.2",
        }
        account = {"account": "authorized", "password": "secret"}
        response = b'dr1003({"result":1,"msg":"ok"})'
        with patch(
            "gdut_autologin.network.http_get_bound",
            return_value=(200, {}, response),
        ) as request:
            success, _message = login_account("10.12.34.56", config, account)
        self.assertTrue(success)
        self.assertEqual(request.call_args.args[0], "10.12.34.56")

    def test_parse_jsonp_success(self):
        success, _message = parse_login_success('dr1003({"result":1,"msg":"ok"})')
        self.assertTrue(success)


class AccountOrderTests(unittest.TestCase):
    def test_order_wraps_from_last_success(self):
        accounts = [
            {"account": "A", "password": "1"},
            {"account": "B", "password": "2"},
            {"account": "C", "password": "3"},
        ]
        with patch("gdut_autologin.storage.load_state", return_value={"last_success_account": "B"}):
            result = ordered_accounts(accounts)
        self.assertEqual([item["account"] for item in result], ["B", "C", "A"])

    def test_mask_account(self):
        self.assertEqual(mask_account("1234567890"), "12******90")


class EventDatabaseTests(unittest.TestCase):
    def test_add_query_export_and_clear(self):
        with tempfile.TemporaryDirectory() as temporary:
            database = EventDatabase(Path(temporary) / "events.db")
            database.add("INFO", "network online")
            database.add("WARNING", "login required")
            rows = database.query(level="WARNING")
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0][3], "login required")

            destination = Path(temporary) / "events.csv"
            count = database.export_csv(destination)
            self.assertEqual(count, 2)
            self.assertTrue(destination.exists())

            database.clear()
            self.assertEqual(database.query(), [])


if __name__ == "__main__":
    unittest.main()
