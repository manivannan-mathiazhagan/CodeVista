###-------------------------------------------------------------------------###
### Program Name:   CodeVista.py                                            ###
###                                                                         ###
### Application:    CodeVista                                               ###
### Version:        2.0                                                     ###
###                                                                         ###
### Purpose:        Provide a standalone SAS Integrated Development         ###
###                 Environment (IDE) for writing, editing, executing,      ###
###                 and validating SAS programs using SAS OnDemand for      ###
###                 Academics through SASPy.                                ###
###-------------------------------------------------------------------------###
### Programmed By:  Manivannan Mathialagan                                  ###
### Created On:     10Oct2026                                               ###
###-------------------------------------------------------------------------###
### Process:        1. Launch CodeVista desktop IDE using PySide6.          ###
###                 2. Connect to SAS OnDemand through SASPy.               ###
###                 3. Initialize the remote SAS workspace and libraries.   ###
###                 4. Load AUTOEXEC, global macros and study macros.       ###
###                 5. Open and edit SAS programs with syntax highlighting. ###
###                 6. Execute selected code or complete SAS programs.      ###
###                 7. Display execution logs and results in the IDE.       ###
###                 8. Browse SAS libraries, datasets and variables.        ###
###                 9. Support SAS Packages Framework (SPF) and ADAMSKI.    ###
###                10. Manage outputs and terminate the SAS session.        ###
###-------------------------------------------------------------------------###
### Security:       SAS OnDemand credentials are read from the private      ###
###                 _authinfo file configured in sas_config.json.           ###
###                 Authentication files must not be committed to source    ###
###                 control.                                                ###
###-------------------------------------------------------------------------###
### Notes:          CodeVista is a standalone PySide6-based SAS IDE.        ###
###                 SAS execution is performed through SASPy using a        ###
###                 persistent SAS OnDemand session.                        ###
###                                                                         ###
###                 Supports Run Selection, Run All, SAS logs, results,     ###
###                 dataset browsing and integrated macro execution.        ###
###                                                                         ###
###                 Local SAS programs remain platform independent.         ###
###                 Windows paths are translated as required when           ###
###                 programs are submitted to SAS OnDemand/Linux.           ###
###                                                                         ###
###                 CodeVista is maintained as an independent GitHub        ###
###                 repository with version-controlled source code.         ###
###-------------------------------------------------------------------------###
### Change History:                                                         ###
### 1.0       10Oct2026    Initial development of CodeVista SAS IDE.        ###
### 2.0       20Oct2026    Dynamic libraries and configured local storage.  ###
###                                                                         ###
###-------------------------------------------------------------------------###
from __future__ import annotations
import html
import json
import os
import re
import sys
import traceback
from pathlib import Path
import posixpath
from PySide6.QtCore import QObject, QThread, Qt, Signal, Slot, QRegularExpression
from PySide6.QtGui import QAction, QColor, QFont, QSyntaxHighlighter, QTextCharFormat, QKeySequence
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QTabWidget,
    QPlainTextEdit, QTextBrowser, QLabel, QPushButton, QFileDialog, QMessageBox,
    QSplitter, QStatusBar, QLineEdit, QDialog, QDialogButtonBox, QFormLayout,
    QToolBar, QInputDialog, QTreeWidget, QTreeWidgetItem, QTableWidget, QTableWidgetItem, QHeaderView, QFrame, QSizePolicy
)
ROOT = Path(__file__).resolve().parent
DEFAULT_SETTINGS = ROOT / 'sas_config.json'
class SasHighlighter(QSyntaxHighlighter):
    def __init__(self, doc):
        super().__init__(doc)
        self.rules = []
        def add(pattern, color, bold=False):
            fmt = QTextCharFormat()
            fmt.setForeground(QColor(color))
            if bold:
                fmt.setFontWeight(QFont.Weight.Bold)
            self.rules.append((QRegularExpression(pattern), fmt))
        add(r'\b(?:data|set|merge|if|then|else|do|end|run|quit|proc|sql|select|from|where|by|retain|length|format|informat|array|output|keep|drop|rename|libname|filename|options|title|footnote|ods|class|var|table|tables|input|datalines|cards|call|put|attrib)\b', '#569cd6', True)
        add(r'%[A-Za-z_][A-Za-z_0-9]*', '#c586c0')
        add(r'&[A-Za-z_][A-Za-z_0-9]*\.?', '#dcdcaa')
        add(r'\b\d+(?:\.\d+)?\b', '#b5cea8')
        add(r"\"(?:[^\"\\]|\\.)*\"|'(?:[^'\\]|\\.)*'", '#ce9178')
        add(r'/\*[\s\S]*?\*/|\*[^;\n]*;', '#6a9955')
    def highlightBlock(self, text):
        for regex, fmt in self.rules:
            iterator = regex.globalMatch(text)
            while iterator.hasNext():
                match = iterator.next()
                self.setFormat(match.capturedStart(), match.capturedLength(), fmt)
        # Multi-line block comments
        fmt = QTextCharFormat(); fmt.setForeground(QColor('#6a9955'))
        start = 0 if self.previousBlockState() == 1 else text.find('/*')
        while start >= 0:
            end = text.find('*/', start + (0 if self.previousBlockState() == 1 and start == 0 else 2))
            if end < 0:
                self.setFormat(start, len(text)-start, fmt)
                self.setCurrentBlockState(1)
                break
            self.setFormat(start, end+2-start, fmt)
            start = text.find('/*', end+2)
class CodeEditor(QPlainTextEdit):
    def __init__(self):
        super().__init__()
        font = QFont('Consolas', 11)
        font.setStyleHint(QFont.StyleHint.Monospace)
        self.setFont(font)
        self.setTabStopDistance(self.fontMetrics().horizontalAdvance(' ') * 4)
        self.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.setPlaceholderText('/* Write SAS code here; Ctrl+Enter runs selection or full program */')
        self.highlighter = SasHighlighter(self.document())
    def selected_or_all(self):
        cursor = self.textCursor()
        if cursor.hasSelection():
            return cursor.selectedText().replace('\u2029', '\n'), True
        return self.toPlainText(), False
