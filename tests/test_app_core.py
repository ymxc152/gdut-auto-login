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
from gdut_autologin.storage import EventDatabase, edit_account, mask_account, ordered_accounts
from gdut_autologin.updates import UpdateInfo, _expected_hash, _replace_with_retry, version_tuple


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

    @patch("gdut_autologin.storage.save_state")
    @patch("gdut_autologin.storage.load_state", return_value={"last_success_account": "old"})
    @patch("gdut_autologin.storage.save_accounts")
    @patch(
        "gdut_autologin.storage.load_accounts",
        return_value=[{"account": "old", "password": "secret"}],
    )
    def test_edit_account_keeps_password_when_blank(
        self, _load_accounts, save_accounts, _load_state, save_state
    ):
        self.assertTrue(edit_account("old", "new", ""))
        save_accounts.assert_called_once_with([{"account": "new", "password": "secret"}])
        save_state.assert_called_once_with({"last_success_account": "new"})


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


class UpdateCoreTests(unittest.TestCase):
    def test_semantic_version_comparison(self):
        self.assertGreater(version_tuple("v1.10.0"), version_tuple("1.9.9"))
        self.assertEqual(version_tuple("release-1.1.0"), (1, 1, 0))

    def test_checksum_parser_requires_matching_asset(self):
        digest = "a" * 64
        text = f"{digest}  GDUTAutoLogin-1.1.1-win64.exe\n"
        self.assertEqual(_expected_hash(text, "GDUTAutoLogin-1.1.1-win64.exe"), digest)
        with self.assertRaises(RuntimeError):
            _expected_hash(text, "different.exe")

    def test_update_info_defaults_to_current_version(self):
        info = UpdateInfo()
        self.assertFalse(info.available)
        self.assertEqual(info.current_version, "1.1.1")

    def test_replace_with_retry_replaces_existing_file(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source, target = root / "new.exe", root / "current.exe"
            source.write_bytes(b"new")
            target.write_bytes(b"old")
            _replace_with_retry(source, target)
            self.assertEqual(target.read_bytes(), b"new")


if __name__ == "__main__":
    unittest.main()
