"""
config.py — Constants, i18n strings, patterns, conflict groups.
"""

C_BG        = "#000000"
C_FG        = "#ffffff"
C_FG_DIM    = "#a0a0a0"
C_RED       = "#ff0000"
C_RED_DIM   = "#7a0000"
C_RED_SEL   = "#3a0000"
C_RED_HOVER = "#cc0000"
C_WARN      = "#553300"
C_WARN_BG   = "#2a1a00"

F_TITLE  = ("Arial", 14, "bold")
F_SUB    = ("Arial", 9)
F_NORM   = ("Arial", 10)
F_SMALL  = ("Arial", 9)
F_BTN    = ("Arial", 10, "bold")
F_HEAD   = ("Arial", 10, "bold")
F_LOG    = ("Courier New", 9)
F_ROW    = ("Arial", 10, "bold")
F_ROW_S  = ("Arial", 9)

APP_NAME = "GMod Addon Manager"
APP_VERSION = "1.2.1"

CONFIG_FILE      = "gmod_manager.json"
CACHE_FILE       = "gmod_cache.json"
SESSION_FILE     = "gmod_session.json"
LOG_FILE         = "gmod_manager.log"
COLLECTIONS_FILE = "gmod_collections.json"

TEXT_EXTENSIONS = {".txt", ".json", ".lua", ".md", ".cfg", ".ini", ".xml"}

RAW_MARKERS = ("lua/", "materials/", "models/", "sound/",
               "scripts/", "particles/", "scenes/", "resource/")

KNOWN_DEPENDENCIES = {
    r"\bdrgbase\b": "DrGBase",
    r"\bvj_base\b": "VJ Base",
    r"\bvjbase\b": "VJ Base",
    r"\barc[_]?cw\b": "ArcCW",
    r"\barc9\b": "ARC9",
    r"\btfa[_]?base\b": "TFA Base",
    r"\bwiremod\b": "Wiremod",
    r"\bwire[_]?expression[2]?\b": "Wiremod",
    r"\bpac3\b": "PAC3",
    r"\bsimfphys\b": "Simfphys",
    r"\bcfc[_]?player\b": "CFC",
    r"\bnutscript\b": "NutScript",
    r"\bhelix\b": "Helix",
    r"\bsam[_]?admin\b": "SAM",
    r"\bwac[_]?aircraft\b": "WAC",
    r"\bwos[_ ]?dynabase\b": "wOS DynaBase",
    r"\bdynabase\b": "wOS DynaBase",
    r"\benhanced[_ ]?parakeet": "Enhanced Parakeets Pill Base",
    r"\bparakeet": "Parakeet's Pill Base",
    r"\bpill[_ ]?base\b": "Pill Base",
    r"\baddpill\b": "Pill Base",
    r"\boutcome[_ ]?memories\b": "Outcome Memories Pack",
    r"\bulx\b": "ULX",
    r"\bulib\b": "ULib",
    r"\bdarkrp\b": "DarkRP",
    r"\bm9k\b": "M9K",
    r"\bcw[_]?2\.0\b": "CW 2.0",
    r"\bsbx\b": "SBX",
}

LUA_DEP_HINTS = {
    r"\bif\s+VJ\s+then\b": "VJ Base",
    r"\bif\s+DrGBase\s+then\b": "DrGBase",
    r"\bif\s+ArcCW\s+then\b": "ArcCW",
    r"\bif\s+simfphys\s+then\b": "Simfphys",
    r"\bif\s+CFC\s+then\b": "CFC",
}

LUA_REF_PATTERNS = [
    r'require\s*\(\s*["\']([^"\']+)["\']',
    r'include\s*\(\s*["\']([^"\']+)["\']',
]

GENERIC_REFS = {
    "shared.lua", "init.lua", "cl_init.lua", "sv_init.lua",
    "loader.lua", "sound.lua", "autorun.lua", "config.lua",
    "sh_config.lua", "cl_util.lua", "sv_util.lua", "shared/util.lua",
}

