from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Optional, Tuple
from urllib.parse import quote

import requests

import core  # reaproveita instalação de Java/Minecraft/NeoForge, perfil offline, etc.


# ============================================================================
# CONFIGURAÇÃO
# ============================================================================

APP_NAME = "GeLauncher Mizera Edition"
APP_VERSION = "1.0"

# Nome de instância PRÓPRIO da edição lite — não mistura mods com a edição
# completa (core.SERVER_VERSION_NAME), mas continua usando o mesmo Minecraft/
# Java/NeoForge já baixados em .geluga/ se o usuário já tiver a edição completa.
SERVER_VERSION_NAME = "geluga-mizera 1.21.1"

# --- Pastas do repositório GitHub usadas por esta edição (mesmo repo do core.py) ---
MODS_REPO_PATH = "build/mizera_edition/mods"        # <- ajuste aqui se o nome real for outro
CONFIG_REPO_PATH = "build/mizera_edition/config"    # <- ajuste aqui se o nome real for outro

_GITHUB_TREE_URL = (
    f"https://api.github.com/repos/{core.GITHUB_USER}/{core.GITHUB_REPO}"
    f"/git/trees/{core.GITHUB_BRANCH}?recursive=1"
)
_REQUEST_TIMEOUT = 15

# --- RAM padrão (a edição lite não expõe esse ajuste na interface) ---
DEFAULT_RAM_MIN_GB = 2
DEFAULT_RAM_MAX_GB = 4

# --- Pastas locais (reaproveita a mesma raiz .geluga/ da edição completa) ---
INSTANCE_DIR = core.MINECRAFT_DIR / "versions" / SERVER_VERSION_NAME
MODS_DIR = INSTANCE_DIR / "mods"

_STATE_DIR = core.CONFIG_DIR
_MODS_MANIFEST_FILE = _STATE_DIR / "mizera_mods_manifest.json"
_SETTINGS_FILE = _STATE_DIR / "mizera_settings.json"


def ensure_directories() -> None:
    for directory in (INSTANCE_DIR, MODS_DIR, _STATE_DIR):
        directory.mkdir(parents=True, exist_ok=True)


ensure_directories()


# ============================================================================
# CONFIGURAÇÕES DO USUÁRIO (só o nome de usuário — edição offline-only)
# ============================================================================

