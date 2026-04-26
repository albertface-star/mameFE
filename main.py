"""
Python MAME Frontend - PyQt6
Gestione centralizzata dei font tramite dizionario FONT_SIZES.
"""

import datetime
import json
import os
import re
import subprocess
import sys
import time
import xml.etree.ElementTree as ET
from collections import Counter, OrderedDict
from pathlib import Path
from functools import lru_cache
import threading

from PIL import Image

if sys.platform == "win32":
    os.environ["QT_QPA_PLATFORM"] = "windows"
    os.environ["QT_ENABLE_HIGHDPI_SCALING"] = "0"
    os.environ["QT_SCALE_FACTOR_ROUNDING_POLICY"] = "PassThrough"

from PyQt6.QtCore import (Qt, QAbstractListModel, QModelIndex, QVariant,
                           QThread, pyqtSignal, QTimer, QSize,
                           QPropertyAnimation, QEasingCurve, QRect)
from PyQt6.QtWidgets import QGraphicsOpacityEffect
from PyQt6.QtGui import (QColor, QFont, QImage, QPixmap, QPalette)
from PyQt6.QtWidgets import (QAbstractItemView, QApplication, QCheckBox,
                              QComboBox, QHBoxLayout, QInputDialog, QLabel,
                              QLineEdit, QListView, QMainWindow, QMenu,
                              QPushButton, QSizePolicy, QFrame,
                              QStyledItemDelegate, QStyleOptionViewItem,
                              QVBoxLayout, QWidget)

# --- Percorsi e Configurazione ---
if getattr(sys, 'frozen', False):
    BASE_DIR = Path(sys.executable).parent.absolute()
else:
    BASE_DIR = Path(__file__).parent.absolute()

MAME_EXE        = BASE_DIR / "mame.exe"
SNAP_FOLDER     = BASE_DIR / "snap"
ROMPATH         = BASE_DIR / "roms"
HI_FOLDER       = BASE_DIR / "hiscore"
INI_FOLDER      = BASE_DIR / "ini"
ARTWORK_FOLDER  = BASE_DIR / "artwork"
ICON_FOLDER     = BASE_DIR / "icons"

GAME_LIST_FILE   = BASE_DIR / "game_list.json"
GAME_LIST_BACKUP = BASE_DIR / "game_list_OLD.json"
PLAY_COUNTS_FILE = BASE_DIR / "play_counts.json"
LISTS_FILE       = BASE_DIR / "lists.json"

MAX_PREVIEW_W = 800
MAX_PREVIEW_H = 800

_NO_WINDOW = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0

FONT_SIZES = {
    "app_base_pt": 13,
    "topbar_pt":   15,
    "counters_pt": 18,
    "header_pt":   11,
    "info_px":     16,
    "list_item_px": 22,
}

# --- Versione MAME ---
_mame_version_str = "N/A"
try:
    res = subprocess.run(
        [str(MAME_EXE), "-help"],
        capture_output=True, text=True, timeout=5, creationflags=_NO_WINDOW
    )
    if res.stdout:
        first_line = res.stdout.split('\n')[0].strip()
        m = re.search(r'(v[\d.]+)', first_line, re.IGNORECASE)
        _mame_version_str = m.group(1) if m else first_line
except Exception:
    pass

print(f"MAME:  {MAME_EXE}\nROMs:  {ROMPATH}\nSnap:  {SNAP_FOLDER}\n"
      f"Hi:    {HI_FOLDER}\nIni:   {INI_FOLDER}\nArt:   {ARTWORK_FOLDER}\nIcons: {ICON_FOLDER}\n")

# --- Utilità immagini ---
@lru_cache(maxsize=500)
def _pil_to_pixmap_cached(img_bytes: bytes, width: int, height: int) -> QPixmap:
    """Versione cached di _pil_to_pixmap che lavora su bytes per essere hashabile."""
    from io import BytesIO
    img = Image.open(BytesIO(img_bytes)).convert("RGBA")
    data = img.tobytes("raw", "RGBA")
    qimg = QImage(data, img.width, img.height, QImage.Format.Format_RGBA8888)
    return QPixmap.fromImage(qimg)

def _pil_to_pixmap(img: Image.Image) -> QPixmap:
    img = img.convert("RGBA")
    data = img.tobytes("raw", "RGBA")
    qimg = QImage(data, img.width, img.height, QImage.Format.Format_RGBA8888)
    return QPixmap.fromImage(qimg)

# Cache per le immagini snap e icone
_snap_cache = {}
_icon_cache = {}
_image_cache_lock = threading.Lock()

# --- Utilità JSON ---
def _leggi_json(path: Path, default):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default

def _scrivi_json(path: Path, data) -> None:
    tmp = path.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    tmp.replace(path)

# --- Game list I/O ---
def _leggi_game_list():
    data = _leggi_json(GAME_LIST_FILE, [])
    if isinstance(data, list):
        return data, None
    return data.get("games", []), data.get("last_game")

def _scrivi_game_list(giochi, last_game=None):
    _scrivi_json(GAME_LIST_FILE, {"games": giochi, "last_game": last_game})

