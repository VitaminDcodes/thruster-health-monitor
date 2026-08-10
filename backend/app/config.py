import os
import sys
import yaml
import logging
from typing import Dict, Any

logger = logging.getLogger(__name__)

def get_resource_path(relative_path: str) -> str:
    """
    Get the absolute path to a resource. Resolves relative to the running
    executable directory if frozen, or to the project base root during development.
    """
    if getattr(sys, "frozen", False):
        # Bundled temporary folder created by PyInstaller
        bundled_dir = getattr(sys, "_MEIPASS", None)
        if bundled_dir:
            # First check if the folder exists next to the executable (allowing external modification)
            exe_dir = os.path.dirname(sys.executable)
            external_path = os.path.join(exe_dir, relative_path)
            if os.path.exists(external_path):
                return external_path
            # Otherwise use bundled assets
            return os.path.join(bundled_dir, relative_path)
            
    # Development mode: resolve relative to project root (up 2 levels from config.py)
    base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    return os.path.join(base_dir, relative_path)

def resolve_path(path_str: str) -> str:
    """Resolves absolute or relative paths dynamically."""
    if os.path.isabs(path_str) and os.path.exists(path_str):
        return path_str
    # Convert absolute paths that don't exist (e.g. from developer system) to relative basenames
    if os.path.isabs(path_str):
        # Extract relative parts (e.g., data/thruster_health.db)
        parts = path_str.replace("\\", "/").split("/")
        if "data" in parts:
            idx = parts.index("data")
            path_str = "/".join(parts[idx:])
        elif "config" in parts:
            idx = parts.index("config")
            path_str = "/".join(parts[idx:])
            
    return get_resource_path(path_str)
def load_yaml_config(file_path: str) -> Dict[str, Any]:
    if not os.path.exists(file_path):
        logger.warning(f"Config file not found: {file_path}. Using empty defaults.")
        return {}
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    except Exception as e:
        logger.error(f"Error parsing YAML config at {file_path}: {e}")
        return {}

# Load configurations
CONFIG_DIR = get_resource_path("config")
SYSTEM_CONFIG = load_yaml_config(os.path.join(CONFIG_DIR, "system.yaml"))
HEALTH_CONFIG = load_yaml_config(os.path.join(CONFIG_DIR, "health.yaml"))


def get_system_config() -> Dict[str, Any]:
    return SYSTEM_CONFIG

def get_health_config() -> Dict[str, Any]:
    return HEALTH_CONFIG

