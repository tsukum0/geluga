from __future__ import annotations

import hashlib
import http.server
import json
import os
import queue
import re
import shutil
import socketserver
import subprocess
import sys
import threading
import time
import uuid as uuid_lib
import webbrowser
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable, Optional, Tuple

import requests
import minecraft_launcher_lib as mll


# ============================================================================
# CONFIGURAÇÃO
# ============================================================================

APP_NAME = "Geluga Launcher"
APP_VERSION = "2.5"

MINECRAFT_VERSION = "1.21.1"
NEOFORGE_VERSION = "21.1.235"
SERVER_VERSION_NAME = "geluga 1.21.1 (2.5)"
REQUIRED_JAVA_MAJOR = 21

# --- Repositório de mods (GitHub - Apenas Manifesto) ---
GITHUB_USER = "tsukum0"
GITHUB_REPO = "geluga"
GITHUB_BRANCH = "main"
GITHUB_RAW_BASE = f"https://raw.githubusercontent.com/{GITHUB_USER}/{GITHUB_REPO}/{GITHUB_BRANCH}"
MANIFEST_URL = f"{GITHUB_RAW_BASE}/manifest.json"
VERSION_URL = f"{GITHUB_RAW_BASE}/version.txt"

# --- Imagens da comunidade (GitHub) ---
COMMUNITY_MANIFEST_URL = f"{GITHUB_RAW_BASE}/community.json"
COMMUNITY_BASE_URL = f"{GITHUB_RAW_BASE}/community"
DISCORD_INVITE_URL = "https://discord.gg/U8M8qmDXnK"

# --- API do Modrinth ---
MODRINTH_API_BASE = "https://api.modrinth.com/v2"
MODRINTH_LOADER = "neoforge"

# --- Login Microsoft ---
MS_CLIENT_ID = "COLOQUE_AQUI_O_CLIENT_ID_DO_SEU_AZURE_APP"
MS_REDIRECT_PORT = 3003
MS_REDIRECT_URI = f"http://localhost:{MS_REDIRECT_PORT}/auth"


def _base_data_dir() -> Path:
    """Pasta base de dados de aplicativos do usuário, de acordo com o SO atual."""
    if sys.platform == "win32":
        base = os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
    elif sys.platform == "darwin":
        base = str(Path.home() / "Library" / "Application Support")
    else:
        base = os.environ.get("XDG_DATA_HOME") or str(Path.home() / ".local" / "share")
    return Path(base)


# Estrutura de pastas:
# - MINECRAFT_DIR (.geluga/): armazena assets, libraries e runtimes compartilhados.
# - INSTANCE_DIR (.geluga/versions/geluga 1.21.1 (2.5)/): pasta da instância com mods, shaders e saves.
APP_ROOT = _base_data_dir() / ".geluga"
MINECRAFT_DIR = APP_ROOT
INSTANCE_DIR = APP_ROOT / "versions" / SERVER_VERSION_NAME

CONFIG_DIR = APP_ROOT / "config"
MODS_DIR = INSTANCE_DIR / "mods"
SHADERPACKS_DIR = INSTANCE_DIR / "shaderpacks"
LOGS_DIR = APP_ROOT / "logs"

SETTINGS_FILE = CONFIG_DIR / "settings.json"
LOCAL_MODS_VERSION_FILE = CONFIG_DIR / "geluga.txt"
MANAGED_MODS_FILE = CONFIG_DIR / "managed_mods.json"
LOG_FILE = LOGS_DIR / "launcher.log"
IMAGE_CACHE_DIR = APP_ROOT / "cache" / "images"


def ensure_directories() -> None:
    """Garante que toda a árvore de pastas da instância e do launcher exista."""
    for directory in (APP_ROOT, INSTANCE_DIR, CONFIG_DIR, MODS_DIR, SHADERPACKS_DIR, LOGS_DIR):
        directory.mkdir(parents=True, exist_ok=True)


ensure_directories()


# ============================================================================
# MODELOS
# ============================================================================

