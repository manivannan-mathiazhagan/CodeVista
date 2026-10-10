# CodeVista v0.1.1

Independent PySide6 SAS editor powered by SASPy and SAS OnDemand for Academics.

## Install

```powershell
cd D:\Work\MyGithub\CodeVista
py -3.13 -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python CodeVista.py
```

## One configuration file

Edit **sas_config.json** for SAS ODA host, port, Java path, authkey, encoding, and global_utils. The app generates a private `_saspy_runtime_cfg.py` automatically; you do not maintain that file. Keep `_authinfo` in the same directory, copied from your working SASPyStudio installation. `_authinfo` is a separate credentials file and is never included in the ZIP. `global_utils` is retained for future integration; v0.1.1 does not automatically upload or include macros from this local directory.

**Security:** `_authinfo` and `_saspy_runtime_cfg.py` are Git-ignored. Do not commit credentials. `sas_config.json` contains no password, but is Git-ignored because it contains machine-specific paths. `_authinfo_example` is safe to commit.

## Usage

Open and save `.sas` files, connect via Session > Connect ODA, press **F5** for Run All or **F8** for Run Selection. LOG and HTML RESULTS are separate tabs. The session persists across submissions.

This version has not been tested against your actual ODA account. It does not yet include the dataset explorer, SPF manager or ADAMSKI runner.

## License

MIT. CodeVista is independent and not affiliated with SAS Institute.