def carica_o_genera_lista():
    if GAME_LIST_FILE.exists():
        print("Carico lista esistente da game_list.json...")
        giochi, _ = _leggi_game_list()
        return giochi

    print("Scansione della cartella ROMs in corso...")
    rom_files = [f for ext in ("*.zip", "*.7z", "*.rar") for f in ROMPATH.glob(ext)]
    if not rom_files:
        print(f"Nessun file ROM trovato in: {ROMPATH}")
        return []

    rom_names = {f.stem for f in rom_files}
    print(f"Trovati {len(rom_names)} file ROM. Scarico XML completo da MAME...")

    try:
        result = subprocess.run(
            [str(MAME_EXE), "-listxml"],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=120, creationflags=_NO_WINDOW
        )
        root = ET.fromstring(result.stdout)
    except subprocess.TimeoutExpired:
        print("Timeout durante -listxml globale.")
        return []
    except Exception as exc:
        print(f"Errore durante -listxml / parsing XML: {exc}")
        return []

    giochi = []
    for machine in root.iter("machine"):
        rom_name = machine.get("name", "")
        if rom_name not in rom_names:
            continue
        if machine.get("isbios") == "yes" or machine.get("isdevice") == "yes":
            continue
        if machine.get("mechanical") == "yes":
            continue

        driver = machine.find("driver")
        driver_status = driver.get("status", "good") if driver is not None else "good"
        if driver_status not in ("good", "imperfect"):
            continue

        genre_el = machine.find("genre")
        if genre_el is not None and "pinball" in (genre_el.text or "").lower():
            continue

        desc_el = machine.find("description")
        real_desc = (desc_el.text or rom_name).strip() if desc_el is not None else rom_name
        year_el = machine.find("year")
        year = (year_el.text or "????").strip() if year_el is not None else "????"

        giochi.append({"name": rom_name, "description": real_desc, "year": year, "status": driver_status})
        print(f"  OK  {rom_name} -> {real_desc} [{driver_status}]")

    _scrivi_game_list(giochi)
    print(f"\nLista creata con {len(giochi)} giochi working!")
    return giochi

def _deduplica_games(raw):
    seen = {}
    for g in raw:
        seen.setdefault(g["name"], g)
    return list(seen.values())

games = []

def carica_ultimo_gioco():
    if GAME_LIST_FILE.exists():
        _, last_game = _leggi_game_list()
        return last_game
    return None

def salva_ultimo_gioco(rom_name):
    giochi, _ = _leggi_game_list()
    _scrivi_game_list(giochi, last_game=rom_name)

def carica_play_counts():
    return _leggi_json(PLAY_COUNTS_FILE, {})

def salva_play_counts(counts):
    _scrivi_json(PLAY_COUNTS_FILE, counts)

play_counts = carica_play_counts()

_DEFAULT_LISTS = {"Interessanti": [], "Fantasy": []}

def carica_liste():
    data = _leggi_json(LISTS_FILE, None)
    if isinstance(data, dict):
        return data
    _scrivi_json(LISTS_FILE, _DEFAULT_LISTS)
    return dict(_DEFAULT_LISTS)

game_lists = carica_liste()

def salva_liste():
    _scrivi_json(LISTS_FILE, game_lists)

def liste_del_gioco(rom_name):
    return [nome for nome, giochi in game_lists.items() if rom_name in giochi]

def leggi_record_hi(rom_name):
    for ext in (".hi", ".ini", ".nv"):
        hi_path = HI_FOLDER / f"{rom_name}{ext}"
        if hi_path.exists():
            mtime = hi_path.stat().st_mtime
            data_str = datetime.datetime.fromtimestamp(mtime).strftime("%d/%m/%Y  %H:%M")
            if ext == ".ini":
                try:
                    testo = hi_path.read_text(encoding="utf-8", errors="replace").strip()
                    detail = f"\n{testo[:200]}" if testo else ""
                    return f"Score salvato il {data_str}{detail}"
                except Exception:
                    pass
            return f"Score salvato il {data_str}"
    return None

def leggi_autosave_state(rom_name):
    ini_path = INI_FOLDER / f"{rom_name}.ini"
    if not ini_path.exists():
        return False
    try:
        with open(ini_path, "r", encoding="utf-8", errors="replace") as f:
            return any(
                line.strip().startswith("autosave") and line.split()[-1] == "1"
                for line in f
            )
    except Exception:
        return False

def scrivi_autosave_state(rom_name, stato):
    ini_path = INI_FOLDER / f"{rom_name}.ini"
    lines = []
    if ini_path.exists():
        try:
            lines = ini_path.read_text(encoding="utf-8", errors="replace").splitlines(keepends=True)
        except Exception:
            pass

    val = f"autosave                  {1 if stato else 0}\n"
    new_lines, found = [], False
    for line in lines:
        if line.strip().startswith("autosave"):
            new_lines.append(val)
            found = True
        else:
            new_lines.append(line)
    if not found:
        new_lines.append(val)

    try:
        INI_FOLDER.mkdir(parents=True, exist_ok=True)
        ini_path.write_text("".join(new_lines), encoding="utf-8")
    except Exception as e:
        print(f"Errore scrittura ini per {rom_name}: {e}")