@dataclass
class Profile:
    username: str
    uuid: str
    access_token: str
    user_type: str = "offline"


# ============================================================================
# UTILITÁRIOS
# ============================================================================

def sha1_of_file(path: Path) -> str:
    digest = hashlib.sha1()
    with open(path, "rb") as file_obj:
        for chunk in iter(lambda: file_obj.read(8192), b""):
            digest.update(chunk)
    return digest.hexdigest()


def download_file(url: str, destination: Path, chunk_size: int = 8192) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = destination.with_name(destination.name + ".part")
    with requests.get(url, stream=True, timeout=30) as response:
        response.raise_for_status()
        with open(tmp_path, "wb") as file_obj:
            for chunk in response.iter_content(chunk_size=chunk_size):
                if chunk:
                    file_obj.write(chunk)
    tmp_path.replace(destination)


def human_size(num_bytes: float) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if num_bytes < 1024:
            return f"{num_bytes:.1f}{unit}"
        num_bytes /= 1024
    return f"{num_bytes:.1f}TB"


# ============================================================================
# EVENTOS / LOG
# ============================================================================

@dataclass
class LogEvent:
    text: str
    level: str = "info"


@dataclass
class ProgressEvent:
    status: Optional[str] = None
    current: Optional[int] = None
    maximum: Optional[int] = None


class EventBus:
    def __init__(self) -> None:
        self._queue: queue.Queue = queue.Queue()

    def log(self, text: str, level: str = "info") -> None:
        self._queue.put(LogEvent(text=text, level=level))

    def progress(
        self,
        status: Optional[str] = None,
        current: Optional[int] = None,
        maximum: Optional[int] = None,
    ) -> None:
        self._queue.put(ProgressEvent(status=status, current=current, maximum=maximum))

    def drain(self) -> list:
        events: list = []
        while True:
            try:
                events.append(self._queue.get_nowait())
            except queue.Empty:
                break
        return events


bus = EventBus()


# ============================================================================
# CONFIGURAÇÕES DO USUÁRIO
# ============================================================================

DEFAULT_SETTINGS = {
    "auth_mode": "offline",
    "username": "Player",
    "ram_min_gb": 2,
    "ram_max_gb": 4,
    "appearance": "dark",
    "close_launcher_on_play": False,
    "ms_account": None,
}


def load_settings() -> dict:
    if SETTINGS_FILE.exists():
        try:
            data = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
            return {**DEFAULT_SETTINGS, **data}
        except (json.JSONDecodeError, OSError):
            pass
    return dict(DEFAULT_SETTINGS)


def save_settings(settings: dict) -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    SETTINGS_FILE.write_text(json.dumps(settings, indent=2, ensure_ascii=False), encoding="utf-8")


# ============================================================================
# INSTALAÇÃO DO MINECRAFT E DO NEOFORGE
# ============================================================================

def _callback(prefix: str = "") -> dict:
    def set_status(text: str) -> None:
        bus.log(f"{prefix}{text}")
        bus.progress(status=f"{prefix}{text}")

    def set_progress(value: int) -> None:
        bus.progress(current=value)

    def set_max(value: int) -> None:
        bus.progress(maximum=value)

    return {"setStatus": set_status, "setProgress": set_progress, "setMax": set_max}


def get_installed_versions() -> list:
    """Lista todas as versões válidas encontradas na pasta .geluga/versions/."""
    versions_dir = MINECRAFT_DIR / "versions"
    if not versions_dir.exists():
        return [SERVER_VERSION_NAME]
    
    installed = []
    for p in versions_dir.iterdir():
        # Verifica se é uma pasta e se dentro dela existe o arquivo JSON da versão
        if p.is_dir() and (p / f"{p.name}.json").exists():
            installed.append(p.name)
            
    # Garante que a versão oficial do servidor sempre esteja na lista e no topo
    if SERVER_VERSION_NAME in installed:
        installed.remove(SERVER_VERSION_NAME)
    installed.insert(0, SERVER_VERSION_NAME)
    
    return installed

