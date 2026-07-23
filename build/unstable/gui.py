from __future__ import annotations

import threading
import traceback
import webbrowser
from typing import Callable, Optional

from PIL import Image

import customtkinter as ctk
import core


# ============================================================================
# TEMA
# ============================================================================

def get_app_theme_config() -> tuple[str, str]:
    """Retorna (nome_do_tema, modo_de_apariencia)."""
    try:
        theme_path = core.APP_ROOT / "themes" / ".theme.txt"
        if not theme_path.exists():
            return "blue", "Dark"
        
        content = theme_path.read_text(encoding="utf-8").strip().split(",")
        if len(content) == 2:
            return content[0].strip(), content[1].strip()
    except Exception:
        pass
    return "blue", "Dark"

def save_theme_config(theme_name: str, mode: str):
    theme_dir = core.APP_ROOT / "themes"
    theme_path = theme_dir / ".theme.txt"
    
    # 1. Garante que o diretório existe
    theme_dir.mkdir(parents=True, exist_ok=True)
    
    # 2. Escreve o conteúdo (usando 'w' garante que o arquivo seja recriado/sobrescrito)
    try:
        theme_path.write_text(f"{theme_name}, {mode}", encoding="utf-8")
    except PermissionError:
        # Se falhar, tenta forçar a remoção antes da escrita (caso o SO esteja travando o handle)
        import os
        if theme_path.exists():
            os.remove(theme_path)
            theme_path.write_text(f"{theme_name}, {mode}", encoding="utf-8")


def any_button_click() -> None:
    print("Botão clicado!")


def load_image(path, size: tuple[int, int]) -> Optional[ctk.CTkImage]:
    """Abre uma imagem local e devolve um CTkImage pronto pra uso, ou None se
    o arquivo não existir/não puder ser lido."""
    if not path:
        return None
    try:
        img_data = Image.open(path).convert("RGBA").copy()
        return ctk.CTkImage(light_image=img_data, dark_image=img_data, size=size)
    except (FileNotFoundError, OSError):
        return None


# ============================================================================
# OBJETOS DA INTERFACE (Construtores de Elementos)
# ============================================================================

class box(ctk.CTkFrame):
    def __init__(self, master, posx=0, posy=0, relx=None, rely=None,
                 sizex=200, sizey=100, relwidth=None, relheight=None,
                 anchor=None, color=None, **kwargs):
        super().__init__(master, width=sizex, height=sizey, fg_color=color, **kwargs)
        self.place(x=posx, y=posy, relx=relx, rely=rely, relwidth=relwidth, relheight=relheight, anchor=anchor)


class Button(ctk.CTkButton):
    def __init__(self, master, text="Button", posx=0, posy=0, relx=None, rely=None,
                 relwidth=None, anchor=None, sizex=120, sizey=40, command=None,
                 color=None, hover_color=None, text_color=None, font_size=14, bold=False, **kwargs):
        if command is None:
            command = any_button_click
        if "fg_color" in kwargs:
            color = kwargs.pop("fg_color")

        weight = "bold" if bold else "normal"
        font = ctk.CTkFont(size=font_size, weight=weight)

        super().__init__(master, text=text, width=sizex, height=sizey, command=command,
                         fg_color=color, hover_color=hover_color, text_color=text_color, font=font, **kwargs)
        self.place(x=posx, y=posy, relx=relx, rely=rely, relwidth=relwidth, anchor=anchor)


class Label(ctk.CTkLabel):
    def __init__(self, master, text="", posx=0, posy=0, relx=None, rely=None,
                 anchor=None, font_size=14, bold=False, text_color=None, justify="center", **kwargs):
        weight = "bold" if bold else "normal"
        font = ctk.CTkFont(size=font_size, weight=weight)

        super().__init__(master, text=text, font=font, text_color=text_color, justify=justify, **kwargs)
        self.place(x=posx, y=posy, relx=relx, rely=rely, anchor=anchor)


class ComboBox(ctk.CTkComboBox):
    def __init__(self, master, values=None, posx=0, posy=0, relx=None, rely=None,
                 anchor=None, sizex=180, **kwargs):
        if values is None:
            values = []
        super().__init__(master, values=values, width=sizex, **kwargs)
        self.place(x=posx, y=posy, relx=relx, rely=rely, anchor=anchor)