def load_snap_pixmap(rom_name):
    """Carica la snap image con caching per migliorare le prestazioni."""
    # Controlla prima la cache in memoria
    if rom_name in _snap_cache:
        return _snap_cache[rom_name]
    
    snap_path = SNAP_FOLDER / f"{rom_name}.png"
    if not snap_path.exists():
        _snap_cache[rom_name] = None
        return None
    
    try:
        with _image_cache_lock:
            img = Image.open(snap_path).convert("RGBA")
            orig_w, orig_h = img.size
            if orig_w == 0 or orig_h == 0:
                _snap_cache[rom_name] = None
                return None
            ratio = min(MAX_PREVIEW_W / orig_w, MAX_PREVIEW_H / orig_h)
            new_w, new_h = max(1, int(orig_w * ratio)), max(1, int(orig_h * ratio))
            img = img.resize((new_w, new_h), Image.LANCZOS)
            canvas = Image.new("RGBA", (MAX_PREVIEW_W, MAX_PREVIEW_H), (0, 0, 0, 0))
            canvas.paste(img, ((MAX_PREVIEW_W - new_w) // 2, (MAX_PREVIEW_H - new_h) // 2))
            pixmap = _pil_to_pixmap(canvas)
            _snap_cache[rom_name] = pixmap
            return pixmap
    except Exception as e:
        print(f"Errore snap '{rom_name}': {e}")
        _snap_cache[rom_name] = None
        return None

def load_icon_pixmap(ico_path):
    """Carica l'icona con caching per migliorare le prestazioni."""
    # Usa il percorso come chiave di cache
    path_str = str(ico_path)
    if path_str in _icon_cache:
        return _icon_cache[path_str]
    
    try:
        with _image_cache_lock:
            pixmap = _pil_to_pixmap(Image.open(ico_path).resize((32, 32), Image.LANCZOS))
            _icon_cache[path_str] = pixmap
            return pixmap
    except Exception:
        _icon_cache[path_str] = None
        return None

# Cache per le immagini snap e icone
_snap_cache = {}
_icon_cache = {}
_image_cache_lock = threading.Lock()

COL_ICON  = 0
COL_NOME  = 1
COL_ANNO  = 2
COL_ROM   = 3
COL_COUNT = 4

SORT_COL_DEFAULT = COL_COUNT
SORT_ASC_DEFAULT = False

class GameTableModel(QAbstractListModel):
    IconRole   = Qt.ItemDataRole.UserRole + 1
    RomRole    = Qt.ItemDataRole.UserRole + 2
    CountRole  = Qt.ItemDataRole.UserRole + 3
    GameRole   = Qt.ItemDataRole.UserRole + 4
    YearRole   = Qt.ItemDataRole.UserRole + 5
    StatusRole = Qt.ItemDataRole.UserRole + 6

    def __init__(self, parent=None):
        super().__init__(parent)
        self._rows = []

    def set_games(self, rows):
        self.beginResetModel()
        self._rows = rows
        self.endResetModel()

    def rowCount(self, parent=QModelIndex()):
        return len(self._rows)

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid() or index.row() >= len(self._rows):
            return QVariant()
        g = self._rows[index.row()]
        match role:
            case Qt.ItemDataRole.DisplayRole: return g["description"]
            case self.RomRole:    return g["name"]
            case self.CountRole:  return play_counts.get(g["name"], 0)
            case self.IconRole:   return _icon_cache.get(str(ICON_FOLDER / f"{g['name']}.ico"))
            case self.YearRole:   return g.get("year", "????")
            case self.GameRole:   return g
            case self.StatusRole: return g.get("status", "good")
        return QVariant()

    def game_at(self, idx):
        if 0 <= idx < len(self._rows):
            return self._rows[idx]
        return None


class GameDelegate(QStyledItemDelegate):
    ROW_H    = 38
    COL_ICON = 40
    COL_NOME = 650
    COL_ANNO = 95
    COL_ROM  = 170
    COL_CNT  = 95

    def __init__(self, is_dark=True, parent=None):
        super().__init__(parent)
        self.is_dark = is_dark

    def sizeHint(self, option, index):
        return QSize(self.COL_ICON + self.COL_NOME + self.COL_ANNO + self.COL_ROM + self.COL_CNT, self.ROW_H)

    def paint(self, painter, option, index):
        from PyQt6.QtWidgets import QStyle
        painter.save()

        font = QFont("Arial")
        font.setPixelSize(FONT_SIZES["list_item_px"])
        painter.setFont(font)

        is_selected = option.state & QStyle.StateFlag.State_Selected
        if is_selected:
            painter.fillRect(option.rect, QColor(5, 185, 228))
        elif index.row() % 2 == 0:
            painter.fillRect(option.rect, QColor(45, 45, 58) if self.is_dark else QColor(238, 238, 238))
        else:
            painter.fillRect(option.rect, QColor(30, 30, 40) if self.is_dark else QColor(216, 216, 232))

        r = option.rect
        x, y, h = r.x(), r.y(), r.height()

        rom_name = index.data(GameTableModel.RomRole)
        ico_path_str = str(ICON_FOLDER / f"{rom_name}.ico")
        icon_px = _icon_cache.get(ico_path_str)
        
        # Carica l'icona solo se non è in cache e il file esiste
        if icon_px is None and ico_path_str not in _icon_cache:
            if ICON_FOLDER.exists():
                ico_path = ICON_FOLDER / f"{rom_name}.ico"
                if ico_path.exists():
                    icon_px = load_icon_pixmap(ico_path)
        
        if icon_px:
            painter.drawPixmap(x + 4, y + (h - 32) // 2, icon_px)
        x += self.COL_ICON

        driver_status = index.data(GameTableModel.StatusRole)
        if driver_status == "imperfect":
            text_color = QColor(255, 170, 50) if self.is_dark else QColor(210, 105, 0)
        elif is_selected:
            text_color = QColor(20, 20, 25)
        else:
            text_color = QColor(220, 220, 220) if self.is_dark else QColor(20, 20, 30)
        painter.setPen(text_color)

        painter.drawText(QRect(x, y, self.COL_NOME, h),
                         Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                         "  " + (index.data(Qt.ItemDataRole.DisplayRole) or ""))
        x += self.COL_NOME

        painter.setPen(QColor(20, 20, 25) if is_selected else
                       (QColor(160, 160, 255) if self.is_dark else QColor(60, 60, 180)))
        painter.drawText(QRect(x, y, self.COL_ANNO, h),
                         Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignHCenter,
                         index.data(GameTableModel.YearRole) or "????")
        x += self.COL_ANNO

        painter.setPen(QColor(20, 20, 25) if is_selected else
                       (QColor(180, 180, 180) if self.is_dark else QColor(80, 80, 80)))
        painter.drawText(QRect(x, y, self.COL_ROM, h),
                         Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                         index.data(GameTableModel.RomRole) or "")
        x += self.COL_ROM

        cnt = index.data(GameTableModel.CountRole) or 0
        painter.setPen(QColor(20, 20, 25) if is_selected else
                       (QColor(5, 185, 228) if cnt > 0 else QColor(100, 100, 100)))
        painter.drawText(QRect(x, y, self.COL_CNT, h),
                         Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignHCenter,
                         str(cnt) if cnt > 0 else "-")

        painter.restore()


class GameListView(QListView):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._keys_held = set()

    def keyPressEvent(self, event):
        key = event.key()
        if key in (Qt.Key.Key_Down, Qt.Key.Key_Up, Qt.Key.Key_Return):
            if key in self._keys_held:
                return
            self._keys_held.add(key)
            model = self.model()
            if not model or model.rowCount() == 0:
                super().keyPressEvent(event)
                return
            cur = self.currentIndex()
            row = cur.row() if cur.isValid() else 0
            if key == Qt.Key.Key_Down:
                new_row = min(row + 1, model.rowCount() - 1)
            elif key == Qt.Key.Key_Up:
                new_row = max(row - 1, 0)
            elif key == Qt.Key.Key_Return:
                if cur.isValid():
                    self.doubleClicked.emit(cur)
                return
            else:
                return
            if new_row != row:
                new_idx = model.index(new_row, 0)
                self.setCurrentIndex(new_idx)
                self.scrollTo(new_idx, QAbstractItemView.ScrollHint.EnsureVisible)
        else:
            super().keyPressEvent(event)

    def keyReleaseEvent(self, event):
        self._keys_held.discard(event.key())


class StartupLoaderThread(QThread):
    finished = pyqtSignal(list)

    def run(self):
        if not GAME_LIST_FILE.exists() and GAME_LIST_BACKUP.exists():
            print("Trovato file di backup (refresh interrotto). Ripristino in corso...")
            GAME_LIST_BACKUP.replace(GAME_LIST_FILE)
        self.finished.emit(_deduplica_games(carica_o_genera_lista()))


class RefreshThread(QThread):
    finished = pyqtSignal(list)

    def run(self):
        if GAME_LIST_FILE.exists():
            GAME_LIST_FILE.replace(GAME_LIST_BACKUP)
        new_games = _deduplica_games(carica_o_genera_lista())
        time.sleep(0.5)
        self.finished.emit(new_games)


class MainWindow(QMainWindow):

    SORT_LABELS = {
        COL_NOME:  ("Name",  True),
        COL_ANNO:  ("Anno",  True),
        COL_ROM:   ("ROM",   True),
        COL_COUNT: ("Count", False),
    }

    _THEME = {
        True:  dict(is_dark=True,  snap="background:#000;border:1px solid #444;",
                    topbar="#2a2a32", refresh_btn="",
                    bg="#1e1e23",  fg="#dcdcdc", list_bg="#16161c", list_border="#333",
                    input_bg="#2d2d37", input_border="#444",
                    btn_bg="#32323f",  btn_hover="#46465a", btn_pressed="#5a5a78",
                    scrollbar="#e0e0e0"),
        False: dict(is_dark=False, snap="background:#d0d0e0;border:1px solid #aaa;",
                    topbar="#dcdce8",
                    refresh_btn="background-color:#dcdce8;border:1px solid #aaa;"
                                 "border-radius:4px;padding:6px 10px;color:#141414;",
                    bg="#f0f0f5",  fg="#141414", list_bg="#e1e1eb", list_border="#bbb",
                    input_bg="#c8c8d2", input_border="#aaa",
                    btn_bg="#bebece",  btn_hover="#a0a0c3", btn_pressed="#8282af",
                    scrollbar="#141414"),
    }

    def __init__(self):
        super().__init__()
        self.setWindowTitle("Python MAME Frontend")
        self._is_dark       = True
        self._sort_col      = SORT_COL_DEFAULT
        self._sort_asc      = SORT_ASC_DEFAULT
        self._current_rom   = ""
        self._is_refreshing = False
        self._refresh_thread  = None
        self._startup_thread  = None
        self._pending_game    = None
        self._snap_anim       = None

        self._build_ui()
        self._apply_dark_theme()

        self._opacity_effect = QGraphicsOpacityEffect(self.lbl_snap)
        self._opacity_effect.setOpacity(1.0)
        self.lbl_snap.setGraphicsEffect(self._opacity_effect)

        self._debounce_timer = QTimer(self)
        self._debounce_timer.setSingleShot(True)
        self._debounce_timer.setInterval(120)
        self._debounce_timer.timeout.connect(self._flush_pending_preview)

        self.search_input.setEnabled(False)
        self.combo_liste.setEnabled(False)
        self.btn_refresh.setEnabled(False)
        self.lbl_working.setText("Caricamento ROMs...")
        self.lbl_imperfect.setText("")

        self._startup_thread = StartupLoaderThread()
        self._startup_thread.finished.connect(self._on_startup_loaded)
        self._startup_thread.start()

        QTimer.singleShot(100, self.list_view.setFocus)

    def _on_startup_loaded(self, giochi):
        global games
        games = giochi
        # Pulisce le cache delle immagini quando si ricarica la lista
        _snap_cache.clear()
        _icon_cache.clear()
        self.search_input.setEnabled(True)
        self.combo_liste.setEnabled(True)
        self.btn_refresh.setEnabled(True)
        self._rebuild_list(select_name=carica_ultimo_gioco())
        self.list_view.setFocus()

    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(4, 4, 4, 4)
        root.setSpacing(4)

        BTN_H = 52
        top_widget = QWidget()
        top_widget.setObjectName("topbar")
        self.top_widget = top_widget
        top = QHBoxLayout(top_widget)
        top.setSpacing(0)
        top.setContentsMargins(8, 6, 8, 6)

        _top_font = QFont("Consolas", FONT_SIZES["topbar_pt"])

        mame_icon_path = ICON_FOLDER / "mamelogo.png"
        self.lbl_mame_icon = QLabel()
        self.lbl_mame_icon.setFixedHeight(BTN_H)
        self.lbl_mame_icon.setAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft)
        if mame_icon_path.exists():
            try:
                self.lbl_mame_icon.setPixmap(_pil_to_pixmap(Image.open(mame_icon_path)))
            except Exception:
                pass
        top.addWidget(self.lbl_mame_icon)
        top.addSpacing(6)

        self.lbl_version = QLabel(_mame_version_str)
        self.lbl_version.setFont(_top_font)
        self.lbl_version.setFixedHeight(BTN_H)
        self.lbl_version.setAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft)
        top.addWidget(self.lbl_version)

        def _make_sep():
            s = QFrame()
            s.setFrameShape(QFrame.Shape.VLine)
            s.setFixedHeight(BTN_H)
            s.setStyleSheet("color: #555;")
            return s

        top.addSpacing(16)
        top.addWidget(_make_sep())
        top.addSpacing(16)

        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Cerca gioco...")
        self.search_input.setFixedWidth(550)
        self.search_input.setFixedHeight(BTN_H)
        self.search_input.setFont(_top_font)
        self.search_input.textChanged.connect(self._filtra_giochi)
        top.addWidget(self.search_input)
        top.addSpacing(10)

        self.combo_liste = QComboBox()
        self.combo_liste.setFixedWidth(240)
        self.combo_liste.setFixedHeight(BTN_H)
        self.combo_liste.setFont(_top_font)
        self._aggiorna_combo_liste()
        self.combo_liste.currentTextChanged.connect(self._seleziona_lista_combo)
        top.addWidget(self.combo_liste)
        top.addStretch()

        _counter_font = QFont("Arial")
        _counter_font.setPixelSize(FONT_SIZES["list_item_px"])

        for attr in ("lbl_working", "lbl_imperfect"):
            lbl = QLabel("0")
            lbl.setStyleSheet("color: #05b9e4;")
            lbl.setFont(_counter_font)
            lbl.setFixedHeight(BTN_H)
            setattr(self, attr, lbl)
            top.addWidget(lbl)
            if attr == "lbl_working":
                top.addSpacing(14)

        top.addSpacing(14)
        top.addWidget(_make_sep())
        top.addSpacing(14)

        self.btn_refresh = QPushButton("Refresh")
        self.btn_refresh.setFixedWidth(160)
        self.btn_refresh.setFixedHeight(BTN_H)
        self.btn_refresh.setFont(_top_font)
        self.btn_refresh.clicked.connect(self._refresh_lista_giochi)
        top.addWidget(self.btn_refresh)
        top.addSpacing(10)

        self.chk_theme = QCheckBox("Light")
        self.chk_theme.setFixedHeight(BTN_H)
        self.chk_theme.setFont(_top_font)
        self.chk_theme.toggled.connect(self._switch_theme)
        top.addWidget(self.chk_theme)

        root.addWidget(top_widget)

        content_layout = QHBoxLayout()
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(0)

        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(0)

        header_bar = QWidget()
        header_bar.setFixedHeight(40)
        hh = QHBoxLayout(header_bar)
        hh.setContentsMargins(0, 0, 0, 0)
        hh.setSpacing(0)

        spacer_icon = QWidget()
        spacer_icon.setFixedWidth(GameDelegate.COL_ICON)
        hh.addWidget(spacer_icon)

        self.hbtn_nome  = self._make_header_btn("Name",  COL_NOME)
        self.hbtn_anno  = self._make_header_btn("Anno",  COL_ANNO)
        self.hbtn_rom   = self._make_header_btn("ROM",   COL_ROM)
        self.hbtn_lanci = self._make_header_btn("Count", COL_COUNT)
        for btn in (self.hbtn_nome, self.hbtn_anno, self.hbtn_rom, self.hbtn_lanci):
            hh.addWidget(btn, stretch=0)
        hh.addStretch()
        left_layout.addWidget(header_bar)

        self.model = GameTableModel()
        self.delegate = GameDelegate(is_dark=True)

        self.list_view = GameListView()
        self.list_view.setModel(self.model)
        self.list_view.setItemDelegate(self.delegate)
        self.list_view.setUniformItemSizes(True)
        self.list_view.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.list_view.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.list_view.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.list_view.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.list_view.doubleClicked.connect(self._lancia_gioco_selected)
        self.list_view.clicked.connect(self._on_click)
        self.list_view.selectionModel().currentChanged.connect(self._on_selection_changed)
        self.list_view.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.list_view.customContextMenuRequested.connect(self._context_menu_lista)
        left_layout.addWidget(self.list_view)

        left.setFixedWidth(1090)
        content_layout.addWidget(left)

        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(8, 8, 8, 8)
        right_layout.setSpacing(8)

        self.lbl_info = QLabel()
        self.lbl_info.setWordWrap(True)
        self.lbl_info.setStyleSheet(f"color: #aaa; font-size: {FONT_SIZES['info_px']}px;")
        self.lbl_info.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_info.setFixedHeight(30)
        right_layout.addWidget(self.lbl_info)

        self.lbl_snap = QLabel()
        self.lbl_snap.setFixedSize(MAX_PREVIEW_W, MAX_PREVIEW_H)
        self.lbl_snap.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_snap.setStyleSheet("background: #000; border: 1px solid #444;")
        right_layout.addWidget(self.lbl_snap)
        right_layout.addStretch()

        right.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        content_layout.addWidget(right)
        root.addLayout(content_layout)
        self._aggiorna_header_labels()

    def _make_header_btn(self, label, col):
        widths = {COL_NOME: GameDelegate.COL_NOME, COL_ANNO: GameDelegate.COL_ANNO,
                  COL_ROM: GameDelegate.COL_ROM, COL_COUNT: GameDelegate.COL_CNT}
        btn = QPushButton(label)
        btn.setFixedWidth(widths.get(col, 100))
        btn.setFixedHeight(40)
        btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        btn.clicked.connect(lambda _, c=col: self._click_header(c))
        btn.setFont(QFont("Arial", FONT_SIZES["header_pt"]))
        align = "center" if col in (COL_COUNT, COL_ANNO) else "left"
        padding_left = "18px" if col == COL_NOME else "5px"
        btn.setStyleSheet(f"padding:0 5px 0 {padding_left};text-align:{align};"
                          "background-color:transparent;border:none;outline:none;")
        return btn

    def _click_header(self, col):
        if self._is_refreshing:
            return
        if self._sort_col == col:
            self._sort_asc = not self._sort_asc
        else:
            self._sort_col = col
            self._sort_asc = self.SORT_LABELS[col][1]
        self._aggiorna_header_labels()
        current_game = self._current_game()
        self._refresh_current_view(select_rom=current_game["name"] if current_game else None)

    def _aggiorna_header_labels(self):
        for col, btn in [(COL_NOME, self.hbtn_nome), (COL_ANNO, self.hbtn_anno),
                         (COL_ROM, self.hbtn_rom), (COL_COUNT, self.hbtn_lanci)]:
            base = self.SORT_LABELS[col][0]
            btn.setText(base + (" ▲" if self._sort_asc else " ▼") if col == self._sort_col else base)

    def _sort_key(self, g: dict):
        if self._sort_col == COL_COUNT: return play_counts.get(g["name"], 0)
        if self._sort_col == COL_ROM:   return g["name"].lower()
        if self._sort_col == COL_ANNO:  return g.get("year", "????")
        return g["description"].lower()

    def _rebuild_list(self, filtro="", select_name=None, lista_filter=None):
        filtro_lower = filtro.lower()
        lista_roms = set(game_lists.get(lista_filter, [])) if lista_filter else None
        visible = [
            g for g in games
            if (filtro_lower in g["description"].lower() or filtro_lower in g["name"].lower())
            and (lista_roms is None or g["name"] in lista_roms)
        ]
        visible.sort(key=self._sort_key, reverse=not self._sort_asc)
        self.model.set_games(visible)

        counts = Counter(g.get("status", "good") for g in visible)
        self.lbl_working.setText(f"<span style='color:#05b9e4;'>working: {counts['good']}</span>")
        self.lbl_imperfect.setText(f"imperfect: {counts['imperfect']}")

        target = 0
        if select_name:
            found = next((i for i, g in enumerate(visible) if g["name"] == select_name), None)
            if found is not None:
                target = found

        if visible:
            idx = self.model.index(target, 0)
            self.list_view.setCurrentIndex(idx)
            self.list_view.scrollTo(idx, QAbstractItemView.ScrollHint.PositionAtCenter)
            self._aggiorna_preview(visible[target])

    def _aggiorna_preview(self, game: dict):
        self._pending_game = game
        self._debounce_timer.start()

    def _flush_pending_preview(self):
        game = self._pending_game
        if not game:
            return
        self._pending_game = None

        if self._snap_anim and self._snap_anim.state() == QPropertyAnimation.State.Running:
            self._snap_anim.stop()

        anim_out = QPropertyAnimation(self._opacity_effect, b"opacity", self)
        anim_out.setDuration(80)
        anim_out.setStartValue(self._opacity_effect.opacity())
        anim_out.setEndValue(0.0)
        anim_out.setEasingCurve(QEasingCurve.Type.OutQuad)

        def _load_and_fadein():
            self._current_rom = game["name"]
            px = load_snap_pixmap(game["name"])
            if px:
                self.lbl_snap.setPixmap(px)
                self.lbl_snap.setText("")
            else:
                self.lbl_snap.setPixmap(QPixmap())
                self.lbl_snap.setText("Nessuna anteprima")

            if leggi_autosave_state(game["name"]):
                self.lbl_info.setText("Immagine del gioco")
            else:
                record = leggi_record_hi(game["name"])
                self.lbl_info.setText(record if record else "Nessun record salvato")

            anim_in = QPropertyAnimation(self._opacity_effect, b"opacity", self)
            anim_in.setDuration(180)
            anim_in.setStartValue(0.0)
            anim_in.setEndValue(1.0)
            anim_in.setEasingCurve(QEasingCurve.Type.InQuad)
            self._snap_anim = anim_in
            anim_in.start()

        anim_out.finished.connect(_load_and_fadein)
        self._snap_anim = anim_out
        anim_out.start()

    def _on_click(self, index):
        game = self.model.game_at(index.row())
        if game:
            self._aggiorna_preview(game)

    def _on_selection_changed(self, current, previous):
        if not current.isValid():
            return
        game = self.model.game_at(current.row())
        if game:
            self._aggiorna_preview(game)

    def _filtra_giochi(self, testo):
        if self._is_refreshing:
            return
        current = self.combo_liste.currentText()
        self._rebuild_list(filtro=testo, lista_filter=current if current != "Tutti i giochi" else None)

    def _seleziona_lista_combo(self, testo):
        self._rebuild_list(filtro=self.search_input.text(),
                           lista_filter=testo if testo != "Tutti i giochi" else None)

    def _aggiorna_combo_liste(self):
        self.combo_liste.blockSignals(True)
        current = self.combo_liste.currentText()
        self.combo_liste.clear()
        self.combo_liste.addItem("Tutti i giochi")
        self.combo_liste.addItems(list(game_lists.keys()))
        self.combo_liste.setCurrentIndex(max(0, self.combo_liste.findText(current)))
        self.combo_liste.blockSignals(False)

    def _context_menu_lista(self, pos):
        game = self._current_game()
        if not game:
            return
        menu = QMenu(self)
        p = self._THEME[self._is_dark]
        menu.setStyleSheet(f"""
            QMenu {{ background-color: {p['input_bg']}; border: 1px solid {p['input_border']}; padding: 5px; }}
            QMenu::item {{ padding: 10px 30px; color: {p['fg']}; background-color: transparent; }}
            QMenu::item:selected {{ background-color: #05b9e4; color: white; }}
        """)
        rom = game["name"]
        act_reset   = menu.addAction("Reset playcounts")
        is_autosave = leggi_autosave_state(rom)
        act_autosave = menu.addAction(f"Save game on exit: {'ON' if is_autosave else 'OFF'}")
        menu.addSeparator()

        mie_liste  = liste_del_gioco(rom)
        altre_liste = [n for n in game_lists if n not in mie_liste]
        add_menu = menu.addMenu("Aggiungi a lista")
        for nome_lista in altre_liste:
            act = add_menu.addAction(nome_lista)
            act.triggered.connect(lambda checked, n=nome_lista: self._aggiungi_a_lista(rom, n))
        if altre_liste:
            add_menu.addSeparator()
        add_menu.addAction("+ Nuova lista...").triggered.connect(lambda: self._nuova_lista_dal_menu(rom))

        if mie_liste:
            rem_menu = menu.addMenu("Rimuovi da lista")
            for nome_lista in mie_liste:
                act = rem_menu.addAction(nome_lista)
                act.triggered.connect(lambda checked, n=nome_lista: self._rimuovi_da_lista(rom, n))

        chosen = menu.exec(self.list_view.viewport().mapToGlobal(pos))
        if chosen == act_reset:
            self._reset_playcount(rom)
        elif chosen == act_autosave:
            self._toggle_autosave(rom)

    def _reset_playcount(self, rom):
        if rom in play_counts:
            play_counts[rom] = 0
            salva_play_counts(play_counts)
            cur = self.list_view.currentIndex()
            if cur.isValid():
                self.model.dataChanged.emit(cur, cur)
            print(f"Play count azzerato per '{rom}'")

    def _toggle_autosave(self, rom):
        new_state = not leggi_autosave_state(rom)
        scrivi_autosave_state(rom, new_state)
        print(f"Save game on exit per '{rom}' impostato su {'ON' if new_state else 'OFF'}")

    def _current_game(self):
        idx = self.list_view.currentIndex()
        return self.model.game_at(idx.row()) if idx.isValid() else None

    def _lancia_gioco_selected(self, index):
        game = self.model.game_at(index.row())
        if game:
            self._lancia_gioco(game)

    def _lancia_gioco(self, game):
        if getattr(self, "_launching", False):
            return
        self._launching = True
        QTimer.singleShot(3000, lambda: setattr(self, "_launching", False))
        rom = game["name"]
        try:
            cmd = [str(MAME_EXE), rom, "-skip_gameinfo",
                   "-rompath", str(ROMPATH), "-artpath", str(ARTWORK_FOLDER),
                   "-view", "Bezel", "-plugin", "hiscore", "-inipath", str(INI_FOLDER)]
            subprocess.Popen(cmd, creationflags=_NO_WINDOW,
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            play_counts[rom] = play_counts.get(rom, 0) + 1
            salva_play_counts(play_counts)
            salva_ultimo_gioco(rom)
            cur = self.list_view.currentIndex()
            if cur.isValid():
                self.model.dataChanged.emit(cur, cur)
            print(f"Avviato {rom} (lanci totali: {play_counts[rom]})")
        except Exception as exc:
            print(f"Errore avvio '{rom}': {exc}")

    def _aggiungi_a_lista(self, rom, nome_lista):
        if nome_lista and rom and nome_lista in game_lists and rom not in game_lists[nome_lista]:
            game_lists[nome_lista].append(rom)
            salva_liste()
            self._refresh_current_view(rom)

    def _rimuovi_da_lista(self, rom, nome_lista):
        if nome_lista in game_lists and rom in game_lists[nome_lista]:
            game_lists[nome_lista].remove(rom)
            salva_liste()
            self._refresh_current_view(rom)

    def _nuova_lista_dal_menu(self, rom):
        nome, ok = QInputDialog.getText(self, "Nuova lista", "Nome della nuova lista:")
        nome = nome.strip()
        if not ok or not nome or nome in game_lists:
            return
        game_lists[nome] = [rom]
        salva_liste()
        self._aggiorna_combo_liste()
        self._refresh_current_view(rom)

    def _refresh_current_view(self, select_rom=None):
        current_filter = self.combo_liste.currentText()
        lista_filter = current_filter if current_filter != "Tutti i giochi" else None
        self._rebuild_list(filtro=self.search_input.text(), lista_filter=lista_filter,
                           select_name=select_rom)

    def _refresh_lista_giochi(self):
        if self._is_refreshing:
            return
        self._is_refreshing = True
        self.btn_refresh.setText("Attendi...")
        for w in (self.btn_refresh, self.search_input, self.combo_liste):
            w.setEnabled(False)
        self.lbl_working.setText("Scansione...")
        self.lbl_imperfect.setText("")
        self._refresh_thread = RefreshThread()
        self._refresh_thread.finished.connect(self._applica_refresh)
        self._refresh_thread.start()

    def _applica_refresh(self, new_games):
        global games
        _scrivi_game_list(new_games)
        if GAME_LIST_BACKUP.exists():
            GAME_LIST_BACKUP.unlink()
        games = new_games
        # Pulisce le cache delle immagini durante il refresh
        _snap_cache.clear()
        _icon_cache.clear()
        self._is_refreshing = False
        self.btn_refresh.setText("Refresh")
        for w in (self.btn_refresh, self.search_input, self.combo_liste):
            w.setEnabled(True)
        self._rebuild_list()
        print("--- Aggiornamento completato! ---\n")

    def _switch_theme(self, light):
        self._apply_theme(not light)
        self.list_view.viewport().update()

    def _apply_dark_theme(self):
        self._apply_theme(dark=True)

    def _apply_theme(self, dark: bool):
        p = self._THEME[dark]
        self._is_dark = p["is_dark"]
        self.delegate.is_dark = p["is_dark"]
        self.lbl_snap.setStyleSheet(p["snap"])
        self.btn_refresh.setStyleSheet(p["refresh_btn"])
        self.lbl_working.setStyleSheet("color: #05b9e4;")
        self.lbl_imperfect.setStyleSheet("color: #05b9e4;")
        self.top_widget.setStyleSheet(f"#topbar {{ background-color: {p['topbar']}; }}")
        self.setStyleSheet(f"""
            QMainWindow, QWidget, QLabel, QPushButton, QLineEdit, QComboBox, QCheckBox {{
                background-color: {p['bg']}; color: {p['fg']};
            }}
            QListView {{
                background-color: {p['list_bg']}; border: 1px solid {p['list_border']}; outline: none;
            }}
            QListView::item:selected {{ background-color: #05b9e4; color: white; }}
            QLineEdit, QComboBox {{
                background-color: {p['input_bg']}; border: 1px solid {p['input_border']};
                border-radius: 4px; padding: 6px; color: {p['fg']};
            }}
            QPushButton {{
                background-color: {p['btn_bg']}; border: 1px solid {p['input_border']};
                border-radius: 4px; padding: 6px 10px; color: {p['fg']};
            }}
            QPushButton:hover   {{ background-color: {p['btn_hover']}; }}
            QPushButton:pressed {{ background-color: {p['btn_pressed']}; }}
            QLabel {{ color: {p['fg']}; background-color: transparent; }}
            QScrollBar:vertical {{ background: transparent; width: 12px; border: none; }}
            QScrollBar::handle:vertical {{
                background: {p['scrollbar']}; border-radius: 5px; min-height: 30px;
            }}
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0px; }}
            QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{ background: none; }}
        """)

    def closeEvent(self, event):
        if self._is_refreshing:
            event.ignore()
        elif self._startup_thread and self._startup_thread.isRunning():
            self._startup_thread.wait(3000)
            event.accept()
        else:
            event.accept()


if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setFont(QFont("Arial", FONT_SIZES["app_base_pt"]))
    window = MainWindow()
    window.showMaximized()
    sys.exit(app.exec())