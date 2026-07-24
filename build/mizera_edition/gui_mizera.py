"""
gui_mizera.py — Interface gráfica do GeLauncher Mizera Edition.

Versão enxuta da interface: uma única tela com nome de usuário, botão "JOGAR"
e um console de log — sem abas, sem tela de configurações, sem seletor de
versão. Usa grid (com pesos) em vez de posicionamento livre por x/y, então a
janela é redimensionável e o console cresce/encolhe com ela.
"""

from __future__ import annotations

import threading
import traceback
from typing import Callable, Optional

import customtkinter as ctk

import core
import core_mizera as mizera


ctk.set_appearance_mode("Dark")
ctk.set_default_color_theme("blue")


class App(ctk.CTk):
    def __init__(self) -> None:
        super().__init__()

        self.settings = mizera.load_settings()
        self._profile: Optional[core.Profile] = None
        self._busy = False

        self.title(mizera.APP_NAME)
        self.geometry("420x580")
        self.minsize(360, 460)

        # Layout responsivo: 1 coluna, a linha do console (4) é a única que
        # ganha espaço extra quando a janela é redimensionada.
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(4, weight=1)

        self._build_ui()
        self._poll_bus()

    # ---------- Construção da interface ----------

    def _build_ui(self) -> None:
        ctk.CTkLabel(
            self, text="GELUGA", font=ctk.CTkFont(size=28, weight="bold")
        ).grid(row=0, column=0, padx=24, pady=(28, 0), sticky="ew")

        ctk.CTkLabel(
            self, text="MIZERA EDITION", font=ctk.CTkFont(size=13), text_color="gray"
        ).grid(row=1, column=0, padx=24, pady=(0, 20), sticky="ew")

        self.username_entry = ctk.CTkEntry(
            self, placeholder_text="Nome de usuário", height=38, justify="center"
        )
        self.username_entry.insert(0, self.settings.get("username", ""))
        self.username_entry.grid(row=2, column=0, padx=24, pady=(0, 12), sticky="ew")
        self.username_entry.bind("<FocusOut>", lambda _e: self._save_username())
        self.username_entry.bind("<Return>", lambda _e: self.jogar())

        self.btn_play = ctk.CTkButton(
            self, text="JOGAR", height=48, font=ctk.CTkFont(size=18, weight="bold"),
            command=self.jogar,
        )
        self.btn_play.grid(row=3, column=0, padx=24, pady=(0, 16), sticky="ew")

        self.log_box = ctk.CTkTextbox(
            self, font=ctk.CTkFont(family="Consolas", size=11), corner_radius=8
        )
        self.log_box.grid(row=4, column=0, padx=24, pady=(0, 24), sticky="nsew")
        self.log_box.configure(state="disabled")

        self._log("GeLauncher Mizera Edition pronto.")
        self._log("Digite seu usuário e clique em Jogar.")

    def _log(self, message: str) -> None:
        self.log_box.configure(state="normal")
        self.log_box.insert("end", f"> {message}\n")
        self.log_box.see("end")
        self.log_box.configure(state="disabled")

    # ---------- Persistência (só o nome de usuário) ----------

    def _save_username(self) -> None:
        self.settings["username"] = self.username_entry.get().strip()
        mizera.save_settings(self.settings)

    # ---------- Infra: fila de eventos e threads (mesmo padrão do gui.py) ----------

    def _poll_bus(self) -> None:
        for event in core.bus.drain():
            if isinstance(event, core.LogEvent):
                self._log(event.text)
            # ProgressEvent é ignorado de propósito: a edição lite não tem
            # barra de progresso separada, o andamento aparece só no console.
        self.after(120, self._poll_bus)

    def _run_async(
        self,
        target: Callable[[], object],
        on_done: Optional[Callable] = None,
        on_error: Optional[Callable] = None,
    ) -> None:
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
        self.username_entry.configure(state=("disabled" if value else "normal"))
        self.btn_play.configure(state=("disabled" if value else "normal"))

    # ---------- Ação principal: instala (se preciso) e joga ----------

    def jogar(self) -> None:
        if self._busy:
            return

        self._save_username()
        username = self.settings.get("username", "").strip()
        try:
            profile = core.build_offline_profile(username)
        except ValueError as exc:
            self._log(str(exc))
            return
        self._profile = profile

        self._set_busy(True)
        self.btn_play.configure(text="PREPARANDO...")

        def work():
            version_id, java_path = mizera.full_setup()
            mizera.sync_mods_and_configs()
            process = mizera.build_and_launch(profile, java_path)
            core.stream_output(
                process,
                on_exit=lambda code: self.after(0, lambda: self._on_game_exit(code)),
            )
            return version_id

        def done(_version_id) -> None:
            self.btn_play.configure(text="JOGANDO...")
            # continua travado (self._busy) até o Minecraft fechar

        def err(exc) -> None:
            self._log(f"Erro ao iniciar o jogo: {exc}")
            self._set_busy(False)
            self.btn_play.configure(text="JOGAR")

        self._run_async(work, on_done=done, on_error=err)

    def _on_game_exit(self, code: int) -> None:
        self.btn_play.configure(text="JOGAR")
        self._set_busy(False)
        self._log(f"Minecraft foi encerrado (código {code}).")


if __name__ == "__main__":
    app = App()
    app.mainloop()
