import os
import json
import subprocess
import threading
import zipfile
import io
import tkinter as tk
from tkinter import messagebox, scrolledtext
import psutil
import requests
import minecraft_launcher_lib as mll

# --- Configurações ---
GELUGA_DIR = os.path.join(os.getenv('APPDATA'), '.geluga')
VERSIONS_DIR = os.path.join(GELUGA_DIR, 'versions')
MODS_DIR = os.path.join(GELUGA_DIR, 'mods')
JAVA_DIR = os.path.join(GELUGA_DIR, 'java')
MANIFEST_LOCAL = os.path.join(GELUGA_DIR, 'installed_mods.json')

MC_VERSION = "1.21.1"
NEOFORGE_VERSION = "21.1.235"
NEOFORGE_ID = f"{MC_VERSION}-neoforge-{NEOFORGE_VERSION}"

# Garantir pastas
for p in [GELUGA_DIR, VERSIONS_DIR, MODS_DIR, JAVA_DIR]:
    os.makedirs(p, exist_ok=True)

class GelugaLauncher:
    def __init__(self, root):
        self.root = root
        self.root.title("Geluga Launcher")
        self.root.geometry("450x500")

        tk.Label(root, text="Nome de Usuário:").pack(pady=5)
        self.entry_user = tk.Entry(root, width=40)
        self.entry_user.pack()

        self.btn_run = tk.Button(root, text="Verificar e Jogar", command=self.start_thread, bg="#dddddd")
        self.btn_run.pack(pady=10)

        self.btn_folder = tk.Button(root, text="Abrir Pasta .geluga", command=lambda: os.startfile(GELUGA_DIR))
        self.btn_folder.pack(pady=5)

        tk.Label(root, text="Console Log:").pack(pady=(10, 0))
        self.log_widget = scrolledtext.ScrolledText(root, height=15, width=55, state='disabled')
        self.log_widget.pack(pady=5, padx=10)

    def log(self, message):
        """Atualização segura de log usando a thread principal do tkinter"""
        self.root.after(0, self._insert_log, message)

    def _insert_log(self, message):
        self.log_widget.config(state='normal')
        self.log_widget.insert(tk.END, f"[LOG] {message}\n")
        self.log_widget.see(tk.END)
        self.log_widget.config(state='disabled')

    def install_java(self):
        self.log("Baixando Java 21 (Temurin)...")
        api_url = "https://api.adoptium.net/v3/assets/latest/21/hotspot?architecture=x64&image_type=jre&os=windows"
        res = requests.get(api_url).json()
        download_url = res[0]['binary']['package']['link']
        
        r = requests.get(download_url, stream=True)
        with zipfile.ZipFile(io.BytesIO(r.content)) as z:
            z.extractall(JAVA_DIR)
        self.log("Java instalado com sucesso.")

    def get_java_path(self):
        for root, dirs, files in os.walk(JAVA_DIR):
            if "java.exe" in files: return os.path.join(root, "java.exe")
        return None

    def install_neoforge(self, java_path):
        self.log("Baixando instalador do NeoForge...")
        installer_url = f"https://maven.neoforged.net/net/neoforged/neoforge/{NEOFORGE_VERSION}/neoforge-{NEOFORGE_VERSION}-installer.jar"
        installer_path = os.path.join(GELUGA_DIR, "neoforge_installer.jar")
        
        # Download com validação
        response = requests.get(installer_url, stream=True)
        with open(installer_path, "wb") as f:
            for chunk in response.iter_content(chunk_size=8192):
                f.write(chunk)
        
        if os.path.getsize(installer_path) < 1000000:
            os.remove(installer_path)
            raise Exception("Erro: Instalador do NeoForge corrompido.")

        self.log("Iniciando instalação do NeoForge (Aguarde)...")
        # Executar instalador em modo headless
        cmd = [java_path, "-jar", installer_path, "--installClient", GELUGA_DIR]
        process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, cwd=GELUGA_DIR)
        
        for line in iter(process.stdout.readline, ''):
            if line: self.log(f"NF: {line.strip()}")
        
        process.wait()
        os.remove(installer_path)
        self.log("NeoForge instalado.")

    def sync_mods(self):
        self.log("Sincronizando mods...")
        url = "https://raw.githubusercontent.com/tsukum0/geluga/main/build/mizera_edition/manifest.json"
        try:
            remote_manifest = requests.get(url).json()['mods']
        except:
            self.log("Erro ao buscar manifesto GitHub.")
            return

        local_mods = {}
        if os.path.exists(MANIFEST_LOCAL):
            with open(MANIFEST_LOCAL, 'r') as f: local_mods = json.load(f)

        # Remover mods antigos
        for mod_slug in list(local_mods.keys()):
            if mod_slug not in remote_manifest:
                if os.path.exists(local_mods[mod_slug]): 
                    os.remove(local_mods[mod_slug])
                    self.log(f"Removido: {mod_slug}")
                del local_mods[mod_slug]

        # Baixar novos
        for slug in remote_manifest:
            if slug not in local_mods:
                self.log(f"Baixando: {slug}...")
                api_url = f"https://api.modrinth.com/v2/project/{slug}/version?loaders=[%22neoforge%22]&game_versions=[%221.21.1%22]"
                res = requests.get(api_url).json()
                if res:
                    download_url = res[0]['files'][0]['url']
                    filename = os.path.join(MODS_DIR, f"{slug}.jar")
                    with open(filename, 'wb') as f: f.write(requests.get(download_url).content)
                    local_mods[slug] = filename
        
        with open(MANIFEST_LOCAL, 'w') as f: json.dump(local_mods, f)
        self.log("Mods sincronizados.")

    def start_thread(self):
        threading.Thread(target=self.run_process, daemon=True).start()

    def run_process(self):
        username = self.entry_user.get()
        if not username: 
            self.log("Erro: Digite um usuário.")
            return

        try:
            # 1. Java
            java_path = self.get_java_path()
            if not java_path:
                self.install_java()
                java_path = self.get_java_path()

            # 2. Base MC
            self.log("Verificando versão base...")
            mll.install.install_minecraft_version(MC_VERSION, GELUGA_DIR)
            
            # 3. NeoForge
            if not os.path.exists(os.path.join(VERSIONS_DIR, NEOFORGE_ID)):
                self.install_neoforge(java_path)
            
            # 4. Mods
            self.sync_mods()

            # 5. Launch
            self.log("Lançando jogo...")
            ram_mb = psutil.virtual_memory().total // 1024 // 1024 // 2
            
            options = {
                "username": username,
                "jvmArguments": [f"-Xmx{ram_mb}M"],
                "executablePath": java_path
            }
            
            cmd = mll.command.get_minecraft_command(NEOFORGE_ID, GELUGA_DIR, options)
            subprocess.Popen(cmd, cwd=GELUGA_DIR)
            self.log("Sucesso! O jogo deve abrir em instantes.")
            
        except Exception as e:
            self.log(f"CRÍTICO: {str(e)}")

if __name__ == "__main__":
    root = tk.Tk()
    GelugaLauncher(root)
    root.mainloop()
