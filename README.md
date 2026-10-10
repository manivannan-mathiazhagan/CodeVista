# CodeVista

**An independent, extensible programming IDE built with Python and PySide6.**

CodeVista is designed to provide a unified development environment for statistical programming, data analysis, and automation.

The long-term vision is to support multiple programming languages, tools, and execution environments within a single application.

## Current Release — v1.0.0

The initial release focuses on **SAS programming through SASPy and SAS OnDemand for Academics (ODA)**.

Future releases will expand CodeVista beyond SAS to support additional programming languages, development tools, and integrations.

### Features

- Standalone desktop editor built using Python and PySide6.
- Open, edit, and save SAS (`.sas`) programs.
- Connect to SAS OnDemand for Academics using SASPy.
- Execute complete SAS programs using **F5 (Run All)**.
- Execute selected SAS code using **F8 (Run Selection)**.
- View SAS LOG and HTML RESULTS in separate tabs.
- Maintain a persistent SAS session across multiple submissions.
- Configure SAS connections using a single JSON configuration file.

## Installation

### Prerequisites

- Windows operating system
- Python 3.13 or later (subject to dependency compatibility)
- Java JDK 17
- Active SAS OnDemand for Academics account
- Git (optional)

### Steps

Clone the repository or download the source code.

```powershell
cd D:\Work\MyGithub\CodeVista
```

Install the required Python packages:

```powershell
python -m pip install -r requirements.txt
```

Launch CodeVista:

```powershell
python CodeVista.py
```

## Configuration

CodeVista uses a single configuration file, **sas_config.json**, for SAS connection settings.

Configure the following:

- SAS ODA host and port
- Java installation path
- SASPy authentication key
- Character encoding
- Global utilities directory (`global_utils`)

CodeVista automatically generates the private `_saspy_runtime_cfg.py` file for SASPy connectivity.

The `_authinfo` file must be placed in the application directory. You can copy it from an existing working SASPy configuration.

**Note:** The `global_utils` setting is reserved for future integration. The current release does not automatically upload or execute macros from this directory.

### Security

The following files are excluded from Git:

- `_authinfo` — SAS authentication credentials
- `_saspy_runtime_cfg.py` — generated SASPy configuration
- `sas_config.json` — machine-specific configuration

The `_authinfo_example` file is provided as a safe reference template.

Never commit credentials or authentication information to a public repository.

## Using CodeVista

1. Launch CodeVista.
2. Open an existing `.sas` program or create a new one.
3. Select **Session → Connect ODA**.
4. Execute code using F5 or F8.
5. Review execution messages in the LOG tab.
6. Review generated output in the HTML RESULTS tab.
7. Continue executing programs within the same SAS session.

## Development Roadmap

CodeVista is intended to evolve into a broader statistical programming and development environment.

Planned enhancements include:

- SAS dataset explorer and library management
- SAS Packages Framework (SPF) integration
- Global and study-specific macro management
- Additional programming language support
- Expanded data import, export, and visualization capabilities
- Integration with version control and development tools

These features are planned and are not included in the initial release.

## Project Status

**Version:** 1.0.0  
**Initial execution environment:** SAS OnDemand for Academics  
**Technology:** Python, PySide6, SASPy  
**License:** MIT

CodeVista is an independent open-source project. It is not affiliated with, endorsed by, or sponsored by SAS Institute Inc.

## License

Distributed under the MIT License. See the LICENSE file for details.
