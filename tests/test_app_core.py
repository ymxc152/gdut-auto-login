from pathlib import Path
import json
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from gdut_autologin import windows
from gdut_autologin import service
from gdut_autologin import gui
from gdut_autologin.network import (
    AdapterInfo,
    adapter_source_ip,
    connected_physical_adapters,
    login_account,
    normalize_mac,
    parse_login_success,
    parse_wlan_interfaces,
    select_adapter,
)
from gdut_autologin import storage
from gdut_autologin.storage import (
    EventDatabase,
    edit_account,
    export_accounts_file,
    import_accounts_file,
    mask_account,
    ordered_accounts,
)
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
            selected = select_adapter({"adapter_mac": "AA:BB:CC:DD:EE:02"})
        self.assertEqual(selected.name, "Wired")

    def test_connected_adapter_list_includes_all_connected_physical_interfaces(self):
        adapters = [
            AdapterInfo("WLAN", "01", "已连接", ["10.1.1.1"], True, profile_names=["GDUT"]),
            AdapterInfo("Ethernet", "02", "已断开", [], True, profile_names=["gdut"]),
            AdapterInfo("Disabled", "03", "已断开", [], True, profile_names=["gdut-disabled"]),
            AdapterInfo("vEthernet", "04", "已连接", ["10.2.2.2"], False, profile_names=["gdut"]),
            AdapterInfo("Other", "05", "已连接", ["192.168.1.2"], True, profile_names=["Home"]),
        ]
        result = connected_physical_adapters(adapters)
        self.assertEqual([item.name for item in result], ["WLAN", "Other"])

    def test_select_adapter_strict_mode_keeps_disconnected_saved_adapter(self):
        adapters = [
            AdapterInfo("Old", "AA-01", "已断开", [], True),
            AdapterInfo("Ethernet", "AA-02", "已连接", ["10.8.8.8"], True),
        ]
        with patch("gdut_autologin.network.list_adapters", return_value=adapters):
            selected = select_adapter({"adapter_mac": "AA-01", "adapter_name": "Old"})
        self.assertEqual(selected.name, "Old")
        self.assertEqual(selected.status, "已断开")

    def test_select_adapter_strict_mode_waits_when_saved_adapter_is_missing(self):
        adapters = [
            AdapterInfo("Ethernet", "AA-02", "已连接", ["10.8.8.8"], True),
        ]
        with patch("gdut_autologin.network.list_adapters", return_value=adapters):
            selected = select_adapter({"adapter_mac": "AA-99", "adapter_name": "Gone"})
        self.assertIsNone(selected)

    def test_parse_current_wifi_ssid_from_netsh_output(self):
        output = """
            Name                   : WLAN
            Physical address       : ac:19:8e:a1:19:4f
            State                  : connected
            SSID                   : gdut-X3-455
            AP BSSID               : 3a:20:28:e4:63:ed
        """
        self.assertEqual(
            parse_wlan_interfaces(output),
            {"AC198EA1194F": ["gdut-X3-455"]},
        )

    def test_configured_adapter_does_not_require_gdut_profile(self):
        adapters = [
            AdapterInfo("Ethernet", "AA-BB-CC-DD-EE-04", "已连接", ["10.9.8.7"], True)
        ]
        with patch("gdut_autologin.network.list_adapters", return_value=adapters):
            selected = select_adapter({"adapter_mac": "AA-BB-CC-DD-EE-04"})
        self.assertEqual(selected.name, "Ethernet")

    def test_configured_connected_adapter_is_honored_without_10_address(self):
        adapters = [
            AdapterInfo("Wi-Fi", "AA-01", "已连接", ["10.8.8.8"], True),
            AdapterInfo("Ethernet", "AA-02", "已连接", ["192.168.1.9"], True),
        ]
        with patch("gdut_autologin.network.list_adapters", return_value=adapters):
            selected = select_adapter({"adapter_mac": "AA-02"})
        self.assertEqual(selected.name, "Ethernet")

    def test_adapter_source_ip_prefers_configured_10_prefix(self):
        adapter = AdapterInfo("Wi-Fi", "AA-01", "已连接", ["192.168.1.2", "10.1.2.3"], True)
        self.assertEqual(adapter_source_ip(adapter, {}), "10.1.2.3")

    def test_adapter_source_ip_falls_back_to_other_subnet(self):
        adapter = AdapterInfo("Wi-Fi", "AA-01", "已连接", ["192.168.1.2"], True)
        self.assertEqual(adapter_source_ip(adapter, {}), "192.168.1.2")

    def test_adapter_source_ip_skips_apipa_address(self):
        adapter = AdapterInfo("Wi-Fi", "AA-01", "已连接", ["169.254.10.2", "192.168.1.2"], True)
        self.assertEqual(adapter_source_ip(adapter, {}), "192.168.1.2")
        adapter = AdapterInfo("Wi-Fi", "AA-01", "已连接", ["169.254.10.2"], True)
        self.assertEqual(adapter_source_ip(adapter, {}), "")

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
    def test_accounts_are_stored_as_plain_json(self):
        accounts = [{"account": "student", "password": "plain-password"}]
        with tempfile.TemporaryDirectory() as temporary, patch.object(
            storage, "ACCOUNTS_PATH", Path(temporary) / "accounts.json"
        ):
            storage.save_accounts(accounts)
            saved_text = storage.ACCOUNTS_PATH.read_text(encoding="utf-8")
            loaded = storage.load_accounts()
        self.assertIn("plain-password", saved_text)
        self.assertEqual(loaded, accounts)

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

    def test_export_file_is_portable_json(self):
        accounts = [{"account": "student", "password": "secret-password"}]
        with tempfile.TemporaryDirectory() as temporary, patch.object(
            storage, "load_accounts", return_value=accounts
        ):
            destination = Path(temporary) / "accounts.json"
            count = export_accounts_file(destination)
            exported = json.loads(destination.read_text(encoding="utf-8"))
        self.assertEqual(count, 1)
        self.assertEqual(exported["accounts"], accounts)

    def test_import_file_merges_and_updates_accounts(self):
        imported = [
            {"account": "existing", "password": "new-password"},
            {"account": "new", "password": "new-secret"},
        ]
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary) / "accounts.json"
            source.write_text(json.dumps(imported), encoding="utf-8")
            with patch.object(
                storage,
                "load_accounts",
                return_value=[{"account": "existing", "password": "old-password"}],
            ), patch.object(storage, "save_accounts") as save_accounts:
                added, updated = import_accounts_file(source)
        self.assertEqual((added, updated), (1, 1))
        save_accounts.assert_called_once_with(imported)