def is_minecraft_installed(version: str = MINECRAFT_VERSION) -> bool:
    try:
        installed = mll.utils.get_installed_versions(str(MINECRAFT_DIR))
    except Exception:
        return False
    return any(item.get("id") == version for item in installed)


def get_neoforge_version_id(
    mc_version: str = MINECRAFT_VERSION, loader_version: str = NEOFORGE_VERSION
) -> str:
    neoforge = mll.mod_loader.get_mod_loader("neoforge")
    return neoforge.get_installed_version(mc_version, loader_version)


def is_neoforge_installed(
    mc_version: str = MINECRAFT_VERSION, loader_version: str = NEOFORGE_VERSION
) -> bool:
    try:
        installed = mll.utils.get_installed_versions(str(MINECRAFT_DIR))
    except Exception:
        return False
    expected_id = get_neoforge_version_id(mc_version, loader_version)
    return any(item.get("id") in (expected_id, SERVER_VERSION_NAME) for item in installed)


def install_minecraft(version: str = MINECRAFT_VERSION) -> None:
    bus.log(f"Verificando Minecraft {version}...")
    mll.install.install_minecraft_version(version, str(MINECRAFT_DIR), callback=_callback())
    bus.log(f"Minecraft {version} verificado/instalado.", level="success")


def install_neoforge(
    mc_version: str = MINECRAFT_VERSION,
    loader_version: str = NEOFORGE_VERSION,
    java_path: Optional[str] = None,
) -> None:
    neoforge = mll.mod_loader.get_mod_loader("neoforge")
    if not neoforge.is_minecraft_version_supported(mc_version):
        raise RuntimeError(f"O NeoForge não tem suporte à versão {mc_version} do Minecraft.")
    bus.log(f"Verificando NeoForge {loader_version} (Minecraft {mc_version})...")
    neoforge.install(
        mc_version,
        str(MINECRAFT_DIR),
        loader_version=loader_version,
        callback=_callback(),
        java=java_path,
    )
    bus.log(f"NeoForge {loader_version} verificado/instalado.", level="success")


def ensure_java(mc_version: str = MINECRAFT_VERSION) -> Optional[str]:
    try:
        info = mll.runtime.get_version_runtime_information(mc_version, str(MINECRAFT_DIR))
    except Exception:
        info = None
    if not info:
        bus.log(
            "Não foi possível identificar o runtime Java necessário; usando o 'java' do "
            f"sistema (é preciso ter o Java {REQUIRED_JAVA_MAJOR}+ instalado).",
            level="warning",
        )
        return None
    runtime_name = info.get("name")
    java_major = info.get("javaMajorVersion")
    bus.log(f"Este Minecraft requer Java {java_major} (runtime '{runtime_name}').")
    try:
        mll.runtime.install_jvm_runtime(runtime_name, str(MINECRAFT_DIR), callback=_callback("[Java] "))
    except Exception as exc:
        bus.log(f"Falha ao baixar o runtime Java embutido ({exc}); usando 'java' do sistema.", level="warning")
        return None
    executable_path = mll.runtime.get_executable_path(runtime_name, str(MINECRAFT_DIR))
    if executable_path:
        bus.log(f"Java {java_major} pronto.", level="success")
    return executable_path


def setup_server_version(base_version_id: str) -> str:
    """Cria/atualiza a versão customizada do servidor sob o nome configurado em SERVER_VERSION_NAME."""
    source_dir = MINECRAFT_DIR / "versions" / base_version_id
    target_dir = MINECRAFT_DIR / "versions" / SERVER_VERSION_NAME
    target_dir.mkdir(parents=True, exist_ok=True)

    source_json = source_dir / f"{base_version_id}.json"
    target_json = target_dir / f"{SERVER_VERSION_NAME}.json"
    if source_json.exists():
        data = json.loads(source_json.read_text(encoding="utf-8"))
        data["id"] = SERVER_VERSION_NAME
        target_json.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")

    source_jar = source_dir / f"{base_version_id}.jar"
    target_jar = target_dir / f"{SERVER_VERSION_NAME}.jar"
    if source_jar.exists() and not target_jar.exists():
        shutil.copy2(source_jar, target_jar)

    return SERVER_VERSION_NAME


