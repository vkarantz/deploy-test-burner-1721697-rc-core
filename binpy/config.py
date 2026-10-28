from configparser import ConfigParser
from pathlib import Path
import platform

###################################################################
#
# Looks for all config.*.ini files in the project root directory
# and loads their contents into a dictionary.
#
# Then, if REL_DIR_CLIENT is defined (or "client/" exists),
# also loads config.*.ini from that subdirectory (overrides root).
#
# Load hierarchy alphabetically (last wins):
# - config.common.ini
# - config.localmachine.ini
# - config.serverdev.ini          (gitignored, dev overrides)
# Then from client subdirectory:
# - client/config.common.ini
# - client/config.localmachine.ini
# - client/config.serverdev.ini   (gitignored, dev overrides)
#
# It will NOT LOAD e.g.
# - configTEMPLATE.ini
#


class ConfigMeta(type):
    """Metaclass that allows Config.ATTRIBUTE access like PHP static properties"""
    
    def __getattr__(cls, name):
        """Handle Config.ATTRIBUTE access"""
        cls._load()
        
        # Check class data for both ini and runtime config
        if name in cls._data:
            return cls._data[name]
            
        raise AttributeError(f"Undefined config key: {name}")
    
    def __setattr__(cls, name, value):
        """Handle Config.ATTRIBUTE = value assignment"""
        # Allow setting special internal attributes
        if name.startswith('_'):
            super().__setattr__(name, value)
            return
        
        # Ensure config is loaded first
        cls._load()
        
        # Apply _cast to runtime values for consistency (only if it's a string)
        if isinstance(value, str):
            processed_value = cls._cast(value)
        else:
            processed_value = value
        
        # Set runtime configuration in class data
        cls._data[name] = processed_value