LUA_DANGER_PATTERNS = [
    (r'\bos\.execute\s*\(',        'os.execute (shell)'),
    (r'\bio\.popen\s*\(',          'io.popen (shell)'),
    (r'\bos\.remove\s*\(',         'os.remove (delete file)'),
    (r'\bos\.rename\s*\(',         'os.rename (rename file)'),
    (r'\bRunString[A-Za-z]*\s*\(', 'RunString (dynamic code)'),
    (r'\bCompileString\s*\(',      'CompileString (dynamic code)'),
    (r'\bhttp\.Fetch\s*\(',        'http.Fetch (network)'),
    (r'\bhttp\.Post\s*\(',         'http.Post (network)'),
    (r'STEAM_0:\d+:\d+',           'Hardcoded SteamID'),
    (r'\bfile\.Delete\s*\(',       'file.Delete'),
    (r'\bfile\.Write\s*\(',        'file.Write'),
]

ASSET_REF_PATTERNS = [
    r'util\.Precache(?:Model|Sound|Material|Texture|Sentence)\s*\(\s*["\']([^"\']+)["\']',
    r'\bMaterial\s*\(\s*["\']([^"\']+)["\']',
    r'["\']((?:models|materials|sound|particles|scenes|resource)/[^"\']{4,})["\']',
    r'["\']([^"\']{6,}\.(?:mdl|vmt|vtf|vvd|phy|anm|wav|mp3|ogg))["\']',
]

LUA_GLOBAL_DEF_PATTERNS = [
    r'^\s*(\w+)\s*=\s*\1\s+or\s*\{\}',
    r'^\s*(\w+)\s*=\s*\{\s*\}\s*$',
]

LUA_HOOK_ID_PATTERN = r'hook\.Add\s*\(\s*["\']([^"\']+)["\']\s*,\s*["\']([^"\']+)["\']'
LUA_NETSTR_PATTERN  = r'util\.AddNetworkString\s*\(\s*["\']([^"\']+)["\']'
LUA_CONCMD_PATTERN  = r'concommand\.Add\s*\(\s*["\']([^"\']+)["\']'
LUA_CVAR_PATTERN    = r'Create(?:Client)?ConVar\s*\(\s*["\']([^"\']+)["\']'
LUA_EXTERNAL_USE_PATTERN = r'(?:^|[\s;(])([A-Z][A-Za-z0-9_]*)\.'

KNOWN_LUA_GLOBALS = {
    "PILL", "VJ", "DrGBase", "DrgBase", "drgbase",
    "ArcCW", "ARC9", "TFA", "CFC", "simfphys",
    "Wire", "PAC3", "pac",
}

# Framework globals that only ONE addon should ever load.
EXCLUSIVE_GLOBALS = {
    "PILL": "Only one Pill Base framework can be loaded at a time.",
    "DrGBase": "Only one DrGBase version can be loaded at a time.",
    "DrgBase": "Only one DrGBase version can be loaded at a time.",
    "VJ": "Only one VJ Base version can be loaded at a time.",
}

FRAMEWORK_MIN_LUA_FILES = 5

MIN_ASSET_REF_LEN = 10
MAX_TEXT_SIZE = 2 * 1024 * 1024
MAX_ZIP_TOTAL = 8 * 1024 * 1024 * 1024
MAX_NESTED_DEPTH = 3
MAX_NESTED_IN_MEM = 300 * 1024 * 1024
FILTER_DEBOUNCE_MS = 150
PARALLEL_WORKERS = 4
WATCH_POLL_SECONDS = 3
CACHE_MAX_ENTRIES = 2000
MAX_SUMMARY_LINES = 4000

WINDOWS_RESERVED = {
    "CON", "PRN", "AUX", "NUL",
    "COM1", "COM2", "COM3", "COM4", "COM5", "COM6", "COM7", "COM8", "COM9",
    "LPT1", "LPT2", "LPT3", "LPT4", "LPT5", "LPT6", "LPT7", "LPT8", "LPT9",
}

DEFAULT_LANG = "en"