def full_setup() -> Tuple[str, Optional[str]]:
    install_minecraft(MINECRAFT_VERSION)
    java_path = ensure_java(MINECRAFT_VERSION)
    install_neoforge(MINECRAFT_VERSION, NEOFORGE_VERSION, java_path=java_path)
    base_id = get_neoforge_version_id(MINECRAFT_VERSION, NEOFORGE_VERSION)
    version_id = setup_server_version(base_id)
    return version_id, java_path


# ============================================================================
# GERENCIAMENTO DE MODS (GitHub Manifest -> API Modrinth)
# ============================================================================

_REQUEST_TIMEOUT = 15


def get_remote_version() -> str:
    response = requests.get(VERSION_URL, timeout=_REQUEST_TIMEOUT)
    response.raise_for_status()
    return response.text.strip()


def get_local_version() -> Optional[str]:
    if LOCAL_MODS_VERSION_FILE.exists():
        text = LOCAL_MODS_VERSION_FILE.read_text(encoding="utf-8").strip()
        return text or None
    return None


def _write_local_version(version: str) -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    LOCAL_MODS_VERSION_FILE.write_text(version, encoding="utf-8")


def get_manifest() -> dict:
    response = requests.get(MANIFEST_URL, timeout=_REQUEST_TIMEOUT)
    response.raise_for_status()
    return response.json()


def _load_managed_mods() -> set:
    if MANAGED_MODS_FILE.exists():
        try:
            return set(json.loads(MANAGED_MODS_FILE.read_text(encoding="utf-8")))
        except (json.JSONDecodeError, OSError):
            pass
    return set()


def _save_managed_mods(names) -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    MANAGED_MODS_FILE.write_text(json.dumps(sorted(names), ensure_ascii=False), encoding="utf-8")


def list_installed_mods() -> list:
    if not MODS_DIR.exists():
        return []
    return sorted(path.name for path in MODS_DIR.glob("*.jar"))


def list_installed_shaderpacks() -> list:
    if not SHADERPACKS_DIR.exists():
        return []
    return sorted(path.name for path in SHADERPACKS_DIR.glob("*.zip"))


def cache_remote_image(url: str) -> Optional[Path]:
    if not url:
        return None
    digest = hashlib.sha1(url.encode("utf-8")).hexdigest()[:16]
    ext = os.path.splitext(url.split("?")[0])[1] or ".png"
    local_path = IMAGE_CACHE_DIR / f"{digest}{ext}"
    if not local_path.exists():
        try:
            download_file(url, local_path)
        except requests.RequestException:
            return None
    return local_path


def _manifest_entries(manifest: dict) -> Iterable[dict]:
    """Extrai os identificadores de projetos do Modrinth do manifest.json do GitHub."""
    for entry in manifest.get("mods", []):
        if isinstance(entry, str):
            yield {"project_id": entry.strip(), "filename": None, "sha1": None}
        elif isinstance(entry, dict):
            project_id = (
                entry.get("project_id") or entry.get("id") or
                entry.get("slug") or entry.get("name") or entry.get("file")
            )
            filename = entry.get("file") or entry.get("filename")
            if filename and not str(filename).endswith(".jar"):
                if not project_id:
                    project_id = filename
                filename = None
            if project_id:
                yield {
                    "project_id": str(project_id).strip(),
                    "filename": filename,
                    "sha1": entry.get("sha1")
                }


def has_update_available() -> bool:
    try:
        remote = get_remote_version()
    except requests.RequestException as exc:
        bus.log(f"Não foi possível verificar atualizações de mods: {exc}", level="warning")
        return False
    return get_local_version() != remote