class Config(metaclass=ConfigMeta):
    """
    Global Config class using class variables (like PHP static properties).
    No instances needed - everything is accessed via Config.ATTRIBUTE
    """
    _data = {}
    _loaded = False

    def __new__(cls):
        # Prevent instantiation - this should be used as a static class
        raise RuntimeError("Config should not be instantiated. Use Config.ATTRIBUTE directly.")

    @classmethod
    def _load_and_merge_ini_files(cls, directory: Path, *, mandatory: bool = True) -> ConfigParser:
        """
        Glob config.*.ini in `directory`, parse & merge them in alphabetical order.
        Mirror of PHP loadAndMergeIniFiles().
        """
        files = sorted(directory.glob("config.*.ini"))

        if not files:
            if mandatory:
                raise RuntimeError(f"No config.*.ini files found in {directory}")
            return ConfigParser(inline_comment_prefixes=(';', '#'))

        parser = ConfigParser(inline_comment_prefixes=(';', '#'))
        for file in files:
            try:
                with open(file, encoding='utf-8') as fh:
                    parser.read_file(fh)
            except UnicodeDecodeError:
                with open(file, encoding='cp1252') as fh:
                    parser.read_file(fh)
        return parser

    @classmethod
    def _load(cls):
        if cls._loaded:
            return

        base_dir = Path(__file__).parent.parent

        # ── Step 1: load config.*.ini from base_dir ──────────────────────
        parser = cls._load_and_merge_ini_files(base_dir)

        # ── Step 2: load config.*.ini from client subdirectory ───────────
        # Determine client dir: use REL_DIR_CLIENT from the config loaded
        # so far (any [section]), fall back to hardcoded "client".
        rel_dir_client = None
        for section in parser.sections():
            if parser.has_option(section, 'REL_DIR_CLIENT'):
                rel_dir_client = parser.get(section, 'REL_DIR_CLIENT').strip()
                break
        # Also check DEFAULT section (flat keys)
        if not rel_dir_client and 'REL_DIR_CLIENT' in parser.defaults():
            rel_dir_client = parser.defaults()['REL_DIR_CLIENT'].strip()
        # Hardcoded fallback
        if not rel_dir_client:
            candidate = base_dir / 'client'
            if candidate.is_dir():
                rel_dir_client = 'client'

        if rel_dir_client:
            client_dir = base_dir / rel_dir_client
            if client_dir.is_dir():
                client_parser = cls._load_and_merge_ini_files(client_dir, mandatory=False)
                # Merge client config into main parser (client overrides root)
                for section in client_parser.sections():
                    if not parser.has_section(section):
                        parser.add_section(section)
                    for key, value in client_parser.items(section, raw=True):
                        parser.set(section, key, value)
                # Merge DEFAULT keys
                for key, value in client_parser.defaults().items():
                    parser.set('DEFAULT', key, value)

        os_name = cls._detect_os()  # "linux" or "windows"

        # 1) Load DEFAULT + all normal sections (flattened)
        for section in parser.sections():
            if section in ("Linux", "Windows"):
                continue  # handled separately

            for key, value in parser.items(section):
                name = cls._normalize_key(key)
                cls._data[name] = cls._cast(value)

        # 2) Load DEFAULT section (flat keys without section)
        for key, value in parser.defaults().items():
            name = cls._normalize_key(key)
            cls._data[name] = cls._cast(value)

        # 3) Apply OS-specific overrides (flattened, no prefix)
        if parser.has_section(os_name):
            for key, value in parser.items(os_name):
                name = cls._normalize_key(key)
                cls._data[name] = cls._normalize_path(cls._cast(value))

        # ── Step 4: compute derived absolute paths ───────────────────────
        #
        # These keys are NOT written in any INI file; they are composed from
        # the project root (base_dir) + a relative directory key.
        #
        # Convention: ABS_DIR_WSZANAMNESE is the project root directory.
        abs_wsz = str(base_dir)
        cls._data['ABS_DIR_WSZANAMNESE'] = abs_wsz

        # ABS_DIR_CLIENT = ABS_DIR_WSZANAMNESE / REL_DIR_CLIENT
        if 'REL_DIR_CLIENT' in cls._data:
            cls._data['ABS_DIR_CLIENT'] = str(base_dir / cls._data['REL_DIR_CLIENT'])

        # ABS_DIR_PDFS_UNSIGNED = ABS_DIR_WSZANAMNESE / REL_DIR_PDFS_UNSIGNED
        if 'REL_DIR_PDFS_UNSIGNED' in cls._data:
            cls._data['ABS_DIR_PDFS_UNSIGNED'] = str(base_dir / cls._data['REL_DIR_PDFS_UNSIGNED'])

        # ABS_DIR_PDF_VORLAGEN = ABS_DIR_WSZANAMNESE / REL_DIR_PDF_VORLAGEN
        if 'REL_DIR_PDF_VORLAGEN' in cls._data:
            cls._data['ABS_DIR_PDF_VORLAGEN'] = str(base_dir / cls._data['REL_DIR_PDF_VORLAGEN'])

        # ABS_DIR_MANIFEST: explicit ini value takes precedence over derived
        if 'ABS_DIR_MANIFEST' not in cls._data:
            rel_dir_manifest = cls._data.get('REL_DIR_MANIFEST', '')
            if rel_dir_manifest:
                cls._data['ABS_DIR_MANIFEST'] = str(base_dir / rel_dir_manifest)
            else:
                cls._data['ABS_DIR_MANIFEST'] = abs_wsz

        # ABS_FILENAME_MANIFEST = ABS_DIR_MANIFEST / FILENAME_MANIFEST
        if 'ABS_FILENAME_MANIFEST' not in cls._data:
            filename_manifest = cls._data.get('FILENAME_MANIFEST', '')
            if filename_manifest:
                cls._data['ABS_FILENAME_MANIFEST'] = str(
                    Path(cls._data['ABS_DIR_MANIFEST']) / filename_manifest
                )

        cls._loaded = True

    @classmethod
    def _detect_os(cls) -> str:
        return "Windows" if platform.system().lower().startswith("win") else "Linux"

    @classmethod
    def _normalize_key(cls, key: str) -> str:
        return key.strip().upper()

    @classmethod
    def _cast(cls, value: str):
        v = value.strip().strip("\"'")
        if v.lower() in ("true", "yes", "on"):
            return True
        if v.lower() in ("false", "no", "off"):
            return False
        
        # Check if it's a valid integer without throwing exception
        if v.isdigit() or (v.startswith('-') and v[1:].isdigit()):
            return int(v)
        
        # Check if it's a valid float without throwing exception
        if '.' in v:
            parts = v.split('.')
            if len(parts) == 2:
                before, after = parts
                if (before.isdigit() or (before.startswith('-') and before[1:].isdigit()) or before == '') and after.isdigit():
                    try:
                        return float(v)
                    except ValueError:
                        pass
        
        # Return as string if not a number
        return v

    @classmethod
    def _normalize_path(cls, value):
        if not isinstance(value, str):
            return value
        return str(Path(value))

    @classmethod
    def get_runtime_attrs(cls):
        """Get all runtime attributes that were set dynamically."""
        ini_keys = set()
        
        # Load to get all ini file keys first
        cls._load()
        
        # Get standard ini keys by loading a fresh parser (mirrors _load Step 1+2)
        base_dir = Path(__file__).parent.parent
        parser = cls._load_and_merge_ini_files(base_dir, mandatory=False)

        # Also merge client dir keys
        rel_dir_client = None
        for section in parser.sections():
            if parser.has_option(section, 'REL_DIR_CLIENT'):
                rel_dir_client = parser.get(section, 'REL_DIR_CLIENT').strip()
                break
        if not rel_dir_client and 'REL_DIR_CLIENT' in parser.defaults():
            rel_dir_client = parser.defaults()['REL_DIR_CLIENT'].strip()
        if not rel_dir_client and (base_dir / 'client').is_dir():
            rel_dir_client = 'client'
        if rel_dir_client:
            client_dir = base_dir / rel_dir_client
            if client_dir.is_dir():
                client_parser = cls._load_and_merge_ini_files(client_dir, mandatory=False)
                for section in client_parser.sections():
                    for key, value in client_parser.items(section):
                        ini_keys.add(cls._normalize_key(key))
                for key, value in client_parser.defaults().items():
                    ini_keys.add(cls._normalize_key(key))

        # Collect all ini keys from root
        for section in parser.sections():
            for key, value in parser.items(section):
                ini_keys.add(cls._normalize_key(key))
        for key, value in parser.defaults().items():
            ini_keys.add(cls._normalize_key(key))
        
        # Runtime attrs are those in _data but not from ini files
        return {k: v for k, v in cls._data.items() if k not in ini_keys}


# ═══════════════════════════════════════════════════════════════════════════════
# CLI: --export-bash
# ═══════════════════════════════════════════════════════════════════════════════

def _shell_escape(value):
    """Return a single-quoted shell-safe representation of a value."""
    if isinstance(value, bool):
        return 'true' if value else 'false'
    if isinstance(value, (int, float)):
        return str(value)
    # Single-quote the string, escaping embedded single quotes
    s = str(value).replace("'", "'\\''")
    return f"'{s}'"


def export_bash():
    """Print all Config keys as KEY=VALUE pairs, safe for bash `eval`."""
    Config._load()
    for key, value in sorted(Config._data.items()):
        print(f"{key}={_shell_escape(value)}")


if __name__ == '__main__':
    import sys
    if '--export-bash' in sys.argv:
        export_bash()
    else:
        print("Usage: python3 config.py --export-bash", file=sys.stderr)
        print("  Outputs all config keys as shell-safe KEY=VALUE pairs.", file=sys.stderr)
        sys.exit(1)