def load_settings() -> dict:
    if _SETTINGS_FILE.exists():
        try:
            return json.loads(_SETTINGS_FILE.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass
    return {"username": ""}


def save_settings(settings: dict) -> None:
    _STATE_DIR.mkdir(parents=True, exist_ok=True)
    _SETTINGS_FILE.write_text(json.dumps(settings, indent=2, ensure_ascii=False), encoding="utf-8")


# ============================================================================
# LEITURA DA ÁRVORE DO REPOSITÓRIO (1 chamada cobre mods + configs)
# ============================================================================

def _fetch_repo_tree() -> list:
    """Baixa a árvore completa de arquivos do repositório via API do Git (1 request)."""
    response = requests.get(_GITHUB_TREE_URL, timeout=_REQUEST_TIMEOUT)
    response.raise_for_status()
    data = response.json()
    if data.get("truncated"):
        core.bus.log(
            "Aviso: a árvore do repositório é grande demais e foi truncada pela API do GitHub.",
            level="warning",
        )
    return [item for item in data.get("tree", []) if item.get("type") == "blob"]


def _entries_under(tree: list, prefix: str) -> dict:
    """Filtra a árvore para os arquivos dentro de `prefix/`, devolvendo
    {caminho_relativo: sha_do_blob}."""
    prefix = prefix.strip("/") + "/"
    entries: dict = {}
    for item in tree:
        path = item.get("path", "")
        if path.startswith(prefix):
            relative = path[len(prefix):]
            if relative:
                entries[relative] = item.get("sha")
    return entries


def _raw_url(repo_prefix: str, relative_path: str) -> str:
    return f"{core.GITHUB_RAW_BASE}/{repo_prefix.strip('/')}/{quote(relative_path, safe='/')}"


def _load_manifest(path: Path) -> dict:
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass
    return {}


def _save_manifest(path: Path, data: dict) -> None:
    _STATE_DIR.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


# ============================================================================
# SINCRONIZAÇÃO DOS MODS (espelha a pasta do GitHub — igual/removido é corrigido)
# ============================================================================

def sync_mods(tree: Optional[list] = None) -> None:
    """Espelha MODS_REPO_PATH -> MODS_DIR: baixa o que mudou (comparando o sha
    do blob do Git) e apaga localmente o que saiu da pasta do repositório."""
    if tree is None:
        tree = _fetch_repo_tree()

    remote_entries = _entries_under(tree, MODS_REPO_PATH)
    if not remote_entries:
        core.bus.log(f"Nenhum mod encontrado em '{MODS_REPO_PATH}' no repositório.", level="warning")
        return

    MODS_DIR.mkdir(parents=True, exist_ok=True)
    local_manifest = _load_manifest(_MODS_MANIFEST_FILE)

    total = len(remote_entries)
    updated = 0
    for index, (relative_path, sha) in enumerate(sorted(remote_entries.items()), start=1):
        local_path = MODS_DIR / relative_path
        needs_download = not local_path.exists() or local_manifest.get(relative_path) != sha
        core.bus.progress(status=f"Mods: {relative_path}", current=index, maximum=total)
        if needs_download:
            core.bus.log(f"Baixando mod: {relative_path}")
            core.download_file(_raw_url(MODS_REPO_PATH, relative_path), local_path)
            updated += 1

    removed = 0
    for relative_path in local_manifest:
        if relative_path not in remote_entries:
            stale_path = MODS_DIR / relative_path
            if stale_path.exists():
                stale_path.unlink(missing_ok=True)
            removed += 1

    _save_manifest(_MODS_MANIFEST_FILE, remote_entries)
    core.bus.log(
        f"Mods sincronizados: {updated} atualizado(s), {removed} removido(s), {total} no total.",
        level="success",
    )


# ============================================================================
# CONFIGURAÇÕES PRÉ-PRONTAS (instaladas uma vez só, sem sobrescrever ajustes do jogador)
# ============================================================================

def install_missing_configs(tree: Optional[list] = None) -> None:
    """Copia CONFIG_REPO_PATH -> pasta da instância, mas só os arquivos que
    ainda não existem localmente. Nunca sobrescreve nem apaga nada — é só um
    "preset" inicial (options.txt, config/ de mods, etc.), então depois da
    primeira vez o jogador é livre para alterar sem o launcher resetar."""
    if tree is None:
        tree = _fetch_repo_tree()

    remote_entries = _entries_under(tree, CONFIG_REPO_PATH)
    if not remote_entries:
        core.bus.log(f"Nenhuma configuração encontrada em '{CONFIG_REPO_PATH}' no repositório.", level="warning")
        return

    INSTANCE_DIR.mkdir(parents=True, exist_ok=True)
    installed = 0
    for relative_path in sorted(remote_entries):
        local_path = INSTANCE_DIR / relative_path
        if local_path.exists():
            continue
        core.bus.log(f"Instalando configuração: {relative_path}")
        core.download_file(_raw_url(CONFIG_REPO_PATH, relative_path), local_path)
        installed += 1

    if installed:
        core.bus.log(f"Configurações pré-prontas instaladas: {installed} arquivo(s) novo(s).", level="success")
    else:
        core.bus.log("Configurações pré-prontas já estavam instaladas.")


def sync_mods_and_configs() -> None:
    """Busca a árvore do repositório uma única vez e sincroniza mods + configs."""
    core.bus.log("Consultando repositório no GitHub...")
    tree = _fetch_repo_tree()
    sync_mods(tree=tree)
    install_missing_configs(tree=tree)


# ============================================================================
# INSTALAÇÃO (Java + Minecraft + NeoForge) — reaproveita o core.py original
# ============================================================================

def _setup_mizera_version(base_version_id: str) -> str:
    """Copia o .json/.jar da versão base do NeoForge para a instância própria
    da edição Mizera (mesma ideia de core.setup_server_version, outro destino)."""
    source_dir = core.MINECRAFT_DIR / "versions" / base_version_id
    INSTANCE_DIR.mkdir(parents=True, exist_ok=True)

    source_json = source_dir / f"{base_version_id}.json"
    target_json = INSTANCE_DIR / f"{SERVER_VERSION_NAME}.json"
    if source_json.exists():
        data = json.loads(source_json.read_text(encoding="utf-8"))
        data["id"] = SERVER_VERSION_NAME
        target_json.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")

    source_jar = source_dir / f"{base_version_id}.jar"
    target_jar = INSTANCE_DIR / f"{SERVER_VERSION_NAME}.jar"
    if source_jar.exists() and not target_jar.exists():
        shutil.copy2(source_jar, target_jar)

    return SERVER_VERSION_NAME


def full_setup() -> Tuple[str, Optional[str]]:
    """Instala Minecraft + Java + NeoForge (via core.py, idempotente) e prepara
    a instância da edição Mizera, sem tocar na instância da edição completa."""
    core.install_minecraft(core.MINECRAFT_VERSION)
    java_path = core.ensure_java(core.MINECRAFT_VERSION)
    core.install_neoforge(core.MINECRAFT_VERSION, core.NEOFORGE_VERSION, java_path=java_path)
    base_id = core.get_neoforge_version_id(core.MINECRAFT_VERSION, core.NEOFORGE_VERSION)
    version_id = _setup_mizera_version(base_id)
    return version_id, java_path


# ============================================================================
# EXECUÇÃO DO JOGO
# ============================================================================

def build_and_launch(profile: "core.Profile", java_path: Optional[str]):
    cmd = core.build_command(
        version_id=SERVER_VERSION_NAME,
        profile=profile,
        ram_min_gb=DEFAULT_RAM_MIN_GB,
        ram_max_gb=DEFAULT_RAM_MAX_GB,
        java_path=java_path,
    )
    return core.launch_game(cmd, version_id=SERVER_VERSION_NAME)