def sync_mods() -> str:
    """Lê o manifesto do GitHub e baixa os mods correspondentes pela API do Modrinth."""
    bus.log("Buscando manifest.json do repositório no GitHub...")
    manifest = get_manifest()
    entries = list(_manifest_entries(manifest))

    MODS_DIR.mkdir(parents=True, exist_ok=True)
    expected_filenames = set()
    total = len(entries)

    for index, entry in enumerate(entries, start=1):
        project_id = entry["project_id"]
        filename = entry["filename"]
        sha1 = entry["sha1"]
        url = None

        local_path = (MODS_DIR / filename) if filename else None
        needs_download = not (local_path and local_path.exists())
        if not needs_download and sha1:
            try:
                needs_download = sha1_of_file(local_path).lower() != sha1.lower()
            except OSError:
                needs_download = True

        if needs_download or not filename:
            bus.progress(status=f"Checando Modrinth: {project_id}...", current=index, maximum=total)
            try:
                info = modrinth_get_download(project_id)
                if info:
                    filename = info["filename"]
                    url = info["url"]
                    if not sha1:
                        sha1 = info.get("sha1")
                    local_path = MODS_DIR / filename
                    needs_download = not local_path.exists()
                    if not needs_download and sha1:
                        try:
                            needs_download = sha1_of_file(local_path).lower() != sha1.lower()
                        except OSError:
                            needs_download = True
                else:
                    bus.log(f"Nenhuma versão compatível no Modrinth para: {project_id}", level="warning")
                    continue
            except Exception as exc:
                bus.log(f"Erro ao consultar Modrinth para {project_id}: {exc}", level="warning")
                continue

        if not filename:
            continue

        expected_filenames.add(filename)
        if needs_download and url:
            bus.log(f"Baixando mod via Modrinth: {filename}")
            bus.progress(status=f"Baixando {filename}", current=index, maximum=total)
            download_file(url, local_path)
        elif not needs_download:
            bus.progress(status=f"OK: {filename}", current=index, maximum=total)

    managed = _load_managed_mods()
    removed = 0
    for jar_path in MODS_DIR.glob("*.jar"):
        if jar_path.name not in expected_filenames and jar_path.name in managed:
            bus.log(f"Removendo mod fora do manifest: {jar_path.name}", level="warning")
            jar_path.unlink(missing_ok=True)
            removed += 1
    _save_managed_mods(expected_filenames)

    version = str(manifest.get("version") or "")
    if not version:
        try:
            version = get_remote_version()
        except requests.RequestException:
            version = ""
    if version:
        _write_local_version(version)

    bus.log(f"Mods sincronizados: {len(expected_filenames)} verificados via Modrinth, {removed} removido(s).", level="success")
    return version


# ============================================================================
# COMUNIDADE E DESCOBERTA DE MODS EXTRAS (Modrinth)
# ============================================================================

def get_community_image_urls(limit: int = 6) -> list:
    response = requests.get(COMMUNITY_MANIFEST_URL, timeout=_REQUEST_TIMEOUT)
    response.raise_for_status()
    manifest = response.json()
    filenames = list(manifest.get("images", []))[-limit:]
    filenames.reverse()
    return [f"{COMMUNITY_BASE_URL}/{name}" for name in filenames]


def modrinth_search_mods(query: str, project_type: str = "mod", limit: int = 20) -> list:
    facets = [[f"project_type:{project_type}"], [f"versions:{MINECRAFT_VERSION}"]]
    if project_type == "mod":
        facets.append([f"categories:{MODRINTH_LOADER}"])
    params = {"query": query, "limit": limit, "facets": json.dumps(facets)}
    response = requests.get(f"{MODRINTH_API_BASE}/search", params=params, timeout=_REQUEST_TIMEOUT)
    response.raise_for_status()
    return response.json().get("hits", [])


