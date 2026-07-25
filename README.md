# GDUT 校园网自动登录

适用于 Windows 10/11 的 GDUT 校园网自动连接工具，支持有线和无线网络。

## 下载

前往 [Releases](https://github.com/ymxc152/gdut-auto-login/releases/latest) 下载最新的：

```text
GDUTAutoLogin-版本号-win64.exe
```

只需要一个 EXE，不需要安装 Python，也不需要管理员权限。

## 使用方法

1. 双击下载的 EXE。
2. 选择名称或 SSID 中包含 `GDUT` 的网络。
3. 输入校园网账号和密码。
4. 点击“完成设置”。

之后程序会在后台检查网络，掉线时自动重新连接。关闭管理界面不会停止后台运行。

## 主要功能

- 自动识别 GDUT 有线或无线网络；
- 断网后自动恢复校园网认证；
- 多网卡环境只使用选定的 GDUT 接口；
- 账号管理、运行日志和自动更新；
- 开机静默运行，不弹出命令行窗口。

账号页面支持双击编辑；设置修改后直接保存，不会弹出完成提示。

## 更多说明

- [详细使用说明](docs/USER_GUIDE.md)
- [构建与发布](docs/BUILD.md)
- [设计说明](docs/DESIGN.md)
- [安全说明](SECURITY.md)
- [更新记录](CHANGELOG.md)

请仅使用本人拥有或已获得明确授权的校园网账号，并遵守学校网络管理规定。

## 开源协议

项目采用 [MIT License](LICENSE)，中文说明见 [LICENSE.zh-CN.md](LICENSE.zh-CN.md)。