class FirstRunTests(unittest.TestCase):
    def test_finish_saves_account_and_registers_autostart(self):
        dialog = MagicMock()
        dialog.adapter.current.return_value = 0
        dialog.account.get.return_value = "student"
        dialog.password.get.return_value = "secret"
        dialog.autostart.get.return_value = False
        dialog.adapters = [
            AdapterInfo("Ethernet", "AA-BB-CC-DD-EE-01", "已连接", ["10.1.2.3"], True)
        ]
        with patch.object(gui, "load_config", return_value={}), patch.object(
            gui, "save_config"
        ), patch.object(gui, "add_or_update_account"), patch.object(
            gui, "set_autostart"
        ) as set_autostart:
            gui.FirstRunDialog.finish(dialog)
        set_autostart.assert_called_once_with(False)
        dialog.destroy.assert_called_once_with()


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
        text = f"{digest}  GDUTAutoLogin-1.1.3-win64.exe\n"
        self.assertEqual(_expected_hash(text, "GDUTAutoLogin-1.1.3-win64.exe"), digest)
        with self.assertRaises(RuntimeError):
            _expected_hash(text, "different.exe")

    def test_update_info_defaults_to_current_version(self):
        info = UpdateInfo()
        self.assertFalse(info.available)
        self.assertEqual(info.current_version, "1.2.2")

    def test_replace_with_retry_replaces_existing_file(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source, target = root / "new.exe", root / "current.exe"
            source.write_bytes(b"new")
            target.write_bytes(b"old")
            _replace_with_retry(source, target)
            self.assertEqual(target.read_bytes(), b"new")


class MonitorThreadTests(unittest.TestCase):
    def test_thread_runs_checks_until_stopped(self):
        import threading as threading_module

        thread = service.MonitorThread()
        calls = []

        def fake_check(**kwargs):
            calls.append(kwargs)
            thread.stop()
            return {"state": "online", "state_text": "ok"}

        mutex = MagicMock()
        mutex.__enter__.return_value = MagicMock(acquired=True)
        with patch.object(service, "build_logger", return_value=(MagicMock(), MagicMock())), patch.object(
            service, "action_mutex", return_value=mutex
        ), patch.object(
            service,
            "load_config",
            return_value={"auto_login_enabled": True, "check_interval_seconds": 30, "auto_check_updates": False},
        ), patch.object(service, "perform_check", side_effect=fake_check), patch.object(
            service, "save_status"
        ):
            thread.start()
            thread.join(timeout=5)
        self.assertFalse(thread.is_alive())
        self.assertEqual(len(calls), 1)
        self.assertTrue(calls[0]["monitor_running"])

    def test_paused_state_skips_check(self):
        import threading as threading_module

        thread = service.MonitorThread()
        timer = threading_module.Timer(0.2, thread.stop)
        with patch.object(service, "build_logger", return_value=(MagicMock(), MagicMock())), patch.object(
            service, "load_config", return_value={"auto_login_enabled": False}
        ), patch.object(service, "perform_check") as check, patch.object(
            service, "save_status"
        ) as save_status:
            timer.start()
            thread.start()
            thread.join(timeout=5)
            timer.join()
        self.assertFalse(thread.is_alive())
        check.assert_not_called()
        paused_states = [
            call.args[0]
            for call in save_status.call_args_list
            if call.args and call.args[0].get("state") == "paused"
        ]
        self.assertTrue(paused_states)


class SingleInstanceTests(unittest.TestCase):
    def test_second_process_acquire_fails_until_released(self):
        import threading as threading_module

        # Use a dedicated test mutex so a live app instance cannot interfere.
        patches = [
            patch.object(windows, "MUTEX_APP", "Local\\GDUT_AutoLogin_App_TestV1"),
            patch.object(windows, "EVENT_SHOW_WINDOW", "Local\\GDUT_AutoLogin_Show_TestV1"),
        ]
        for item in patches:
            item.start()
        self.addCleanup(lambda: [item.stop() for item in patches])
        first = windows.acquire_single_instance()
        try:
            self.assertIsNotNone(first)
            results = []
            runner = threading_module.Thread(
                target=lambda: results.append(windows.acquire_single_instance())
            )
            runner.start()
            runner.join(timeout=5)
            self.assertEqual(len(results), 1)
            self.assertIsNone(results[0])
        finally:
            first.__exit__(None, None, None)
        second = windows.acquire_single_instance()
        try:
            self.assertIsNotNone(second)
        finally:
            second.__exit__(None, None, None)


class AutostartUpgradeTests(unittest.TestCase):
    def test_legacy_task_without_hidden_args_is_reregistered(self):
        for legacy in ("", "old.exe --monitor", "old.exe"):
            calls = []
            with patch.object(
                windows, "scheduled_task_info", return_value=(True, legacy)
            ), patch.object(
                windows, "set_autostart", side_effect=lambda enabled: calls.append(enabled)
            ):
                windows.ensure_autostart_upgraded()
            self.assertEqual(calls, [True], f"legacy args {legacy!r} should be upgraded")

    def test_current_hidden_task_is_kept(self):
        calls = []
        with patch.object(
            windows, "scheduled_task_info", return_value=(True, "app.exe --hidden")
        ), patch.object(windows, "set_autostart", side_effect=lambda enabled: calls.append(enabled)):
            windows.ensure_autostart_upgraded()
        self.assertEqual(calls, [])

    def test_scheduled_task_info_reads_arguments_property(self):
        result = MagicMock()
        result.stdout = "EXISTS|app.exe --hidden\n"
        with patch.object(windows, "hidden_run", return_value=result):
            exists, arguments = windows.scheduled_task_info()
        self.assertTrue(exists)
        self.assertEqual(arguments, "app.exe --hidden")

    def test_missing_task_is_not_reregistered(self):
        calls = []
        with patch.object(
            windows, "scheduled_task_info", return_value=(False, "")
        ), patch.object(windows, "set_autostart", side_effect=lambda enabled: calls.append(enabled)):
            windows.ensure_autostart_upgraded()
        self.assertEqual(calls, [])


class TerminateInstalledTests(unittest.TestCase):
    def test_terminates_only_matching_executable(self):
        with tempfile.TemporaryDirectory() as temporary:
            installed = Path(temporary) / "GDUTAutoLogin.exe"
            installed.write_bytes(b"x")
            mine = MagicMock()
            mine.info = {"pid": 123, "exe": str(installed)}
            other = MagicMock()
            other.info = {"pid": 456, "exe": r"C:\Windows\notepad.exe"}
            with patch.object(windows, "IS_FROZEN", True), patch.object(
                windows, "INSTALLED_EXE", installed
            ), patch.object(windows.psutil, "process_iter", return_value=[mine, other]), patch.object(
                windows, "time"
            ) as fake_time:
                stopped = windows.terminate_running_installed()
            self.assertEqual(stopped, 1)
            mine.terminate.assert_called_once_with()
            other.terminate.assert_not_called()
            fake_time.sleep.assert_called_once_with(1.5)

    def test_noop_when_not_frozen(self):
        with patch.object(windows, "IS_FROZEN", False), patch.object(
            windows.psutil, "process_iter"
        ) as process_iter:
            self.assertEqual(windows.terminate_running_installed(), 0)
        process_iter.assert_not_called()


class MonitorWaitingTests(unittest.TestCase):
    def test_missing_selected_network_waits_without_warning_log(self):
        logger = MagicMock()
        lock = MagicMock(acquired=True)
        mutex = MagicMock()
        mutex.__enter__.return_value = lock
        with patch.object(service, "build_logger", return_value=(logger, MagicMock())), patch.object(
            service, "action_mutex", return_value=mutex
        ), patch.object(service, "load_state", return_value={}), patch.object(
            service, "load_config", return_value={}
        ), patch.object(service, "select_adapter", return_value=None), patch.object(
            service, "save_status"
        ):
            status = service.perform_check(monitor_running=True)
        self.assertEqual(status["state"], "adapter_missing")
        self.assertEqual(status["state_text"], "等待所选网络接口连接")
        logger.warning.assert_not_called()

    def test_disconnected_states_are_silent_waiting_states(self):
        self.assertEqual(
            service.WAITING_STATES,
            frozenset(("adapter_missing", "adapter_down", "no_ip")),
        )


if __name__ == "__main__":
    unittest.main()