class ProgressBar(ctk.CTkProgressBar):
    def __init__(self, master, posx=0, posy=0, relx=None, rely=None, relwidth=None,
                 anchor=None, sizex=300, sizey=8, initial_value=0.0, color=None, progress_color=None, **kwargs):
        if "fg_color" in kwargs:
            color = kwargs.pop("fg_color")

        super().__init__(
            master,
            width=sizex,
            height=sizey,
            fg_color=color,
            progress_color=progress_color,
            **kwargs
        )
        self.place(x=posx, y=posy, relx=relx, rely=rely, relwidth=relwidth, anchor=anchor)
        self.set(initial_value)


class TextBox(ctk.CTkTextbox):
    def __init__(self, master, posx=0, posy=0, relx=None, rely=None,
                 sizex=200, sizey=100, relwidth=None, relheight=None,
                 anchor=None, color=None, corner_radius=0, font_size=12, **kwargs):
        if "fg_color" in kwargs:
            color = kwargs.pop("fg_color")

        font = ctk.CTkFont(family="Consolas", size=font_size)

        super().__init__(master, corner_radius=corner_radius, width=sizex, height=sizey, fg_color=color, font=font, **kwargs)
        self.place(x=posx, y=posy, relx=relx, rely=rely, relwidth=relwidth, relheight=relheight, anchor=anchor)
        self.configure(state="disabled")

    def log(self, mensagem):
        self.configure(state="normal")
        self.insert("end", f"> {mensagem}\n")
        self.see("end")
        self.configure(state="disabled")


# ============================================================================
# APLICAÇÃO (Construção da UI via Objetos Definidos)
# ============================================================================