class SasWorker(QObject):
    connected = Signal(str)
    disconnected = Signal(str)
    session_lost = Signal(str)
    completed = Signal(str, str, str)  # label, log, html
    failed = Signal(str, str)
    busy = Signal(bool)
    libraries_ready = Signal(object)
    dataset_ready = Signal(str, object, object, str)
    def __init__(self):
        super().__init__()
        self.session = None
        self.runtime_config = None
        self.local_paths = {}
        self.remote_files = None
        self.upload_cache = {}
    def _setup_storage(self, config):
        paths = config.get('local_paths', {})
        for key in ('logs', 'results', 'files'):
            folder = Path(paths.get(key) or (ROOT / key.title())).expanduser().resolve()
            folder.mkdir(parents=True, exist_ok=True)
            self.local_paths[key] = folder
    def _setup_remote_files(self):
        result = self.session.submit('%put CV_WORKDIR=%sysfunc(pathname(work));', results='TEXT')
        match = re.search(r'^CV_WORKDIR=(.+)$', str(result.get('LOG', '')), re.M)
        if not match:
            raise RuntimeError('Unable to determine SAS WORK directory')
        self.remote_files = match.group(1).strip()
        if any(c in self.remote_files for c in ('"', "'", ';')):
            raise ValueError('Unexpected characters in remote SAS WORK path')
        self.session.submit(
            f'filename CVFILES "{self.remote_files}"; %global CV_FILES; %let CV_FILES={self.remote_files};',
            results='TEXT')
        self.upload_cache.clear()
    def _upload_local_inputs(self, code, paths):
        for path in paths['files'].iterdir():
            if not path.is_file() or path.name.lower() not in code.lower():
                continue
            stat = path.stat()
            signature = (stat.st_size, stat.st_mtime_ns)
            if self.upload_cache.get(path.name) == signature:
                continue
            result = self.session.upload(str(path), f'{self.remote_files}/{path.name}', overwrite=True)
            if isinstance(result, dict) and result.get('Success') is False:
                raise RuntimeError(f'Upload failed for {path.name}: {result}')
            self.upload_cache[path.name] = signature
    def _remote_inventory(self):
        code = """options nonotes nosource;
data _null_;
  length name $1024;
  did=dopen('CVFILES');
  if did > 0 then do;
    do i=1 to dnum(did);
      name=dread(did,i);
      put 'CV_FILE|' name;
    end;
    rc=dclose(did);
  end;
run;
options notes source;"""
        result = self.session.submit(code, results='TEXT')
        names = set()
        for line in str(result.get('LOG', '')).splitlines():
            line = line.strip()
            if line.startswith('CV_FILE|'):
                name = line.split('CV_FILE|', 1)[1].strip()
                if name:
                    names.add(name)
        return names

    def _download_outputs(self, before, code, paths):
        after = self._remote_inventory()
        allowed = {'.xlsx', '.xls', '.csv', '.xpt', '.pdf', '.rtf',
                   '.html', '.htm', '.txt', '.json', '.xml', '.zip'}
        candidates = set(after - before)

        # A workbook can be rewritten using the SAME filename on subsequent runs.
        # Detect explicitly referenced files even if they existed before execution.
        code_lower = code.lower()
        for name in after:
            if name.lower() in code_lower:
                candidates.add(name)

        # The standard validation workbook is generated via LIBNAME XLSX and may
        # not be referenced by its full filename in the program text.
        # Capture XLSX files in the remote workspace on every run.
        candidates.update(name for name in after if name.lower().endswith('.xlsx'))

        downloaded = []
        for name in sorted(candidates):
            if Path(name).name != name or Path(name).suffix.lower() not in allowed:
                continue
            target = paths['files'] / name
            target.parent.mkdir(parents=True, exist_ok=True)
            remote = posixpath.join(self.remote_files, name)
            result = self.session.download(str(target), remote, overwrite=True)
            if isinstance(result, dict) and result.get('Success') is False:
                raise RuntimeError(f'Download failed for {name}: {result}')
            if not target.is_file() or target.stat().st_size == 0:
                raise RuntimeError(f'File was not downloaded correctly: {target} | {result}')
            downloaded.append(str(target))
            self.upload_cache.pop(name, None)
        return downloaded

    def _execution_paths(self, directive):
        if not directive:
            return self.local_paths
        base = Path(directive).expanduser()
        if not base.is_absolute():
            raise ValueError('CODEVISTA_OUTPUT_DIR must be an absolute local path')
        base = base.resolve()
        paths = {key: base / subdir for key, subdir in
                 (('logs', 'Logs'), ('results', 'Results'), ('files', 'Files'))}
        for folder in paths.values():
            folder.mkdir(parents=True, exist_ok=True)
        return paths
    def cleanup_runtime_config(self):
        if self.runtime_config is not None:
            try:
                self.runtime_config.unlink(missing_ok=True)
            except OSError:
                pass
            self.runtime_config = None
    def report_worker_exception(self, label):
        """Surface the original error and reset a dead SASPy session."""
        detail = traceback.format_exc()
        terminated = ('SASIOConnectionTerminated' in detail or
                      'No SAS process attached' in detail or
                      'SAS process has terminated unexpectedly' in detail)
        if terminated:
            self.session = None
            self.cleanup_runtime_config()
            self.session_lost.emit(
                'SAS ODA process terminated. Reconnect before running code.\n\n'
                + detail)
        else:
            self.failed.emit(label, detail)
    @Slot(str, str, str)
    def connect_session(self, cfgname, cfgfile, workdir):
        if self.session is not None:
            self.connected.emit('Already connected')
            return
        self.busy.emit(True)
        try:
            import saspy
            if workdir:
                os.chdir(workdir)  # resolves relative _authinfo for configurations that use it
            config = json.loads(Path(cfgfile).read_text(encoding='utf-8'))
            self._setup_storage(config)
            required = ['java_path', 'iom_host', 'iom_port', 'authkey', 'authinfo']
            missing = [k for k in required if not config.get(k)]
            if missing:
                raise ValueError('Missing sas_config.json fields: ' + ', '.join(missing))
            # Resolve the private authinfo beside CodeVista.py, independent of
            # the current working directory or the Windows user profile.
            auth_path = ROOT / Path(str(config['authinfo'])).name
            auth_path = auth_path.resolve()
            if not auth_path.is_file():
                raise FileNotFoundError(f'SAS ODA credentials file not found: {auth_path}')
            cfg = {'java': config['java_path'], 'iomhost': config['iom_host'],
                   'iomport': int(config['iom_port']), 'authkey': config['authkey'],
                   'encoding': config.get('encoding', 'utf-8')}
            # saspy expects a Python config module; generate it from JSON automatically.
            # The generated file is private and excluded from Git.
            runtime = ROOT / '_saspy_runtime_cfg.py'
            self.runtime_config = runtime
            runtime.write_text('SAS_config_names = ' + repr([cfgname]) + '\n'
                               + cfgname + ' = ' + repr(cfg) + '\n'
                               + 'SAS_config_options = {"lock_down": False}\n', encoding='utf-8')
            # SASPy IOM locates _authinfo under the effective home directory.
            # Match the proven SASPyStudio connection logic; AUTHINFO alone is
            # not sufficient for SASPy versions that use HOME/USERPROFILE.
            # SASPy reads the authinfo location while constructing the session.
            # Restore Windows environment immediately afterward: permanently
            # overriding USERPROFILE breaks Windows Desktop/Open File dialogs.
            keys = ('USERPROFILE', 'HOME', 'AUTHINFO')
            previous_env = {key: os.environ.get(key) for key in keys}
            try:
                os.environ['USERPROFILE'] = str(auth_path.parent)
                os.environ['HOME'] = str(auth_path.parent)
                os.environ['AUTHINFO'] = str(auth_path)
                self.session = saspy.SASsession(cfgname=cfgname, cfgfile=str(runtime))
            finally:
                for key, previous in previous_env.items():
                    if previous is None:
                        os.environ.pop(key, None)
                    else:
                        os.environ[key] = previous
            self._setup_remote_files()
            self.connected.emit(f'Connected: {cfgname} | SAS ODA session ready')
        except Exception:
            self.session = None
            self.cleanup_runtime_config()
            self.failed.emit('Connection', traceback.format_exc())
        finally:
            self.busy.emit(False)
    @Slot(str, str, str, str)
    def submit(self, code, label, directive, program_name):
        if self.session is None:
            self.failed.emit(label, 'Not connected. Choose Session > Connect first.')
            return
        self.busy.emit(True)
        try:
            # SAS Studio/ODA may leave NONOTES/NOSOURCE enabled. Ensure DATA
            # step creation notes and executed statements appear in this log.
            paths = self._execution_paths(directive)
            self._upload_local_inputs(code, paths)
            before = self._remote_inventory()
            result = self.session.submit('options notes source;\n' + code, results='HTML')
            log = str(result.get('LOG', ''))
            html_result = str(result.get('LST', ''))
            safe_label = re.sub(r'[^A-Za-z0-9_-]+', '_', program_name or label).strip('_') or 'Execution'
            (paths['logs'] / f'{safe_label}.log').write_text(log, encoding='utf-8')
            if html_result.strip():
                (paths['results'] / f'{safe_label}.html').write_text(html_result, encoding='utf-8')
            try:
                downloads = self._download_outputs(before, code, paths)
                if downloads:
                    log += '\nNOTE: CodeVista downloaded to local Files: ' + ', '.join(downloads) + '\n'
            except Exception as exc:
                log += f'\nWARNING: CodeVista file download: {exc}\n'
            self.completed.emit(label, log, html_result)
        except Exception:
            self.report_worker_exception(label)
        finally:
            self.busy.emit(False)
    @Slot()
    def load_libraries(self):
        if self.session is None:
            self.failed.emit('Libraries', 'Connect to SAS ODA first.')
            return
        self.busy.emit(True)
        try:
            code = """options nonotes nosource;
data _null_;
    set sashelp.vlibnam(keep=libname);
    if libname in ('WORK','SASHELP') or libname not in
        ('SASUSER','MAPS','MAPSSAS') then put 'CV_LIB|' libname;
run;
data _null_;
    set sashelp.vtable(keep=libname memname memtype nobs
        where=(memtype='DATA'));
    if libname in ('WORK','SASHELP') or libname not in
        ('SASUSER','MAPS','MAPSSAS') then
        put 'CV_DATASET|' libname +(-1) '|' memname +(-1) '|' nobs best32.;
run;
options notes source;"""
            result = self.session.submit(code, results='TEXT')
            log = str(result.get('LOG', ''))
            entries = []
            for line in log.splitlines():
                line = line.strip()
                if line.startswith('CV_LIB|'):
                    entries.append((line[7:].strip().upper(), None, None))
                elif line.startswith('CV_DATASET|'):
                    parts = line.split('|')
                    if len(parts) == 4:
                        entries.append((parts[1].strip().upper(), parts[2].strip().upper(), parts[3].strip()))
            errors = [line.strip() for line in log.splitlines()
                      if re.match(r'^\s*ERROR(?:\s+\d+-\d+)?:', line)]
            if errors:
                raise RuntimeError('SAS library scan failed:\n' + '\n'.join(errors) +
                                   '\n\nComplete SAS log:\n' + log)
            self.libraries_ready.emit(entries)
        except Exception:
            self.report_worker_exception('Libraries')
        finally:
            self.busy.emit(False)
    @Slot(str, str)
    def load_dataset(self, library, dataset):
        if self.session is None:
            self.failed.emit('Dataset', 'Connect to SAS ODA first.')
            return
        self.busy.emit(True)
        try:
            if not re.fullmatch(r'[A-Za-z_][A-Za-z_0-9]{0,31}', library) or not re.fullmatch(r'[A-Za-z_][A-Za-z_0-9]{0,31}', dataset):
                raise ValueError('Invalid SAS dataset name')
                # SASPyStudio uses sd2df successfully for live ODA datasets.
            # Apply the SAS OBS option before transfer to limit the preview.
            frame = self.session.sd2df(table=dataset, libref=library,
                                       dsopts={'obs': 100})
            columns = [str(c) for c in frame.columns]
            rows = [[('' if v is None else str(v)) for v in row] for row in frame.itertuples(index=False, name=None)]
            self.dataset_ready.emit(f'{library}.{dataset}', columns, rows, 'Showing up to 100 observations')
        except Exception:
            self.report_worker_exception('Dataset')
        finally:
            self.busy.emit(False)
    @Slot()
    def close_session(self):
        self.busy.emit(True)
        try:
            if self.session is not None:
                self.session.endsas()
                self.session = None
            self.cleanup_runtime_config()
            self.remote_files = None
            self.upload_cache.clear()
            self.disconnected.emit('Disconnected')
        except Exception:
            self.failed.emit('Disconnect', traceback.format_exc())
        finally:
            if self.session is None:
                self.cleanup_runtime_config()
            self.busy.emit(False)