def modrinth_get_download(project_id: str, loaders: Optional[list] = None) -> Optional[dict]:
    if loaders is None:
        loaders = [MODRINTH_LOADER]
    params = {"game_versions": json.dumps([MINECRAFT_VERSION])}
    if loaders:
        params["loaders"] = json.dumps(loaders)
    response = requests.get(
        f"{MODRINTH_API_BASE}/project/{project_id}/version", params=params, timeout=_REQUEST_TIMEOUT
    )
    response.raise_for_status()
    versions = response.json()
    if not versions:
        return None
    files = versions[0].get("files") or []
    file_info = next((f for f in files if f.get("primary")), files[0] if files else None)
    if not file_info:
        return None
    return {
        "filename": file_info["filename"],
        "url": file_info["url"],
        "sha1": (file_info.get("hashes") or {}).get("sha1"),
    }


def install_from_modrinth(
    project_id: str, destination_dir: Path = MODS_DIR, loaders: Optional[list] = None
) -> str:
    file_info = modrinth_get_download(project_id, loaders=loaders)
    if not file_info:
        raise RuntimeError("Nenhuma versão compatível encontrada para este item no Modrinth.")
    local_path = destination_dir / file_info["filename"]
    bus.log(f"Baixando do Modrinth: {file_info['filename']}")
    download_file(file_info["url"], local_path)
    bus.log(f"Instalado: {file_info['filename']}", level="success")
    return file_info["filename"]


def uninstall_file(filename: str, directory: Path = MODS_DIR) -> None:
    local_path = directory / filename
    if local_path.exists():
        local_path.unlink()
    if directory == MODS_DIR:
        managed = _load_managed_mods()
        if filename in managed:
            managed.discard(filename)
            _save_managed_mods(managed)


# ============================================================================
# AUTENTICAÇÃO OFFLINE
# ============================================================================

_USERNAME_RE = re.compile(r"^[A-Za-z0-9_]{3,16}$")


def is_valid_username(username: str) -> bool:
    return bool(_USERNAME_RE.match(username or ""))


def offline_uuid(username: str) -> str:
    data = f"OfflinePlayer:{username}".encode("utf-8")
    digest = bytearray(hashlib.md5(data).digest())
    digest[6] = (digest[6] & 0x0F) | 0x30
    digest[8] = (digest[8] & 0x3F) | 0x80
    return str(uuid_lib.UUID(bytes=bytes(digest)))


def build_offline_profile(username: str) -> Profile:
    username = (username or "").strip()
    if not is_valid_username(username):
        raise ValueError("Nome de usuário inválido (use 3-16 caracteres: letras, números ou _).")
    return Profile(
        username=username,
        uuid=offline_uuid(username),
        access_token=uuid_lib.uuid4().hex,
        user_type="offline",
    )


# ============================================================================
# AUTENTICAÇÃO MICROSOFT
# ============================================================================

class AzureAppNotConfigured(Exception):
    pass


_SUCCESS_HTML = """<!doctype html>
<html><head><meta charset="utf-8"><title>Geluga Launcher</title></head>
<body style="font-family: sans-serif; text-align:center; margin-top: 15vh;">
<h2>Login concluído!</h2>
<p>Você já pode fechar esta aba e voltar para o Geluga Launcher.</p>
</body></html>"""


class _CallbackHandler(http.server.BaseHTTPRequestHandler):
    captured_url: Optional[str] = None

    def do_GET(self) -> None:
        type(self).captured_url = self.path
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(_SUCCESS_HTML.encode("utf-8"))

    def log_message(self, format: str, *args) -> None:
        pass


def _wait_for_redirect(timeout: float = 300.0) -> str:
    _CallbackHandler.captured_url = None
    with socketserver.TCPServer(("127.0.0.1", MS_REDIRECT_PORT), _CallbackHandler) as server:
        server.timeout = 1.0
        start = time.monotonic()
        while time.monotonic() - start < timeout:
            server.handle_request()
            if _CallbackHandler.captured_url:
                break
    if not _CallbackHandler.captured_url:
        raise TimeoutError("Tempo esgotado aguardando o login no navegador.")
    return f"http://localhost:{MS_REDIRECT_PORT}{_CallbackHandler.captured_url}"