class App(ctk.CTk):
    def __init__(self) -> None:
        super().__init__()

        self.settings = core.load_settings()
        self.title(core.APP_NAME)
        self.geometry("1200x750")
        self.minsize(1200, 750)

        self._profile: Optional[core.Profile] = None
        self._busy = False

        # --- 1. SIDEBAR ---
        self._build_sidebar()

        # --- 2. ÁREA CENTRAL ---
        self._build_main_area()

        # --- 3. BOTTOMBAR (Controles + Log) ---
        self._build_bottombar()

        self.show_home()
        self._refresh_user_panel()
        self._refresh_installed_list()
        self._load_community_images()

        self._poll_bus()
        self.after(300, self._startup_check)

        # --- Configuração de Tema ---
        theme_name, mode = get_app_theme_config()
        ctk.set_appearance_mode(mode)
        # Dentro do __init__ da classe App


        # Caminho absoluto para o arquivo .json
        theme_file_path = core.APP_ROOT / "themes" / f"{theme_name}.json"

        if theme_file_path.exists():
            # Se o arquivo .json existe, passamos o caminho completo para o CustomTkinter
            ctk.set_default_color_theme(str(theme_file_path))
        else:
            # Caso contrário, tentamos carregar como tema interno (blue, green, dark-blue)
            # Se o usuário salvou 'darkblue' e o tema interno é 'dark-blue', corrigimos:
            if theme_name == "darkblue":
                ctk.set_default_color_theme("dark-blue")
            elif theme_name in ["blue", "green", "dark-blue"]:
                ctk.set_default_color_theme(theme_name)
            else:
                # Fallback final
                ctk.set_default_color_theme("blue")


    # ---------- Construção: Sidebar ----------

    def _build_sidebar(self) -> None:
        self.sidebar = box(master=self, relwidth=0.15, relheight=1, corner_radius=0)

        self.logo_label = Label(master=self.sidebar, text="GELUGA", font_size=22, bold=True, relx=0.5, rely=0.05, anchor="center")

        self.btn_home = Button(master=self.sidebar, text="🎮 Jogar", relx=0.1, rely=0.12, relwidth=0.8, anchor="w", command=self.show_home)
        self.btn_mods = Button(master=self.sidebar, text="🛠️ Mods/Shaders", relx=0.1, rely=0.19, relwidth=0.8, anchor="w", command=self.show_mods)
        self._nav_default_color = self.btn_home.cget("fg_color")

        # Fundo da Sidebar (Usuário)
        self.user_panel = box(master=self.sidebar, relx=0.0, rely=1.0, relwidth=1.0, sizey=110, anchor="sw", color="transparent", corner_radius=0)
        self.user_label = Label(master=self.user_panel, text="Player (Offline)", font_size=14, bold=True, relx=0.5, rely=0.45, anchor="center")
        self.btn_settings = Button(master=self.user_panel, text="⚙️ Configurações", relx=0.1, rely=0.6, relwidth=0.8, sizey=30, command=self.show_settings)

    def _highlight_nav(self, which: str) -> None:
        pass

    # ---------- Construção: Área central (Jogar / Mods+Shaders / Configurações) ----------

    def _build_main_area(self) -> None:
        self.main_area = box(master=self, relx=0.15, rely=0, relwidth=0.85, relheight=0.88, color="transparent")

        self.home_view = self._build_home_view()
        self.mods_view = self._build_mods_view()
        self.settings_view = self._build_settings_view()

        for view in (self.home_view, self.mods_view, self.settings_view):
            view.place(relx=0, rely=0, relwidth=1, relheight=1)

    def show_home(self) -> None:
        self.home_view.tkraise()
        self._highlight_nav("home")

    def show_mods(self) -> None:
        self.mods_view.tkraise()
        self._highlight_nav("mods")
        self._refresh_installed_list()

    def show_settings(self) -> None:
        self.settings_view.tkraise()
        self._highlight_nav("settings")

    # ---------- Tela: Jogar (imagens da comunidade) ----------

    def _build_home_view(self) -> ctk.CTkFrame:
        view = ctk.CTkFrame(self.main_area, fg_color="transparent")

        Label(master=view, text=core.SERVER_VERSION_NAME, font_size=24, bold=True, relx=0.02, rely=0.04, anchor="nw")
        Label(
            master=view, text="Clique em uma imagem para entrar no Discord do servidor",
            font_size=13, text_color="gray", relx=0.02, rely=0.11, anchor="nw"
        )

        grid = ctk.CTkFrame(view, fg_color="transparent")
        grid.place(relx=0.02, rely=0.18, relwidth=0.96, relheight=0.78)
        for col in range(3):
            grid.grid_columnconfigure(col, weight=1, uniform="community")
        for row in range(2):
            grid.grid_rowconfigure(row, weight=1, uniform="community")

        self._community_slots = []
        for i in range(6):
            slot = ctk.CTkFrame(grid, fg_color=("gray85", "gray20"), corner_radius=10)
            slot.grid(row=i // 3, column=i % 3, padx=8, pady=8, sticky="nsew")
            placeholder = ctk.CTkLabel(slot, text="Carregando...", text_color="gray")
            placeholder.place(relx=0.5, rely=0.5, anchor="center")
            self._community_slots.append((slot, placeholder))

        return view

    def _load_community_images(self) -> None:
        def work():
            try:
                urls = core.get_community_image_urls(limit=6)
            except Exception as exc:
                core.bus.log(f"Não foi possível carregar imagens da comunidade: {exc}", level="warning")
                return []
            return [core.cache_remote_image(url) for url in urls]

        def done(paths):
            for i, (slot, placeholder) in enumerate(self._community_slots):
                placeholder.destroy()
                path = paths[i] if i < len(paths) else None
                image = load_image(path, size=(260, 150)) if path else None
                if image is None:
                    ctk.CTkLabel(slot, text="Sem imagem", text_color="gray").place(relx=0.5, rely=0.5, anchor="center")
                    continue
                img_label = ctk.CTkLabel(slot, image=image, text="", cursor="hand2")
                img_label.image = image
                img_label.place(relx=0.5, rely=0.5, anchor="center")
                img_label.bind("<Button-1>", lambda _e: webbrowser.open(core.DISCORD_INVITE_URL))

        self._run_async(work, on_done=done)

    # ---------- Tela: Mods / Shaders ----------

    def _build_mods_view(self) -> ctk.CTkFrame:
        view = ctk.CTkFrame(self.main_area, fg_color="transparent")

        self.mod_type_var = ctk.StringVar(value="mod")
        toggle = ctk.CTkSegmentedButton(view, values=["Mods", "Shaders"], command=self._on_mod_type_changed)
        toggle.set("Mods")
        toggle.place(relx=0.02, rely=0.03, anchor="nw")

        Label(master=view, text="Instalados", font_size=15, bold=True, relx=0.02, rely=0.13, anchor="nw")
        self.installed_frame = ctk.CTkScrollableFrame(view, fg_color=("gray90", "gray17"))
        self.installed_frame.place(relx=0.02, rely=0.18, relwidth=0.46, relheight=0.79)

        Label(master=view, text="Buscar no Modrinth", font_size=15, bold=True, relx=0.52, rely=0.03, anchor="nw")
        self.mod_search_entry = ctk.CTkEntry(view, placeholder_text="Pesquisar...", height=32)
        self.mod_search_entry.place(relx=0.52, rely=0.09, relwidth=0.34, anchor="nw")
        self.mod_search_entry.bind("<Return>", lambda _e: self._search_modrinth())

        Button(master=view, text="Buscar", relx=0.88, rely=0.09, sizex=90, sizey=32, anchor="nw", command=self._search_modrinth)

        self.search_results_frame = ctk.CTkScrollableFrame(view, fg_color=("gray90", "gray17"))
        self.search_results_frame.place(relx=0.52, rely=0.18, relwidth=0.46, relheight=0.79)
        ctk.CTkLabel(self.search_results_frame, text="Os mods aparecerão aqui.", text_color="gray").pack(pady=12)

        self.after(100, self._search_modrinth) 
        
        return view

    def _on_mod_type_changed(self, value: str) -> None:
        # Atualiza a variável de tipo
        self.mod_type_var.set("shader" if value == "Shaders" else "mod")
        
        # Limpa o campo de busca para garantir que estamos buscando "recomendados" (vazio)
        self.mod_search_entry.delete(0, "end")
        
        # Atualiza a lista de instalados
        self._refresh_installed_list()
        
        # Dispara a busca automática (agora com a query vazia)
        self._search_modrinth()

    def _refresh_installed_list(self) -> None:
        for widget in self.installed_frame.winfo_children():
            widget.destroy()

        if self.mod_type_var.get() == "shader":
            names = core.list_installed_shaderpacks()
            directory = core.SHADERPACKS_DIR
        else:
            names = core.list_installed_mods()
            directory = core.MODS_DIR

        if not names:
            ctk.CTkLabel(self.installed_frame, text="Nada instalado ainda.", text_color="gray").pack(pady=12)
            return

        for name in names:
            row = ctk.CTkFrame(self.installed_frame, fg_color="transparent")
            row.pack(fill="x", pady=3, padx=4)
            ctk.CTkLabel(row, text=name, anchor="w").pack(side="left", fill="x", expand=True, padx=(4, 8))
            ctk.CTkButton(
                row, text="Remover", width=80, height=26, fg_color="#a83232", hover_color="#c73c3c",
                command=lambda n=name, d=directory: self._remove_installed(n, d)
            ).pack(side="right", padx=4)

    def _remove_installed(self, name: str, directory) -> None:
        try:
            core.uninstall_file(name, directory=directory)
            core.bus.log(f"Removido: {name}", level="success")
        except OSError as exc:
            core.bus.log(f"Falha ao remover {name}: {exc}", level="error")
        self._refresh_installed_list()

    def _search_modrinth(self) -> None:
        query = self.mod_search_entry.get().strip()
        mod_type = self.mod_type_var.get()

        for widget in self.search_results_frame.winfo_children():
            widget.destroy()
            
        # Muda o texto de status para algo mais amigável
        status_text = "Carregando recomendados..." if not query else "Buscando..."
        ctk.CTkLabel(self.search_results_frame, text=status_text, text_color="gray").pack(pady=12)

        def work():
            # A API do Modrinth, se receber uma query vazia, 
            # costuma retornar os projetos mais populares de acordo com os filtros
            return core.modrinth_search_mods(query, project_type=mod_type)

        def done(hits):
            # Limpa o "Carregando..."
            for widget in self.search_results_frame.winfo_children():
                widget.destroy()
            
            if not hits:
                ctk.CTkLabel(self.search_results_frame, text="Nada encontrado.", text_color="gray").pack(pady=12)
                return
            
            for hit in hits:
                self._add_search_result_row(hit, mod_type)

        def err(exc):
            for widget in self.search_results_frame.winfo_children():
                widget.destroy()
            ctk.CTkLabel(self.search_results_frame, text=f"Erro: {exc}", text_color="gray").pack(pady=12)

        self._run_async(work, on_done=done, on_error=err)

    def _add_search_result_row(self, hit: dict, mod_type: str) -> None:
        row = ctk.CTkFrame(self.search_results_frame, fg_color=("gray85", "gray22"), corner_radius=8)
        row.pack(fill="x", pady=4, padx=4)
        row.grid_columnconfigure(1, weight=1)

        icon_label = ctk.CTkLabel(row, text="", width=40, height=40)
        icon_label.grid(row=0, column=0, rowspan=2, padx=8, pady=8)

        title = hit.get("title") or hit.get("slug") or "Sem título"
        downloads = hit.get("downloads", 0)
        ctk.CTkLabel(row, text=title, font=ctk.CTkFont(size=13, weight="bold"), anchor="w").grid(
            row=0, column=1, sticky="w", padx=(0, 8), pady=(8, 0)
        )
        ctk.CTkLabel(
            row, text=f"↓ {downloads:,}".replace(",", "."), text_color="gray", anchor="w", font=ctk.CTkFont(size=11)
        ).grid(row=1, column=1, sticky="w", padx=(0, 8), pady=(0, 8))

        project_id = hit.get("project_id") or hit.get("slug")
        ctk.CTkButton(
            row, text="Instalar", width=80, height=28,
            command=lambda pid=project_id, name=title: self._install_from_search(pid, name, mod_type)
        ).grid(row=0, column=2, rowspan=2, padx=8)

        icon_url = hit.get("icon_url")
        if icon_url:
            def load_icon():
                return core.cache_remote_image(icon_url)

            def icon_done(path):
                image = load_image(path, size=(40, 40))
                if image:
                    icon_label.configure(image=image)
                    icon_label.image = image

            self._run_async(load_icon, on_done=icon_done)

    def _install_from_search(self, project_id: Optional[str], name: str, mod_type: str) -> None:
        if not project_id:
            core.bus.log("Não foi possível identificar este item no Modrinth.", level="error")
            return

        def work():
            if mod_type == "shader":
                return core.install_from_modrinth(project_id, destination_dir=core.SHADERPACKS_DIR, loaders=[])
            return core.install_from_modrinth(project_id, destination_dir=core.MODS_DIR)

        def done(_filename):
            self._refresh_installed_list()

        def err(exc):
            core.bus.log(f"Falha ao instalar {name}: {exc}", level="error")

        self._run_async(work, on_done=done, on_error=err)

    # ---------- Tela: Configurações ----------

    def _build_settings_view(self) -> ctk.CTkFrame:
        view = ctk.CTkFrame(self.main_area, fg_color="transparent")
        settings = self.settings

        Label(master=view, text="Configurações", font_size=24, bold=True, relx=0.02, rely=0.04, anchor="nw")

        # --- Conta ---
        account_card = ctk.CTkFrame(view, corner_radius=10)
        account_card.place(relx=0.02, rely=0.14, relwidth=0.62, relheight=0.34)

        ctk.CTkLabel(account_card, text="Autenticação e Conta", font=ctk.CTkFont(size=14, weight="bold")).pack(
            anchor="w", padx=16, pady=(14, 8)
        )

        self.auth_mode_var = ctk.StringVar(value=settings.get("auth_mode", "offline"))
        ctk.CTkRadioButton(
            account_card, text="Somente usuário (offline)", variable=self.auth_mode_var,
            value="offline", command=self._on_auth_mode_changed
        ).pack(anchor="w", padx=16, pady=4)
        ctk.CTkRadioButton(
            account_card, text="Conta Microsoft (original)", variable=self.auth_mode_var,
            value="microsoft", command=self._on_auth_mode_changed
        ).pack(anchor="w", padx=16, pady=4)

        entry_row = ctk.CTkFrame(account_card, fg_color="transparent")
        entry_row.pack(fill="x", padx=16, pady=(10, 8))
        self.username_entry = ctk.CTkEntry(entry_row, placeholder_text="Nome de usuário (3-16 caracteres)", height=34)
        self.username_entry.insert(0, settings.get("username", ""))
        self.username_entry.pack(side="left", fill="x", expand=True, padx=(0, 8))
        self.username_entry.bind("<FocusOut>", lambda _e: self._save_username())

        self.ms_login_button = ctk.CTkButton(entry_row, text="Entrar com Microsoft", height=34, command=self._on_login_microsoft)
        self.ms_login_button.pack(side="left")

        self.ms_status_label = ctk.CTkLabel(account_card, text="", text_color="gray")
        self.ms_status_label.pack(anchor="w", padx=16, pady=(0, 12))

        # --- RAM ---
        ram_card = ctk.CTkFrame(view, corner_radius=10)
        ram_card.place(relx=0.02, rely=0.50, relwidth=0.62, relheight=0.20)

        ctk.CTkLabel(ram_card, text="Alocação de memória RAM", font=ctk.CTkFont(size=14, weight="bold")).pack(
            anchor="w", padx=16, pady=(14, 4)
        )
        self.ram_value_label = ctk.CTkLabel(ram_card, text="")
        self.ram_value_label.pack(anchor="w", padx=16)
        self.ram_slider = ctk.CTkSlider(ram_card, from_=1, to=16, number_of_steps=15, command=self._on_ram_changed)
        self.ram_slider.set(settings.get("ram_max_gb", 4))
        self.ram_slider.pack(fill="x", padx=16, pady=(8, 14))
        self._update_ram_label(settings.get("ram_max_gb", 4))

        # --- Extras ---
        extra_card = ctk.CTkFrame(view, corner_radius=10)
        extra_card.place(relx=0.02, rely=0.72, relwidth=0.62, relheight=0.14)

        self.close_on_play_var = ctk.BooleanVar(value=settings.get("close_launcher_on_play", False))
        ctk.CTkCheckBox(
            extra_card, text="Fechar o launcher automaticamente ao iniciar o jogo",
            variable=self.close_on_play_var, command=self._save_extra_options
        ).pack(anchor="w", padx=16, pady=16)

        self._on_auth_mode_changed(persist=False)

        appearance_card = ctk.CTkFrame(view, corner_radius=10)
        appearance_card.place(relx=0.02, rely=0.72, relwidth=0.62, relheight=0.20)

        # Alternância Claro/Escuro
        mode_btn = ctk.CTkButton(
            appearance_card, text="Alternar Claro/Escuro", 
            command=self._toggle_appearance_mode
        )
        mode_btn.pack(pady=10)

        # Lista de arquivos .json em .geluga/themes/
        theme_files = [f.stem for f in (core.APP_ROOT / "themes").glob("*.json")]
        theme_files = list(set(["blue", "green", "dark-blue"] + theme_files)) # Garantir nativos

        self.theme_menu = ctk.CTkOptionMenu(
            appearance_card, values=theme_files, 
            command=self._apply_new_theme, state="normal"
        )
        self.theme_menu.set(get_app_theme_config()[0])
        self.theme_menu.pack(pady=5)
        
        return view

    def _toggle_appearance_mode(self):
        new_mode = "Light" if ctk.get_appearance_mode() == "Dark" else "Dark"
        ctk.set_appearance_mode(new_mode)
        theme, _ = get_app_theme_config()
        save_theme_config(theme, new_mode)



    def _apply_new_theme(self, new_theme: str):
        import os
        import sys
        
        _, mode = get_app_theme_config()
        save_theme_config(new_theme, mode)
        
        core.bus.log("Aplicando tema e reiniciando...")
        
        # O comando abaixo encerra o processo atual e inicia um novo
        os.execv(sys.executable, ['python'] + sys.argv)

    def _save_username(self) -> None:
        self.settings["username"] = self.username_entry.get().strip()
        core.save_settings(self.settings)
        self._refresh_user_panel()

    def _on_ram_changed(self, value: float) -> None:
        gb = int(round(value))
        self._update_ram_label(gb)
        self.settings["ram_max_gb"] = gb
        self.settings["ram_min_gb"] = max(1, gb // 2)
        core.save_settings(self.settings)

    def _update_ram_label(self, gb: int) -> None:
        self.ram_value_label.configure(text=f"{gb} GB alocados para o Minecraft")

    def _save_extra_options(self) -> None:
        self.settings["close_launcher_on_play"] = bool(self.close_on_play_var.get())
        core.save_settings(self.settings)

    def _on_auth_mode_changed(self, persist: bool = True) -> None:
        mode = self.auth_mode_var.get()
        if persist:
            self.settings["auth_mode"] = mode
            core.save_settings(self.settings)
        if mode == "microsoft":
            self.username_entry.configure(state="disabled")
            self.ms_login_button.configure(state="normal")
            account = self.settings.get("ms_account")
            if account:
                self.ms_status_label.configure(text=f"Conectado como {account.get('username')}")
            else:
                self.ms_status_label.configure(text="Nenhuma conta conectada ainda.")
        else:
            self.username_entry.configure(state="normal")
            self.ms_login_button.configure(state="disabled")
            self.ms_status_label.configure(text="")
        self._refresh_user_panel()

    def _on_login_microsoft(self) -> None:
        if self._busy:
            return
        self._set_busy(True)
        self.ms_login_button.configure(text="Entrando...", state="disabled")
        self.ms_status_label.configure(text="Aguardando confirmação no navegador...")

        def work():
            return core.login_with_microsoft()

        def done(result):
            profile, refresh_token = result
            self._profile = profile
            self.settings["ms_account"] = {
                "username": profile.username, "uuid": profile.uuid, "refresh_token": refresh_token,
            }
            core.save_settings(self.settings)
            self._set_busy(False)
            self.ms_login_button.configure(text="Entrar com Microsoft", state="normal")
            self.ms_status_label.configure(text=f"Conectado como {profile.username}")
            self._refresh_user_panel()

        def err(exc):
            self._set_busy(False)
            self.ms_login_button.configure(text="Entrar com Microsoft", state="normal")
            self.ms_status_label.configure(text="Falha no login. Veja o log para detalhes.")
            core.bus.log(f"Erro no login Microsoft: {exc}", level="error")

        self._run_async(work, on_done=done, on_error=err)

    def _refresh_user_panel(self) -> None:
        mode = self.settings.get("auth_mode", "offline")
        if mode == "microsoft":
            account = self.settings.get("ms_account")
            name = account.get("username") if account else "Não conectado"
        else:
            name = self.settings.get("username") or "GelugaPlayer"
        self.user_label.configure(text=name)

    # ---------- Bottombar (versão, JOGAR/SAIR, progresso, log) ----------

    def _build_bottombar(self) -> None:
        self.bottombar = box(master=self, relx=0.15, rely=0.88, relwidth=0.85, relheight=0.12, corner_radius=0)

        # BARRA DE PROGRESSO NO TOPO DA BOTTOMBAR (Esticada na largura total)
        self.progress_bar = ProgressBar(
            master=self.bottombar,
            relx=0.5, rely=0.0, relwidth=1.0, anchor="n",
            sizey=6, initial_value=0.0, corner_radius=0
        )

        # ESQUERDA: Seletor de Versões Ativo
        self.version_label = Label(master=self.bottombar, text="Versão:", bold=True, relx=0.03, rely=0.3, anchor="w")
        
        # Puxa a lista de versões do core.py
        version_list = core.get_installed_versions()
        
        self.version_combo = ComboBox(
            master=self.bottombar, 
            values=version_list, 
            relx=0.03, rely=0.65, anchor="w", sizex=180,
            state="readonly"  # "readonly" impede o usuário de digitar texto aleatório, forçando o clique na lista
        )
        self.version_combo.set(core.SERVER_VERSION_NAME)

        # CENTRO: Botão Jogar e Botão Sair lado a lado
        self.btn_play = Button(
            master=self.bottombar, text="JOGAR", relx=0.4, rely=0.5, sizex=200, sizey=55, anchor="center",
            font_size=20, bold=True, text_color="white", command=self.lancar_jogo
        )

        # DIREITA: Caixa de Log
        self.log_box = TextBox(
            master=self.bottombar,
            relx=0.58, rely=0.15, relwidth=0.39, relheight=0.75,
            font_size=11, color=("gray90", "gray17")
        )

        self.log_box.log("Geluga Launcher iniciado com sucesso.")
        self.log_box.log("Aguardando ação do jogador...")

    def refresh_version_list(self):
        """Atualiza os valores do ComboBox de versões com as pastas mais recentes no disco."""
        if hasattr(self, "version_combo"):
            versions = core.get_installed_versions()
            current = self.version_combo.get()
            self.version_combo.configure(values=versions)
            if current not in versions and versions:
                self.version_combo.set(versions[0])

    # ---------- Infra: fila de eventos, threads, lançamento do jogo ----------

    def _poll_bus(self) -> None:
        for event in core.bus.drain():
            if isinstance(event, core.LogEvent):
                self.log_box.log(event.text)
            elif isinstance(event, core.ProgressEvent):
                if event.current is not None and event.maximum:
                    self.progress_bar.stop()
                    self.progress_bar.configure(mode="determinate")
                    self.progress_bar.set(event.current / event.maximum)
        self.after(120, self._poll_bus)

    def _run_async(self, target: Callable[[], object], on_done: Optional[Callable] = None, on_error: Optional[Callable] = None) -> None:
        def worker() -> None:
            try:
                result = target()
            except Exception as exc:
                traceback.print_exc()
                core.bus.log(f"Erro: {exc}", level="error")
                if on_error:
                    self.after(0, lambda e=exc: on_error(e))
                return
            if on_done:
                self.after(0, lambda r=result: on_done(r))

        threading.Thread(target=worker, daemon=True).start()

    def _set_busy(self, value: bool) -> None:
        self._busy = value
        self.btn_play.configure(state=("disabled" if value else "normal"))

    def _startup_check(self) -> None:
        def work():
            local_version = core.get_local_version()
            update_available = False
            if local_version is not None:
                try:
                    update_available = core.has_update_available()
                except Exception:
                    update_available = False
            return local_version, update_available

        def done(result):
            local_version, update_available = result
            if local_version is None:
                core.bus.log("Nenhum mod instalado ainda — clique em Jogar para instalar tudo.")
            elif update_available:
                core.bus.log("Há uma nova versão dos mods disponível.")
            else:
                core.bus.log("Mods atualizados. Pronto para jogar.")

        self._run_async(work, on_done=done)

        account = self.settings.get("ms_account")
        if self.settings.get("auth_mode") == "microsoft" and account and account.get("refresh_token"):
            def refresh_work():
                return core.refresh_microsoft_login(account["refresh_token"])

            def refresh_done(result):
                profile, refresh_token = result
                self._profile = profile
                self.settings["ms_account"] = {
                    "username": profile.username, "uuid": profile.uuid, "refresh_token": refresh_token,
                }
                core.save_settings(self.settings)
                self._refresh_user_panel()
                self.ms_status_label.configure(text=f"Conectado como {profile.username}")

            def refresh_err(_exc):
                core.bus.log("Sessão Microsoft expirada — faça login novamente em Configurações.", level="warning")

            self._run_async(refresh_work, on_done=refresh_done, on_error=refresh_err)

    def lancar_jogo(self) -> None:
        # 1. Evita cliques duplos ou execução se o launcher já estiver processando
        if self._busy:
            return

        # 2. Valida a autenticação (Offline ou Microsoft) ANTES de tentar instalar o jogo
        mode = self.settings.get("auth_mode", "offline")
        if mode == "microsoft":
            if not self._profile:
                core.bus.log("Faça login com sua conta Microsoft em Configurações antes de jogar.", level="warning")
                self.show_settings()
                return
            profile = self._profile
        else:
            username = self.settings.get("username", "").strip()
            try:
                profile = core.build_offline_profile(username)
            except ValueError as exc:
                core.bus.log(str(exc), level="warning")
                self.show_settings()
                return
            self._profile = profile

        # 3. Trava a interface visual para o usuário saber que o processo começou
        self._set_busy(True)
        self.btn_play.configure(text="PREPARANDO...")
        self.progress_bar.configure(mode="indeterminate")
        self.progress_bar.start()

        # Lê tudo que é preciso da UI/settings AGORA, na thread principal —
        # o resto (rede/disco) roda todo dentro de work(), na thread de fundo.
        settings = core.load_settings()
        ram_min_gb = settings.get("ram_min_gb", 2)
        ram_max_gb = settings.get("ram_max_gb", 4)
        selected_version = self.version_combo.get()
        close_on_play = settings.get("close_launcher_on_play", False)

        # 4. Bloco principal de verificação, download e inicialização — roda em
        # background (via _run_async/threading.Thread), então pode demorar
        # sem travar a janela.
        def work():
            if selected_version == core.SERVER_VERSION_NAME:
                # Versão do Geluga: roda a verificação completa de mods + neoforge
                version_id, java_path = core.full_setup()
                core.sync_mods()
            else:
                # Outra versão já instalada (ex: Vanilla 1.20.4, OptiFine...)
                version_id = selected_version
                java_path = core.ensure_java(core.MINECRAFT_VERSION)
                if not core.is_minecraft_installed(version_id):
                    core.install_minecraft(version_id)

            cmd = core.build_command(
                version_id=version_id,
                profile=profile,
                ram_min_gb=ram_min_gb,
                ram_max_gb=ram_max_gb,
                java_path=java_path,
            )

            process = core.launch_game(cmd, version_id=version_id)
            core.stream_output(
                process,
                on_exit=lambda code: self.after(0, lambda: self._on_game_exit(code)),
            )
            return version_id

        # 5. Só o que roda aqui (na thread principal, via self.after) pode
        # mexer em widgets — nada de tocar na UI dentro de work().
        def done(version_id):
            self.refresh_version_list()
            self.progress_bar.stop()

            if close_on_play:
                self.destroy()
                return

            self.btn_play.configure(text="JOGANDO...", state="disabled")
            self.progress_bar.configure(mode="determinate")
            self.progress_bar.set(1.0)
            self._busy = True  # mantém travado até o jogo fechar (ver _on_game_exit)

        def err(exc):
            core.bus.log(f"Erro ao tentar iniciar o jogo: {exc}", level="error")
            self._set_busy(False)
            self.btn_play.configure(text="JOGAR")
            self.progress_bar.stop()
            self.progress_bar.set(0)

        self._run_async(work, on_done=done, on_error=err)

    def _on_game_exit(self, code: int) -> None:
        self.btn_play.configure(text="JOGAR", state="normal")
        self._set_busy(False)
        core.bus.log(f"Minecraft foi encerrado (código {code}).")

if __name__ == "__main__":
    # 1. Carrega as configurações ANTES de criar a janela
    theme_name, mode = get_app_theme_config()
    
    # 2. Aplica o modo
    ctk.set_appearance_mode(mode)
    
    # 3. Aplica o tema
    theme_file_path = core.APP_ROOT / "themes" / f"{theme_name}.json"
    if theme_file_path.exists():
        ctk.set_default_color_theme(str(theme_file_path))
    elif theme_name == "darkblue":
        ctk.set_default_color_theme("dark-blue")
    elif theme_name in ["blue", "green", "dark-blue"]:
        ctk.set_default_color_theme(theme_name)
    else:
        ctk.set_default_color_theme("blue")
    
    # 4. Agora sim, cria e roda o App
    app = App()
    app.mainloop()