class SettingsDialog(QDialog):
    def __init__(self, current, parent=None):
        super().__init__(parent)
        self.setWindowTitle('CodeVista SAS ODA Settings')
        form = QFormLayout(self)
        self.config_path = QLineEdit(str(DEFAULT_SETTINGS))
        form.addRow('sas_config.json:', self.config_path)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)
    def values(self):
        return {'config_path': self.config_path.text().strip()}
class MaximizedDatasetViewer(QDialog):
    """Independent, maximized read-only viewer for a remote SAS dataset."""
    def __init__(self, name, columns, rows, message, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f'CodeVista — {name}')
        self.resize(1200, 750)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        layout = QVBoxLayout(self)
        top = QHBoxLayout()
        title = QLabel(f'{name}  |  {len(rows):,} rows loaded  |  {len(columns)} variables')
        title.setStyleSheet('font-size: 13pt; font-weight: bold; color: #174a78;')
        top.addWidget(title)
        top.addStretch()
        restore = QPushButton('Restore Window')
        restore.clicked.connect(lambda: self.showNormal() if self.isMaximized() else self.showMaximized())
        top.addWidget(restore)
        close = QPushButton('Close Viewer')
        close.clicked.connect(self.close)
        top.addWidget(close)
        layout.addLayout(top)
        self.table = QTableWidget()
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.table.setSortingEnabled(False)
        self.table.setColumnCount(len(columns))
        self.table.setHorizontalHeaderLabels(columns)
        self.table.setRowCount(len(rows))
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        for r, values in enumerate(rows):
            for c, value in enumerate(values):
                self.table.setItem(r, c, QTableWidgetItem(value))
        self.table.setSortingEnabled(True)
        layout.addWidget(self.table)
        foot = QLabel(f'{message} — Data loaded from the active SAS ODA session. Read-only preview.')
        foot.setStyleSheet('color: #526779;')
        layout.addWidget(foot)
        self.setStyleSheet('''
            QDialog { background: #F4F7FA; font-family: 'Segoe UI'; }
            QTableWidget { background: white; alternate-background-color: #edf6ff;
                gridline-color: #dbe8f4; selection-background-color: #91c9fa; }
            QPushButton { background: #316B9E; color: white; border: none;
                border-radius: 8px; padding: 9px 16px; font-weight: bold; }
            QPushButton:hover { background: #23577F; }
        ''')
