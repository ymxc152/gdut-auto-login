# 构建与发布

## 环境

- Windows 10/11 x64；
- Python 3.10 或更高版本；
- Tk/Tcl；
- 依赖见 `requirements.txt` 和 `requirements-build.txt`。

## 构建

```powershell
powershell -ExecutionPolicy Bypass -File .\build.ps1
```

构建脚本会：

1. 安装依赖；
2. 运行自动测试；
3. 使用 PyInstaller 生成无控制台单文件 EXE；
4. 在独立数据目录运行冻结版自检；
5. 生成 `SHA256SUMS.txt`；
6. 清理 `build/`、`dist/` 和临时 spec 文件。

发布文件位于 `release/`。

## 手动测试

```powershell
python -m unittest discover -s tests -v
python app.py --self-test .\self-test.json
```

## 代码签名

仓库不包含签名证书或私钥。取得可信代码签名证书后，应先签名最终 EXE，再生成 SHA-256：

```powershell
signtool sign /fd SHA256 /td SHA256 /tr https://timestamp.example.com /a .\release\GDUTAutoLogin-版本号-win64.exe
```

每次发布应上传 EXE 和对应的 `SHA256SUMS.txt`，并从干净环境重新测试。