def login_with_microsoft() -> Tuple[Profile, Optional[str]]:
    if not MS_CLIENT_ID or "COLOQUE_AQUI" in MS_CLIENT_ID:
        raise AzureAppNotConfigured(
            "Nenhum Client ID do Azure foi configurado (core.py -> MS_CLIENT_ID). Veja o README.md."
        )
    bus.log("Abrindo o navegador para login com a conta Microsoft...")
    login_url, state, code_verifier = mll.microsoft_account.get_secure_login_data(
        MS_CLIENT_ID, MS_REDIRECT_URI
    )
    webbrowser.open(login_url)
    bus.log("Aguardando o login ser concluído no navegador...")
    redirect_url = _wait_for_redirect()
    try:
        auth_code = mll.microsoft_account.parse_auth_code_url(redirect_url, state)
    except AssertionError as exc:
        raise RuntimeError("O 'state' retornado não confere; login abortado por segurança.") from exc
    except KeyError as exc:
        raise RuntimeError("A URL de retorno não contém um código de autenticação válido.") from exc

    bus.log("Autenticando com Xbox Live / Minecraft Services...")
    try:
        login_data = mll.microsoft_account.complete_login(
            MS_CLIENT_ID, None, MS_REDIRECT_URI, auth_code, code_verifier
        )
    except Exception as exc:
        if type(exc).__name__ == "AzureAppNotPermitted":
            raise AzureAppNotConfigured(
                "Seu Azure App ainda não tem permissão para usar a API do Minecraft. "
                "Veja a seção de login Microsoft no README.md."
            ) from exc
        raise

    profile = Profile(
        username=login_data["name"],
        uuid=login_data["id"],
        access_token=login_data["access_token"],
        user_type="msa",
    )
    bus.log(f"Login com Microsoft concluído: {profile.username}", level="success")
    return profile, login_data.get("refresh_token")


def refresh_microsoft_login(refresh_token: str) -> Tuple[Profile, Optional[str]]:
    login_data = mll.microsoft_account.complete_refresh(
        MS_CLIENT_ID, None, MS_REDIRECT_URI, refresh_token
    )
    profile = Profile(
        username=login_data["name"],
        uuid=login_data["id"],
        access_token=login_data["access_token"],
        user_type="msa",
    )
    return profile, login_data.get("refresh_token")


# ============================================================================
# EXECUÇÃO DO JOGO
# ============================================================================

def build_command(
    version_id: str,
    profile: Profile,
    ram_min_gb: int,
    ram_max_gb: int,
    java_path: Optional[str] = None,
) -> list:
    # Direciona o diretório do jogo (gameDirectory) para a pasta da versão selecionada!
    instance_path = MINECRAFT_DIR / "versions" / version_id
    instance_path.mkdir(parents=True, exist_ok=True)

    options = {
        "username": profile.username,
        "uuid": profile.uuid,
        "token": profile.access_token,
        "launcherName": APP_NAME,
        "launcherVersion": APP_VERSION,
        "gameDirectory": str(instance_path),
        "jvmArguments": [f"-Xms{ram_min_gb}G", f"-Xmx{ram_max_gb}G"],
    }
    if java_path:
        options["executablePath"] = java_path
    return mll.command.get_minecraft_command(version_id, str(MINECRAFT_DIR), options)


def launch_game(command: list, version_id: str = SERVER_VERSION_NAME) -> subprocess.Popen:
    bus.log(f"Iniciando o Minecraft ({version_id})...")
    
    # O diretório de trabalho (CWD) passa a ser a pasta exata da versão escolhida
    work_dir = MINECRAFT_DIR / "versions" / version_id
    work_dir.mkdir(parents=True, exist_ok=True)
    
    return subprocess.Popen(
        command,
        cwd=str(work_dir),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        bufsize=1,
    )


def stream_output(process: subprocess.Popen, on_exit: Optional[Callable[[int], None]] = None) -> None:
    def reader() -> None:
        if process.stdout is not None:
            for line in process.stdout:
                bus.log(line.rstrip())
        exit_code = process.wait()
        if on_exit:
            on_exit(exit_code)

    threading.Thread(target=reader, daemon=True).start()