class Studio(QMainWindow):
    request_connect = Signal(str, str, str)
    request_submit = Signal(str, str, str, str)
    request_close = Signal()
    request_libraries = Signal()
    request_dataset = Signal(str, str)
    def __init__(self):
        super().__init__()
        self.setWindowTitle('CodeVista — SAS ODA IDE')
        self.resize(1450, 900)
        self.setMinimumSize(850, 560)
        self.settings_path = DEFAULT_SETTINGS
        self.settings = self.load_settings()
        self.paths = {}
        self.is_connected = False
        self.is_busy = False
        self.pending_library_refresh = False
        self.dataset_windows = []
        self.thread = QThread(self)
        self.worker = SasWorker()
        self.worker.moveToThread(self.thread)
        self.request_connect.connect(self.worker.connect_session)
        self.request_submit.connect(self.worker.submit)
        self.request_close.connect(self.worker.close_session)
        self.request_libraries.connect(self.worker.load_libraries)
        self.request_dataset.connect(self.worker.load_dataset)
        self.worker.connected.connect(self.on_connected)
        self.worker.disconnected.connect(self.on_disconnected)
        self.worker.session_lost.connect(self.on_session_lost)
        self.worker.completed.connect(self.on_completed)
        self.worker.failed.connect(self.on_failed)
        self.worker.busy.connect(self.on_busy)
        self.worker.libraries_ready.connect(self.on_libraries_ready)
        self.worker.dataset_ready.connect(self.on_dataset_ready)
        self.thread.start()
        self.editors = QTabWidget()
        self.editors.setObjectName('editorTabs')
        self.editors.setTabsClosable(True)
        self.editors.tabCloseRequested.connect(self.close_tab)
        self.log = QPlainTextEdit(); self.log.setReadOnly(True)
        self.log.setFont(QFont('Consolas', 10))
        self.results = QTextBrowser()
        self.results.setOpenExternalLinks(True)
        self.output = QTabWidget()
        self.output.setObjectName('outputTabs')
        self.output.addTab(self.log, 'LOG')
        self.output.addTab(self.results, 'RESULTS (HTML)')
        self.library_tree = QTreeWidget()
        self.library_tree.setHeaderLabels(['SAS Libraries / Datasets'])
        self.library_tree.itemDoubleClicked.connect(self.open_dataset)
        self.dataset_table = QTableWidget()
        self.dataset_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.dataset_table.setAlternatingRowColors(True)
        self.dataset_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        self.dataset_table.setMinimumHeight(120)
        self.data_tabs = QTabWidget()
        self.data_tabs.setObjectName('dataTabs')
        self.data_tabs.addTab(self.library_tree, 'LIBRARIES')
        self.data_tabs.addTab(self.dataset_table, 'DATASET VIEWER')
        self.data_tabs.setMinimumWidth(280)
        editor_split = QSplitter(Qt.Orientation.Horizontal)
        editor_split.setChildrenCollapsible(False)
        editor_split.setHandleWidth(7)
        editor_split.addWidget(self.data_tabs)
        editor_split.addWidget(self.editors)
        editor_split.setSizes([300, 950])
        splitter = QSplitter(Qt.Orientation.Vertical)
        splitter.setChildrenCollapsible(False)
        splitter.setHandleWidth(7)
        splitter.addWidget(editor_split); splitter.addWidget(self.output)
        splitter.setSizes([540, 260])
        # Header and IDE body share the central layout, retaining both resizable splitters.
        self.header = QFrame()
        self.header.setObjectName('brandHeader')
        self.header.setFixedHeight(78)
        header_layout = QVBoxLayout(self.header)
        header_layout.setContentsMargins(12, 7, 12, 7)
        header_layout.setSpacing(1)
        brand = QLabel('CodeVista')
        brand.setObjectName('brandTitle')
        brand.setAlignment(Qt.AlignmentFlag.AlignCenter)
        subtitle = QLabel('SAS Programming Environment  |  Powered by SASPy')
        subtitle.setObjectName('brandSubtitle')
        subtitle.setAlignment(Qt.AlignmentFlag.AlignCenter)
        header_layout.addWidget(brand)
        header_layout.addWidget(subtitle)
        central = QWidget()
        central.setObjectName('centralSurface')
        central_layout = QVBoxLayout(central)
        central_layout.setContentsMargins(12, 10, 12, 8)
        central_layout.setSpacing(9)
        central_layout.addWidget(self.header)
        central_layout.addWidget(splitter, 1)
        self.setCentralWidget(central)
        self.main_splitter = splitter
        self.editor_splitter = editor_split
        self.setStatusBar(QStatusBar())
        self.connection_label = QLabel('●  DISCONNECTED')
        self.connection_label.setObjectName('connectionIndicator')
        self.statusBar().addPermanentWidget(self.connection_label)
        self.statusBar().showMessage('Ready — Connect to SAS ODA')
        self.create_actions()
        self.new_file()
        self.apply_theme()
    def load_settings(self):
        return {'config_path': str(DEFAULT_SETTINGS)}
    def create_actions(self):
        file_menu = self.menuBar().addMenu('&File')
        session_menu = self.menuBar().addMenu('&Session')
        run_menu = self.menuBar().addMenu('&Run')
        toolbar = QToolBar('Main')
        toolbar.setObjectName('mainToolbar')
        toolbar.setMovable(False)
        toolbar.setFloatable(False)
        toolbar.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.addToolBar(toolbar)
        def action(menu, title, shortcut, fn, tool=True):
            a = QAction(title, self)
            if shortcut: a.setShortcut(QKeySequence(shortcut))
            a.triggered.connect(fn)
            menu.addAction(a)
            if tool: toolbar.addAction(a)
            return a
        action(file_menu, 'New', 'Ctrl+N', self.new_file)
        action(file_menu, 'Open...', 'Ctrl+O', self.open_file)
        action(file_menu, 'Save', 'Ctrl+S', self.save_file)
        action(file_menu, 'Save As...', 'Ctrl+Shift+S', self.save_as, False)
        toolbar.addSeparator()
        action(session_menu, 'Settings...', None, self.edit_settings, False)
        self.connect_action = action(session_menu, 'Connect ODA', None, self.connect_oda)
        self.disconnect_action = action(session_menu, 'Disconnect', None, self.disconnect_oda)
        toolbar.addSeparator()
        self.selection_action = action(run_menu, 'Run Selection', 'F8', self.run_selection)
        self.all_action = action(run_menu, 'Run All', 'F5', self.run_all)
        toolbar.addSeparator()
        self.refresh_action = action(session_menu, 'Refresh Libraries', 'F6', self.refresh_libraries)
        self.refresh_action.setEnabled(False)
        # Colored toolbar controls keep the original QAction keyboard shortcuts.
        toolbar.clear()
        def colored(text, fn, color, name):
            btn = QPushButton(text)
            btn.setObjectName(name)
            btn.setProperty('accent', color)
            btn.setMinimumHeight(36)
            btn.setMinimumWidth(82)
            btn.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.clicked.connect(fn)
            toolbar.addWidget(btn)
            return btn
        self.btn_new = colored('New', self.new_file, 'blue', 'newBtn')
        self.btn_open = colored('Open', self.open_file, 'blue', 'openBtn')
        self.btn_save = colored('Save', self.save_file, 'teal', 'saveBtn')
        toolbar.addSeparator()
        self.btn_connect = colored('Connect ODA', self.connect_oda, 'green', 'connectBtn')
        self.btn_disconnect = colored('Disconnect', self.disconnect_oda, 'red', 'disconnectBtn')
        toolbar.addSeparator()
        self.btn_selection = colored('Run Selection', self.run_selection, 'purple', 'selectionBtn')
        self.btn_all = colored('Run All', self.run_all, 'orange', 'allBtn')
        self.btn_refresh = colored('Refresh Libraries', self.refresh_libraries, 'teal', 'refreshBtn')
        action(run_menu, 'Run Selection or All', 'Ctrl+Return', self.run_auto, False)
        action(run_menu, 'Clear Log', None, self.log.clear, False)
        action(run_menu, 'Clear Results', None, self.results.clear, False)
        self.disconnect_action.setEnabled(False)
        self.selection_action.setEnabled(False)
        self.all_action.setEnabled(False)
        self.update_controls()
    def new_file(self):
        editor = CodeEditor()
        idx = self.editors.addTab(editor, 'Untitled.sas')
        self.editors.setCurrentIndex(idx)
        self.paths[editor] = None
        editor.document().modificationChanged.connect(lambda _x, ed=editor: self.update_title(ed))
    def current_editor(self):
        return self.editors.currentWidget()
    def update_title(self, editor):
        idx = self.editors.indexOf(editor)
        if idx >= 0:
            path = self.paths.get(editor)
            name = path.name if path else 'Untitled.sas'
            self.editors.setTabText(idx, name + (' *' if editor.document().isModified() else ''))
    def open_file(self):
        filename, _ = QFileDialog.getOpenFileName(self, 'Open SAS file', str(Path.home()), 'SAS files (*.sas);;All files (*)')
        if not filename: return
        path = Path(filename)
        for editor, p in self.paths.items():
            if p == path:
                self.editors.setCurrentWidget(editor); return
        try:
            content = path.read_text(encoding='utf-8-sig')
        except UnicodeDecodeError:
            content = path.read_text(encoding='cp1252')
        except OSError as exc:
            QMessageBox.critical(self, 'Open failed', str(exc)); return
        editor = CodeEditor(); editor.setPlainText(content)
        editor.document().setModified(False)
        self.paths[editor] = path
        editor.document().modificationChanged.connect(lambda _x, ed=editor: self.update_title(ed))
        idx = self.editors.addTab(editor, path.name)
        self.editors.setCurrentIndex(idx)
    def save_file(self):
        editor = self.current_editor()
        if editor is None: return False
        path = self.paths.get(editor)
        if path is None: return self.save_as()
        try:
            path.write_text(editor.toPlainText(), encoding='utf-8')
            editor.document().setModified(False)
            self.update_title(editor)
            return True
        except OSError as exc:
            QMessageBox.critical(self, 'Save failed', str(exc)); return False
    def save_as(self):
        editor = self.current_editor()
        if editor is None: return False
        filename, _ = QFileDialog.getSaveFileName(self, 'Save SAS file', str(Path.home()), 'SAS files (*.sas);;All files (*)')
        if not filename: return False
        self.paths[editor] = Path(filename)
        return self.save_file()
    def close_tab(self, index):
        editor = self.editors.widget(index)
        if editor.document().isModified():
            answer = QMessageBox.question(self, 'Unsaved changes', 'Save changes before closing?',
                QMessageBox.StandardButton.Save | QMessageBox.StandardButton.Discard | QMessageBox.StandardButton.Cancel)
            if answer == QMessageBox.StandardButton.Cancel: return False
            if answer == QMessageBox.StandardButton.Save:
                self.editors.setCurrentIndex(index)
                if not self.save_file(): return False
        self.paths.pop(editor, None)
        self.editors.removeTab(index)
        editor.deleteLater()
        if self.editors.count() == 0: self.new_file()
        return True
    def edit_settings(self):
        dialog = SettingsDialog(self.settings, self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.settings = dialog.values()
            self.statusBar().showMessage('Settings saved. Reconnect to apply.')
    def connect_oda(self):
        path = Path(self.settings['config_path']).expanduser().resolve()
        if not path.is_file():
            self.on_failed('Configuration', f'Configuration file not found: {path}')
            return
        try:
            config = json.loads(path.read_text(encoding='utf-8'))
            cfgname = config.get('config_name', 'oda')
        except Exception as exc:
            self.on_failed('Configuration', str(exc))
            return
        self.connection_label.setText('●  CONNECTING…')
        self.connection_label.setStyleSheet('color: #e69f20; font-weight: bold;')
        self.btn_connect.setText('Connecting…')
        self.btn_connect.setEnabled(False)
        self.request_connect.emit(cfgname, str(path), str(path.parent))
    def disconnect_oda(self):
        self.request_close.emit()
    def on_connected(self, msg):
        self.is_connected = True
        self.statusBar().showMessage(msg)
        self.connect_action.setEnabled(False)
        self.disconnect_action.setEnabled(True)
        self.selection_action.setEnabled(True)
        self.all_action.setEnabled(True)
        self.connection_label.setText('●  SAS ODA CONNECTED')
        self.connection_label.setStyleSheet('color: #15803d; font-weight: bold;')
        self.update_controls()
        self.pending_library_refresh = True
    def on_disconnected(self, msg):
        self.is_connected = False
        self.statusBar().showMessage(msg)
        self.connect_action.setEnabled(True)
        self.disconnect_action.setEnabled(False)
        self.selection_action.setEnabled(False)
        self.all_action.setEnabled(False)
        self.connection_label.setText('●  DISCONNECTED')
        self.connection_label.setStyleSheet('color: #dc3545; font-weight: bold;')
        self.update_controls()
        self.library_tree.clear()
    def on_session_lost(self, detail):
        self.pending_library_refresh = False
        self.is_connected = False
        self.library_tree.clear()
        self.log.setPlainText(detail)
        self.output.setCurrentIndex(0)
        self.connection_label.setText('●  SAS SESSION LOST')
        self.connection_label.setStyleSheet('color: #dc3545; font-weight: bold;')
        self.statusBar().showMessage('SAS session terminated — reconnect required')
        self.update_controls()
    def on_busy(self, busy):
        self.is_busy = busy
        self.connect_action.setEnabled(not busy and not self.is_connected)
        self.disconnect_action.setEnabled(not busy and self.is_connected)
        self.selection_action.setEnabled(not busy and self.is_connected)
        self.all_action.setEnabled(not busy and self.is_connected)
        self.update_controls()
        if busy:
            self.statusBar().showMessage('SAS ODA: working...')
        elif self.pending_library_refresh and self.is_connected:
            self.pending_library_refresh = False
            self.refresh_libraries()
    def run_selection(self):
        editor = self.current_editor()
        if editor is None: return
        cursor = editor.textCursor()
        if not cursor.hasSelection():
            self.statusBar().showMessage('Select SAS code first, or use Run All (F5).')
            return
        self.execute(cursor.selectedText().replace('\u2029', '\n'), 'Selection')
    def run_all(self):
        editor = self.current_editor()
        if editor: self.execute(editor.toPlainText(), 'Full program')
    def run_auto(self):
        editor = self.current_editor()
        if editor:
            code, selected = editor.selected_or_all()
            self.execute(code, 'Selection' if selected else 'Full program')
    def execute(self, code, label):
        if self.is_busy or not self.is_connected: return
        if not code.strip():
            self.statusBar().showMessage('No SAS code to run.'); return
        self.log.setPlainText(f'Running {label}...\n')
        self.results.clear()
        self.output.setCurrentIndex(0)
        editor = self.current_editor()
        full_text = editor.toPlainText() if editor else code
        directives = re.findall(
            r'(?im)^\s*(?:/\*\s*)?CODEVISTA_OUTPUT_DIR\s*:\s*([^\r\n*]+)',
            full_text
        )
        if len(directives) > 1:
            self.on_failed('Output directory', 'Specify only one CODEVISTA_OUTPUT_DIR directive.')
            return
        directive = directives[0].strip() if directives else ''
        path = self.paths.get(editor) if editor else None
        if path:
            program_name = path.stem
        elif directive:
            # Use the macro folder name when the editor has not been saved yet.
            # Saving the SAS file gives logs/results its exact filename instead.
            macro_folder = Path(directive.replace('\\', '/').rstrip('/')).name
            program_name = 'test_' + macro_folder if macro_folder else 'Untitled'
        else:
            program_name = 'Untitled'
        self.request_submit.emit(code, label, directive, program_name)
    def on_completed(self, label, log, results):
        self.log.setPlainText(log)
        self.results.setHtml(results if results.strip() else '<p>No HTML output returned.</p>')
        errors = len(re.findall(r'^ERROR(?:\s+\d+-\d+)?:', log, re.M))
        warnings = len(re.findall(r'^WARNING:', log, re.M))
        self.statusBar().showMessage(f'{label} completed | {errors} error line(s), {warnings} warning line(s)')
        if results.strip(): self.output.setCurrentIndex(1)
        # Refresh the remote inventory after DATA/PROC steps have finished.
        # Refresh Libraries manually while investigating SAS ODA process termination.
    def on_failed(self, label, message):
        self.log.setPlainText(f'{label} failed:\n{message}')
        self.output.setCurrentIndex(0)
        self.statusBar().showMessage(f'{label} failed — see LOG')
        if label == 'Connection':
            self.pending_library_refresh = False
            self.connection_label.setText('●  CONNECTION FAILED')
            self.connection_label.setStyleSheet('color: #dc3545; font-weight: bold;')
            self.btn_connect.setText('Connect ODA')
            self.btn_connect.setEnabled(True)
    def update_controls(self):
        ready = self.is_connected and not self.is_busy
        self.btn_connect.setEnabled(not self.is_connected and not self.is_busy)
        self.btn_connect.setText('SAS Connected' if self.is_connected else 'Connect ODA')
        self.btn_connect.setProperty('connectionState', 'connected' if self.is_connected else 'disconnected')
        self.btn_connect.style().unpolish(self.btn_connect)
        self.btn_connect.style().polish(self.btn_connect)
        self.btn_disconnect.setEnabled(ready)
        self.btn_selection.setEnabled(ready)
        self.btn_all.setEnabled(ready)
        self.btn_refresh.setEnabled(ready)
        self.refresh_action.setEnabled(ready)
    def apply_theme(self):
        """Unified professional palette inspired by the TLF Packager."""
        self.setStyleSheet("""
            QMainWindow, QWidget#centralSurface {
                background: #F4F7FA; color: #213547;
                font-family: 'Segoe UI'; font-size: 10pt;
            }
            QFrame#brandHeader { background: #B7E5E8; border-radius: 15px; }
            QLabel#brandTitle { color: #12374A; font-size: 23pt; font-weight: 750; }
            QLabel#brandSubtitle { color: #365F6B; font-size: 9pt; }
            QMenuBar { background: #FFFFFF; color: #213547; padding: 4px; }
            QMenuBar::item:selected, QMenu::item:selected { background: #D8EEF2; }
            QMenu { background: #FFFFFF; border: 1px solid #CFDCE7; padding: 5px; }
            QToolBar#mainToolbar {
                background: #EDF3F7; padding: 8px 10px; spacing: 6px;
                border-bottom: 1px solid #D5E0E9;
            }
            QToolBar::separator { background: #CAD7E1; width: 1px; margin: 5px 7px; }
            QPushButton {
                background: #316B9E; color: #FFFFFF; border: none;
                border-radius: 9px; padding: 8px 12px; font-weight: 600;
            }
            QPushButton:hover { background: #23577F; }
            QPushButton:pressed { background: #184261; }
            QPushButton:disabled { background: #E0E5EA; color: #9AA5B0; }
            QPushButton#newBtn, QPushButton#openBtn { background: #5279AD; }
            QPushButton#newBtn:hover, QPushButton#openBtn:hover { background: #385E91; }
            QPushButton#saveBtn, QPushButton#refreshBtn { background: #258F9D; }
            QPushButton#saveBtn:hover, QPushButton#refreshBtn:hover { background: #1B7380; }
            QPushButton#connectBtn { background: #258A64; }
            QPushButton#connectBtn:hover { background: #1D7051; }
            QPushButton#connectBtn[connectionState="connected"]:disabled {
                background: #D8F0E4; color: #18774E;
            }
            QPushButton#disconnectBtn { background: #C94C57; }
            QPushButton#disconnectBtn:hover { background: #AA3541; }
            QPushButton#selectionBtn, QPushButton#allBtn { background: #256C99; }
            QPushButton#selectionBtn:hover, QPushButton#allBtn:hover { background: #1C5477; }
            QPushButton#disconnectBtn:disabled, QPushButton#selectionBtn:disabled,
            QPushButton#allBtn:disabled, QPushButton#refreshBtn:disabled {
                background: #E0E5EA; color: #9AA5B0;
            }
            QPlainTextEdit, QTextBrowser, QTreeWidget, QTableWidget {
                background: #FFFFFF; color: #223649;
                border: 1px solid #D3DEE8; border-radius: 7px;
                selection-background-color: #C5E4F4;
                selection-color: #17354B;
            }
            QPlainTextEdit { padding: 8px; }
            QTabWidget::pane { background: #FFFFFF; border: 1px solid #D3DEE8; border-radius: 7px; }
            QTabBar::tab {
                background: #E5EDF3; color: #3A5369; padding: 9px 15px;
                border-top-left-radius: 7px; border-top-right-radius: 7px;
                margin-right: 3px; font-weight: 600;
            }
            QTabBar::tab:selected { background: #B7E5E8; color: #163E50; }
            QTabBar::tab:hover:!selected { background: #D1E6EF; }
            QHeaderView::section {
                background: #B7C5D5; color: #213547; padding: 8px;
                border: none; border-right: 1px solid #E5EDF3; font-weight: 700;
            }
            QTableWidget { alternate-background-color: #F2F7FB; gridline-color: #E0E8EF; }
            QTreeWidget::item { padding: 4px; }
            QTreeWidget::item:selected { background: #D1EAF2; color: #163E50; }
            QSplitter::handle { background: #E0E9F0; }
            QSplitter::handle:hover { background: #B7E5E8; }
            QStatusBar { background: #E7F1F5; color: #355267; border-top: 1px solid #D0E0E9; }
            QLineEdit { background: white; border: 1px solid #CAD9E4; border-radius: 6px; padding: 6px; }
        """)
    def refresh_libraries(self):
        if self.is_connected and not self.is_busy:
            self.statusBar().showMessage('Refreshing remote SAS libraries...')
            self.request_libraries.emit()
    def on_libraries_ready(self, entries):
        self.library_tree.clear()
        groups = {}
        for lib, dataset, nobs in entries:
            if lib not in groups:
                groups[lib] = QTreeWidgetItem(self.library_tree, [lib])
            if dataset is not None:
                child = QTreeWidgetItem(groups[lib], [f'{dataset}  ({nobs} rows)'])
                child.setData(0, Qt.ItemDataRole.UserRole, (lib, dataset))
        self.library_tree.expandAll()
        dataset_count = sum(1 for _, dataset, _ in entries if dataset is not None)
        self.statusBar().showMessage(f'Loaded {dataset_count} remote datasets across {len(groups)} libraries')
        self.data_tabs.setCurrentIndex(0)
    def open_dataset(self, item, column=0):
        info = item.data(0, Qt.ItemDataRole.UserRole)
        if info and self.is_connected and not self.is_busy:
            self.data_tabs.setCurrentIndex(1)
            self.statusBar().showMessage(f'Loading {info[0]}.{info[1]}...')
            self.request_dataset.emit(*info)
    def on_dataset_ready(self, name, columns, rows, message):
        self.dataset_table.setSortingEnabled(False)
        self.dataset_table.clear()
        self.dataset_table.setColumnCount(len(columns))
        self.dataset_table.setHorizontalHeaderLabels(columns)
        self.dataset_table.setRowCount(len(rows))
        for r, values in enumerate(rows):
            for c, value in enumerate(values):
                self.dataset_table.setItem(r, c, QTableWidgetItem(value))
        self.dataset_table.setSortingEnabled(True)
        self.data_tabs.setTabText(1, name)
        self.data_tabs.setCurrentIndex(1)
        self.statusBar().showMessage(f'{name}: {len(rows)} observations displayed | {message}')
        viewer = MaximizedDatasetViewer(name, columns, rows, message, self)
        self.dataset_windows.append(viewer)
        viewer.destroyed.connect(lambda _obj=None, w=viewer: self.dataset_windows.remove(w)
                                 if w in self.dataset_windows else None)
        viewer.showMaximized()
    def closeEvent(self, event):
        for i in range(self.editors.count()-1, -1, -1):
            if not self.close_tab(i):
                event.ignore(); return
        if self.is_busy:
            QMessageBox.warning(self, 'SAS busy', 'Wait for the SAS request to finish before closing.')
            event.ignore(); return
        # A live session must be ended in its worker thread; do not block the GUI thread.
        if self.is_connected:
            QMessageBox.information(self, 'Disconnect first', 'Disconnect the SAS session before exiting.')
            event.ignore(); return
        self.worker.cleanup_runtime_config()
        self.thread.quit()
        self.thread.wait(3000)
        event.accept()
def main():
    app = QApplication(sys.argv)
    app.setStyle('Fusion')
    window = Studio()
    window.show()
    sys.exit(app.exec())
if __name__ == '__main__':
    main()