STRINGS = {
    "en": {
        "lang_button": "ES",
        "menu_file": "File",
        "menu_edit": "Edit",
        "menu_tools": "Tools",
        "menu_help": "Help",
        "menu_add_files": "Add files...",
        "menu_add_folder": "Add folder...",
        "menu_exit": "Exit",
        "menu_select_all": "Select all",
        "menu_select_none": "Select none",
        "menu_invert": "Invert selection",
        "menu_remove": "Remove marked",
        "menu_clear": "Clear list",
        "menu_analyze": "Analyze",
        "menu_extract": "Extract",
        "menu_summary": "Show summary",
        "menu_conflicts": "Detect conflicts",
        "menu_about": "About",
        "menu_shortcuts": "Keyboard shortcuts",
        "about_body": "GMod Addon Manager v{version}\n\n"
                      "Standalone GMA / ZIP / folder addon manager for Garry's Mod.\n"
                      "No gmad.exe or Garry's Mod installation required.\n\n"
                      "github.com/AbeX2244/c00lxdgmod-manager",
        "shortcuts_body": "Ctrl+A  - Select all\n"
                          "Ctrl+D  - Deselect all\n"
                          "Ctrl+I  - Invert selection\n"
                          "Delete  - Remove marked\n"
                          "F5      - Analyze\n"
                          "F6      - Extract\n"
                          "F7      - Show summary\n"
                          "F8      - Detect conflicts\n"
                          "Ctrl+O  - Add files\n"
                          "Ctrl+Shift+O  - Add folder\n"
                          "Ctrl+L  - Focus log",
        "add_panel": "ADD",
        "files_btn": "FILES",
        "folder_btn": "FOLDER",
        "add_btn": "ADD",
        "history_btn": "HISTORY",
        "filter_panel": "FILTER",
        "search_label": "Search:",
        "group_dep": "Group by dependency (requires analysis)",
        "addons_panel": "ADDONS",
        "all_btn": "ALL",
        "none_btn": "NONE",
        "invert_btn": "INVERT",
        "remove_btn": "REMOVE",
        "clear_btn": "CLEAR",
        "export_btn": "EXPORT",
        "compact_btn": "COMPACT",
        "dest_panel": "DESTINATION",
        "choose_btn": "CHOOSE",
        "open_btn": "OPEN",
        "backup_btn": "BACKUP",
        "analyze_btn": "ANALYZE",
        "extract_btn": "EXTRACT",
        "repack_btn": "REPACK",
        "summary_btn": "SUMMARY",
        "conflicts_btn": "CONFLICTS",
        "cancel_btn": "CANCEL",
        "tools_panel": "TOOLS",
        "rename_all_btn": "RENAME ALL",
        "grep_btn": "GREP",
        "watch_btn": "WATCH",
        "collections_btn": "COLLECTIONS",
        "report_btn": "HTML REPORT",
        "sizes_btn": "SIZES",
        "fastdl_btn": "FASTDL",
        "log_panel": "LOG",
        "copy_btn": "COPY",
        "log_clear_btn": "CLEAR",
        "log_open_btn": "OPEN FILE",
        "log_autoscroll": "Auto-scroll",
        "close_btn": "CLOSE",
        "ready": "Ready.",
        "working": "Working...",
        "canceling": "Canceling...",
        "empty_title": "Empty",
        "empty_body": "No addons are marked.",
        "no_dest_title": "Missing destination",
        "no_dest_body": "Type or choose the destination folder.",
        "not_found_title": "Not found",
        "not_found_body": "Not found:\n{path}",
        "no_log_title": "Log",
        "no_log_body": "No log file yet.",
        "rename_title": "Rename",
        "rename_prompt": "New name:",
        "rename_all_title": "Rename all",
        "rename_all_prompt": "Pattern (use {i} for index, {name} for old name):",
        "action_title": "Action",
        "action_body": "Addon: {name}\n\nYes = Rename\nNo = Extract to temp and open\nCancel = Nothing",
        "dest_missing_title": "Does not exist",
        "conflicts_need_title": "Conflicts",
        "conflicts_need_body": "Mark at least 2 addons.",
        "conflicts_none_title": "Conflicts",
        "conflicts_none_body": "No conflicts between marked addons.",
        "summary_empty_title": "Summary",
        "summary_empty_body": "Nothing analyzed yet.",
        "export_empty_title": "Export",
        "export_empty_body": "No addons.",
        "save_as_title": "Save as",
        "zip_error_title": "Error reading zip",
        "error_title": "Error",
        "grep_title": "Grep inside addons",
        "grep_prompt": "Search string:",
        "grep_empty": "No matches found.",
        "grep_done": "Found {n} match(es) in {m} addon(s).",
        "repack_title": "Repack to GMA",
        "repack_prompt": "Destination .gma file:",
        "repack_need_folder": "Select exactly one folder to repack.",
        "backup_title": "Backup",
        "backup_done": "Backed up {n} existing addon(s) to {path}.",
        "watch_title": "Watch folder",
        "watch_prompt": "Choose folder to watch:",
        "watch_started": "Watching: {path}",
        "watch_stopped": "Watch stopped.",
        "watch_new": "New file detected: {name}",
        "collections_title": "Collections",
        "collections_save": "Save current list",
        "collections_load": "Load collection",
        "collections_name": "Collection name:",
        "collections_saved": "Saved: {name}",
        "collections_empty": "No collections saved yet.",
        "report_done": "Report saved: {path}",
        "sizes_title": "Size breakdown",
        "fastdl_title": "FastDL export",
        "fastdl_prompt": "Choose FastDL root folder:",
        "fastdl_done": "Copied {n} asset(s) to {path}.",
        "gmod_open_title": "Garry's Mod appears to be running",
        "gmod_open_body": "GMod should be closed before modifying addons. Continue anyway?",
        "missing_deps_title": "MISSING DEPENDENCIES",
        "missing_deps_header": "This batch requires addons that are NOT in your list:",
        "missing_deps_footer": "Without them, addons may load broken in-game (T-pose, missing animations, errors in console).",
        "missing_deps_question": "Continue extracting anyway?",
        "missing_deps_copy": "Copy names",
        "missing_deps_workshop": "Open Workshop search",
        "conflicts_title": "ADDON CONFLICTS",
        "auto_conflicts_title": "AUTO-DETECTED CONFLICTS",
        "frameworks_title": "FRAMEWORKS AND CONTENT",
        "orphan_title": "POSSIBLE EXTERNAL DEPENDENCIES",
        "orphan_body": "These addons reference assets not present in themselves.",
        "orphan_hint": "They likely require an external addon. Check the Workshop page.",
        "auto_analyze_title": "Not analyzed yet",
        "auto_analyze_body": "The addons must be analyzed first to detect dependencies and conflicts.\n\nAnalyze now?",
        "analysis_stale": "List changed since last analysis",
        "auto_analyze_done": "Auto-analysis complete.",
        "search_summary_prompt": "Find in summary:",
        "search_found": "{n} match(es)",
        "search_none": "No matches",
        "eta_prefix": "ETA {eta}",
        "status_analyzing": "Analyzing {i}/{total}: {name}",
        "status_scanning": "Scanning {i}/{total}: {name}",
        "status_extracting": "Extracting {i}/{total}: {name}",
        "status_indexing": "Indexing {i}/{total}: {name}",
        "status_analysis_ok": "Analysis complete: {n} addon(s)",
        "status_analysis_partial": "Analysis: {ok} ok, {fail} error(s)",
        "status_analysis_cancelled": "Analysis cancelled: {n}/{total}",
        "status_extract_ok": "Extraction complete: {n} addon(s)",
        "status_extract_partial": "Extraction: {ok} ok, {fail} failed",
        "status_extract_cancelled": "Extraction cancelled: {ok} ok, {fail} failed",
        "status_index_ok": "Index complete: {n} addon(s)",
        "status_index_cancelled": "Index cancelled: {n} addon(s)",
        "status_conflicts_none": "Conflicts: none",
        "status_conflicts_found": "Conflicts: {n} file(s)",
        "status_selected_all": "Selected {n} addon(s)",
        "status_deselected_all": "Deselected {n} addon(s)",
        "status_inverted": "Selection inverted: {sel} selected",
        "status_removed": "Removed {n} addon(s)",
        "status_cleared": "List cleared ({n} removed)",
        "status_exported": "Exported: {name}",
        "status_session": "Session: {n} addon(s)",
        "status_added_zip": "{name}: {n} addon(s)",
        "status_no_op": "No operation in progress.",
        "status_cancel_requested": "Cancel requested...",
        "status_counts": "{total} addon(s) - {marked} marked - {size}",
        "help_hint": "Hover any button to see what it does. Right-click a row for actions.",
        "help_add_manual": "Add the path typed in the field above",
        "help_browse": "Pick one or more .gma or .zip files",
        "help_browse_folder": "Add a raw addon folder (with lua/, materials/, ...)",
        "help_history": "Show the last 10 paths you used",
        "help_all": "Mark all addons",
        "help_none": "Unmark all addons",
        "help_invert": "Swap marked/unmarked",
        "help_remove": "Remove marked addons from the list (files stay on disk)",
        "help_clear": "Clear the entire list",
        "help_export": "Export the list as CSV, JSON, or TXT",
        "help_compact": "Toggle compact mode (hide tools)",
        "help_choose_dest": "Choose the destination folder",
        "help_open_dest": "Open the destination folder",
        "help_backup": "Backup existing addons before overwriting",
        "help_analyze": "Scan addons: dependencies, files, suspicious code",
        "help_extract": "Extract marked addons to the destination",
        "help_summary": "Reopen the last analysis report",
        "help_conflicts": "Find files that appear in 2+ addons",
        "help_cancel": "Cancel the current operation",
        "help_repack": "Pack a folder into a .gma file",
        "help_grep": "Search text inside all addons",
        "help_rename_all": "Bulk rename with a pattern",
        "help_watch": "Auto-add new files dropped in a folder",
        "help_collections": "Save/load addon list presets",
        "help_report": "Export an HTML report of the list",
        "help_sizes": "File type breakdown chart",
        "help_fastdl": "Copy assets to a FastDL folder",
        "row_menu_rename": "Rename",
        "row_menu_remove": "Remove from list",
        "row_menu_temp": "Extract to temp and open",
        "row_menu_copy": "Copy path",
        "row_menu_copy_name": "Copy name",
    },
    "es": {
        "lang_button": "EN",
        "menu_file": "Archivo",
        "menu_edit": "Editar",
        "menu_tools": "Herramientas",
        "menu_help": "Ayuda",
        "menu_add_files": "Anadir archivos...",
        "menu_add_folder": "Anadir carpeta...",
        "menu_exit": "Salir",
        "menu_select_all": "Seleccionar todo",
        "menu_select_none": "Deseleccionar todo",
        "menu_invert": "Invertir seleccion",
        "menu_remove": "Quitar marcados",
        "menu_clear": "Limpiar lista",
        "menu_analyze": "Analizar",
        "menu_extract": "Extraer",
        "menu_summary": "Mostrar resumen",
        "menu_conflicts": "Detectar conflictos",
        "menu_about": "Acerca de",
        "menu_shortcuts": "Atajos de teclado",
        "about_body": "GMod Addon Manager v{version}\n\n"
                      "Gestor de addons GMA / ZIP / carpeta para Garry's Mod.\n"
                      "No requiere gmad.exe ni Garry's Mod instalado.\n\n"
                      "github.com/AbeX2244/c00lxdgmod-manager",
        "shortcuts_body": "Ctrl+A  - Seleccionar todo\n"
                          "Ctrl+D  - Deseleccionar todo\n"
                          "Ctrl+I  - Invertir seleccion\n"
                          "Delete  - Quitar marcados\n"
                          "F5      - Analizar\n"
                          "F6      - Extraer\n"
                          "F7      - Mostrar resumen\n"
                          "F8      - Detectar conflictos\n"
                          "Ctrl+O  - Anadir archivos\n"
                          "Ctrl+Shift+O  - Anadir carpeta\n"
                          "Ctrl+L  - Foco al registro",
        "add_panel": "ANADIR",
        "files_btn": "ARCHIVOS",
        "folder_btn": "CARPETA",
        "add_btn": "ANADIR",
        "history_btn": "HISTORIAL",
        "filter_panel": "FILTRO",
        "search_label": "Buscar:",
        "group_dep": "Agrupar por dependencia (requiere analisis)",
        "addons_panel": "ADDONS",
        "all_btn": "TODO",
        "none_btn": "NADA",
        "invert_btn": "INVERTIR",
        "remove_btn": "QUITAR",
        "clear_btn": "LIMPIAR",
        "export_btn": "EXPORTAR",
        "compact_btn": "COMPACTO",
        "dest_panel": "DESTINO",
        "choose_btn": "ELEGIR",
        "open_btn": "ABRIR",
        "backup_btn": "BACKUP",
        "analyze_btn": "ANALIZAR",
        "extract_btn": "EXTRAER",
        "repack_btn": "REPACK",
        "summary_btn": "RESUMEN",
        "conflicts_btn": "CONFLICTOS",
        "cancel_btn": "CANCELAR",
        "tools_panel": "HERRAMIENTAS",
        "rename_all_btn": "RENOMBRAR TODO",
        "grep_btn": "GREP",
        "watch_btn": "VIGILAR",
        "collections_btn": "COLECCIONES",
        "report_btn": "REPORTE HTML",
        "sizes_btn": "TAMANOS",
        "fastdl_btn": "FASTDL",
        "log_panel": "REGISTRO",
        "copy_btn": "COPIAR",
        "log_clear_btn": "LIMPIAR",
        "log_open_btn": "ABRIR",
        "log_autoscroll": "Auto-scroll",
        "close_btn": "CERRAR",
        "ready": "Listo.",
        "working": "Trabajando...",
        "canceling": "Cancelando...",
        "empty_title": "Vacio",
        "empty_body": "No hay addons marcados.",
        "no_dest_title": "Falta destino",
        "no_dest_body": "Escribe o elige la carpeta destino.",
        "not_found_title": "No existe",
        "not_found_body": "No se encuentra:\n{path}",
        "no_log_title": "Log",
        "no_log_body": "Todavia no hay archivo de log.",
        "rename_title": "Renombrar",
        "rename_prompt": "Nuevo nombre:",
        "rename_all_title": "Renombrar todo",
        "rename_all_prompt": "Patron (usa {i} para indice, {name} para nombre viejo):",
        "action_title": "Accion",
        "action_body": "Addon: {name}\n\nSi = Renombrar\nNo = Extraer a temporal y abrir\nCancelar = Nada",
        "dest_missing_title": "No existe",
        "conflicts_need_title": "Conflictos",
        "conflicts_need_body": "Marca al menos 2 addons.",
        "conflicts_none_title": "Conflictos",
        "conflicts_none_body": "Sin conflictos entre los marcados.",
        "summary_empty_title": "Resumen",
        "summary_empty_body": "Aun no has analizado nada.",
        "export_empty_title": "Exportar",
        "export_empty_body": "No hay addons.",
        "save_as_title": "Guardar como",
        "zip_error_title": "Error al leer zip",
        "error_title": "Error",
        "grep_title": "Buscar dentro de addons",
        "grep_prompt": "Texto a buscar:",
        "grep_empty": "Sin coincidencias.",
        "grep_done": "{n} coincidencia(s) en {m} addon(s).",
        "repack_title": "Repack a GMA",
        "repack_prompt": "Archivo .gma destino:",
        "repack_need_folder": "Selecciona exactamente una carpeta para repackear.",
        "backup_title": "Backup",
        "backup_done": "{n} addon(s) respaldados en {path}.",
        "watch_title": "Vigilar carpeta",
        "watch_prompt": "Elige la carpeta a vigilar:",
        "watch_started": "Vigilando: {path}",
        "watch_stopped": "Vigilancia detenida.",
        "watch_new": "Nuevo archivo: {name}",
        "collections_title": "Colecciones",
        "collections_save": "Guardar lista actual",
        "collections_load": "Cargar coleccion",
        "collections_name": "Nombre de la coleccion:",
        "collections_saved": "Guardada: {name}",
        "collections_empty": "Sin colecciones guardadas.",
        "report_done": "Reporte guardado: {path}",
        "sizes_title": "Desglose de tamanos",
        "fastdl_title": "Export FastDL",
        "fastdl_prompt": "Elige la carpeta raiz de FastDL:",
        "fastdl_done": "{n} asset(s) copiados a {path}.",
        "gmod_open_title": "Garry's Mod parece estar abierto",
        "gmod_open_body": "GMod deberia estar cerrado antes de modificar addons. Continuar de todos modos?",
        "missing_deps_title": "DEPENDENCIAS FALTANTES",
        "missing_deps_header": "Este lote requiere addons que NO estan en tu lista:",
        "missing_deps_footer": "Sin ellos, los addons pueden verse rotos en el juego (T-pose, animaciones faltantes, errores en consola).",
        "missing_deps_question": "Extraer de todos modos?",
        "missing_deps_copy": "Copiar nombres",
        "missing_deps_workshop": "Abrir busqueda en Workshop",
        "conflicts_title": "CONFLICTOS ENTRE ADDONS",
        "auto_conflicts_title": "CONFLICTOS AUTO-DETECTADOS",
        "frameworks_title": "FRAMEWORKS Y CONTENIDO",
        "orphan_title": "POSIBLES DEPENDENCIAS EXTERNAS",
        "orphan_body": "Estos addons referencian assets que no estan en si mismos.",
        "orphan_hint": "Probablemente requieren un addon externo. Mira la pagina de Workshop.",
        "auto_analyze_title": "Sin analizar todavia",
        "auto_analyze_body": "Los addons deben analizarse primero para detectar dependencias y conflictos.\n\nAnalizar ahora?",
        "analysis_stale": "La lista cambio desde el ultimo analisis",
        "auto_analyze_done": "Auto-analisis completado.",
        "search_summary_prompt": "Buscar en el resumen:",
        "search_found": "{n} coincidencia(s)",
        "search_none": "Sin coincidencias",
        "eta_prefix": "Restante {eta}",
        "status_analyzing": "Analizando {i}/{total}: {name}",
        "status_scanning": "Escaneando {i}/{total}: {name}",
        "status_extracting": "Extrayendo {i}/{total}: {name}",
        "status_indexing": "Indexando {i}/{total}: {name}",
        "status_analysis_ok": "Analisis completo: {n} addon(s)",
        "status_analysis_partial": "Analisis: {ok} ok, {fail} errores",
        "status_analysis_cancelled": "Analisis cancelado: {n}/{total}",
        "status_extract_ok": "Extraccion completa: {n} addon(s)",
        "status_extract_partial": "Extraccion: {ok} ok, {fail} fallos",
        "status_extract_cancelled": "Extraccion cancelada: {ok} ok, {fail} fallos",
        "status_index_ok": "Indexado completo: {n} addon(s)",
        "status_index_cancelled": "Indexado cancelado: {n} addon(s)",
        "status_conflicts_none": "Conflictos: ninguno",
        "status_conflicts_found": "Conflictos: {n} archivo(s)",
        "status_selected_all": "Marcados {n} addon(s)",
        "status_deselected_all": "Desmarcados {n} addon(s)",
        "status_inverted": "Seleccion invertida: {sel} marcados",
        "status_removed": "Quitados {n} addon(s)",
        "status_cleared": "Lista limpiada ({n} eliminados)",
        "status_exported": "Exportado: {name}",
        "status_session": "Sesion: {n} addon(s)",
        "status_added_zip": "{name}: {n} addon(s)",
        "status_no_op": "No hay operacion en curso.",
        "status_cancel_requested": "Cancelacion solicitada...",
        "status_counts": "{total} addon(s) - {marked} marcados - {size}",
        "help_hint": "Pasa el cursor por un boton para ver que hace. Clic derecho en una fila para acciones.",
        "help_add_manual": "Anade la ruta escrita en el campo",
        "help_browse": "Elige uno o varios .gma o .zip",
        "help_browse_folder": "Anade una carpeta cruda (con lua/, materials/, ...)",
        "help_history": "Muestra las ultimas 10 rutas usadas",
        "help_all": "Marca todos los addons",
        "help_none": "Desmarca todos",
        "help_invert": "Invierte marcados/desmarcados",
        "help_remove": "Quita los marcados de la lista (archivos intactos)",
        "help_clear": "Vacia toda la lista",
        "help_export": "Exporta la lista como CSV, JSON o TXT",
        "help_compact": "Alterna modo compacto (oculta herramientas)",
        "help_choose_dest": "Elige la carpeta destino",
        "help_open_dest": "Abre la carpeta destino",
        "help_backup": "Respalda los addons existentes antes de sobrescribir",
        "help_analyze": "Escanea addons: dependencias, archivos, codigo sospechoso",
        "help_extract": "Extrae los addons marcados al destino",
        "help_summary": "Reabre el ultimo reporte de analisis",
        "help_conflicts": "Encuentra archivos que aparecen en 2+ addons",
        "help_cancel": "Cancela la operacion en curso",
        "help_repack": "Empaqueta una carpeta en un .gma",
        "help_grep": "Busca texto dentro de todos los addons",
        "help_rename_all": "Renombra en masa con un patron",
        "help_watch": "Anade automaticamente archivos nuevos en una carpeta",
        "help_collections": "Guarda/carga presets de listas",
        "help_report": "Exporta un reporte HTML de la lista",
        "help_sizes": "Grafico de desglose por tipo de archivo",
        "help_fastdl": "Copia assets a una carpeta FastDL",
        "row_menu_rename": "Renombrar",
        "row_menu_remove": "Quitar de la lista",
        "row_menu_temp": "Extraer a temporal y abrir",
        "row_menu_copy": "Copiar ruta",
        "row_menu_copy_name": "Copiar nombre",
    },
}
