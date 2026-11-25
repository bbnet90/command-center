import asyncio
import os
import shlex
import signal
import sys
import threading
from threading import current_thread, main_thread
from datetime import datetime

from rich.cells import cell_len
from rich.text import Text
from .background import background
from textual.app import App, ComposeResult, SuspendNotSupported
from textual.binding import Binding
from textual.containers import Container, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Input, Static

from . import llm, state
from .command_panels import Processes
from .config import read_order, settings
from .package_process import PackageProcess
from .plugins import discover, inspect_panel
from .rendering import PANEL_WIDTH, clipped
from .text import clean


HINTS = "Tab odak · ↑↓ kaydır · r yenile · [ ] taşı · l yerleşim · t tema · m modüller · q çık"


class KeyHelp(ModalScreen):
    BINDINGS = [("escape,question_mark", "dismiss", "Kapat"), ("q", "app.quit", "Çık")]

    def compose(self):
        yield Static(Text(
            "Klavye yardımı\n"
            "Tab / Shift+Tab · Sonraki / önceki odak\n"
            "↑ ↓ / PgUp PgDn · Paneli kaydır\n"
            "r / R · Paneli / tümünü yenile\n"
            "[ / ] · Paneli yukarı / aşağı taşı\n"
            "l / t · Yerleşimi / temayı değiştir\n"
            "Enter · Paneli aç veya soruyu gönder\n"
            "Esc · Yanıtı iptal et veya pencereyi kapat\n"
            "m · Katalog: Enter kur, x kaldır, y onayla\n"
            "? · Yardım   q / Ctrl+C · Çık"
        ))


def greeting(hour):
    if 6 <= hour < 12:
        return "Günaydın"
    if 12 <= hour < 18:
        return "İyi günler"
    if 18 <= hour < 22:
        return "İyi akşamlar"
    return "İyi geceler"


class Section(VerticalScroll):
    can_focus = True
    BINDINGS = [("enter", "open_panel", "Aç")]

    def __init__(self, key, entry):
        super().__init__()
        self.key = key
        self.entry = entry
        self.data = None
        self.caption = clean(key)
        self.rows = ["yükleniyor…"]
        self.generation = 0
        self.panel_loading = False
        self.unresponsive = False
        self.last_success = None

    def compose(self):
        yield Static(Text(self.rows[0]), markup=False)

    def redraw(self):
        self.border_title = Text(("❯ " if self.app.focused is self else "") + self.caption)
        if self.is_mounted:
            self.app.update_hints()
            self.query_one(Static).update(clipped(self.rows, self.scrollable_content_region.width))

    def reload(self):
        self.generation += 1
        token = self.generation
        self.panel_loading = True
        if self.last_success is None:
            self.rows = ["yükleniyor…"]
        self.redraw()
        self.set_timer(10, lambda: self.slow(token))
        self.fetch(token)

    def slow(self, token):
        if self.generation == token and self.panel_loading:
            self.unresponsive = True
            if self.last_success is None:
                self.rows = ["yanıt vermiyor…"]
            self.app.clock()
            self.redraw()

    @background
    def fetch(self, token):
        data = inspect_panel(self.entry).panel
        self.app.call_from_thread(self.receive, token, data)

    def receive(self, token, data):
        if self.is_mounted and token == self.generation:
            self.panel_loading = False
            self.unresponsive = data is None
            if data is not None:
                self.last_success = datetime.now().strftime("%H:%M")
                self.border_subtitle = f"güncellendi {self.last_success}"
            elif self.last_success:
                self.border_subtitle = f"eski veri · {self.last_success}"
                data = self.data
            else:
                data = {"title": self.key, "lines": ["Bu modüle ulaşılamadı"]}
            self.set_class(self.unresponsive and bool(self.last_success), "stale")
            self.data = data
            self.caption = clean(data["title"])
            self.rows = data["lines"]
            self.app.clock()
            self.redraw()

    async def action_open_panel(self):
        argv = (self.data or {}).get("open")
        if not argv:
            return
        notice = None
        try:
            with self.app.suspend():
                # Leave the context normally so the terminal is always restored.
                try:
                    await self.app.open_runner(argv)
                except FileNotFoundError:
                    notice = "Komut bulunamadı: " + clean(argv[0])
                except (OSError, ValueError, RuntimeError):
                    notice = "Komut açılamadı."
        except SuspendNotSupported:
            notice = "Bu terminalde komut açılamıyor."
        if notice:
            self.app.notify(notice, markup=False)
        if self.is_mounted and not self.app.shutdown_started:
            self.reload()

    on_resize = redraw
    on_focus = redraw
    on_blur = redraw


class PanelBody(VerticalScroll):
    def on_resize(self, event):
        self.app.size_sections(self, event.size.height)
        self.app.update_hints()


class Dashboard(App):
    CSS = f"""
    Screen {{ align-horizontal: center; }}
    #header {{ height: auto; width: 100%; align-horizontal: center; border-bottom: solid $accent; }}
    #header > * {{ width: {PANEL_WIDTH}; max-width: 100%; }}
    #answer {{ height: auto; max-height: 5; overflow-y: auto; }}
    #body {{ width: 100%; align-horizontal: center; }}
    #sections {{ layout: grid; grid-size: 1; grid-rows: auto; height: auto; width: {PANEL_WIDTH}; max-width: 100%; }}
    #sections.wide {{ grid-size: 2; width: {2 * PANEL_WIDTH}; }}
    Section {{ border: round $secondary; height: auto; min-height: 3; max-height: 12; padding: 0 1; }}
    Section.stale {{ border-subtitle-color: $warning; }}
    KeyHelp {{ align: center middle; background: $background 85%; }}
    KeyHelp Static {{ width: auto; max-width: 100%; height: auto; border: round $accent; }}
    Section:focus {{ border: round $accent; }}
    #hints {{ height: 1; width: 100%; border-top: none; background: $boost; }}
    """
    BINDINGS = [
        ("question_mark", "help", "Yardım"),
        ("m", "modules", "Modüller"),
        ("escape", "cancel", "İptal"),
        ("left_square_bracket", "move(-1)", "Yukarı"),
        ("right_square_bracket", "move(1)", "Aşağı"),
        ("l", "layout", "Yerleşim"),
        ("t", "cycle_theme", "Tema"),
        ("r", "refresh", "Yenile"),
        ("R", "refresh_all", "Tümünü yenile"),
        ("q", "quit", "Çık"),
        Binding("ctrl+c", "quit", "Çık", priority=True),
    ]

    def __init__(self, *, runner=None, open_runner=None):
        super().__init__()
        self.commands = Processes()
        self.open_child = None
        self.open_runner = open_runner or self.run_open
        self.packages = PackageProcess()
        self.runner = runner or self.packages.run
        self.shutdown_started = False
        self.quit_prompt = False
        providers, selected = llm.providers()
        self.provider = providers.get(selected)
        self.request = 0
        self.entries = discover(self.commands)
        order = read_order()
        saved = state.preferences()
        defaults = settings()
        self.preset = saved.get("layout", defaults.get("layout"))
        if self.preset != "two-column":
            self.preset = "single"
        theme = saved.get("theme", defaults.get("theme"))
        if isinstance(theme, str) and theme in self.available_themes:
            self.theme = theme
        self.sections = [Section(k, self.entries[k]) for k in self.visible(order, saved)]

    async def shutdown(self):
        if self.shutdown_started:
            return
        self.shutdown_started = True
        self.commands.close()
        if self.open_child and self.open_child.returncode is None:
            try:
                self.open_child.kill()
            except ProcessLookupError:
                pass
        await self.packages.shutdown()
        self.exit()

    async def action_quit(self):
        if self.packages.child is not None:
            if not self.quit_prompt:
                from .catalog_screen import Confirmation
                self.quit_prompt = True
                self.push_screen(Confirmation([], prompt="Kurulum sürüyor, çıkılsın mı? (y/n)"),
                                 self.quit_decided)
            return
        await self.shutdown()

    async def quit_decided(self, confirmed):
        self.quit_prompt = False
        if confirmed:
            await self.shutdown()

    def visible(self, order, saved):
        visible = sorted(self.entries) if order is None else order
        saved_order = saved.get("order")
        if isinstance(saved_order, list):
            visible = list(dict.fromkeys([k for k in saved_order if k in visible] + visible))
        return [k for k in visible if k in self.entries]

    def compose(self) -> ComposeResult:
        with Vertical(id="header"):
            yield Static(id="greeting")
            yield Input(placeholder="Soru sor" if self.provider else "Model bağlı değil",
                        disabled=self.provider is None, max_length=500)
            yield Static(id="answer")
        with PanelBody(id="body", can_focus=False):
            with Container(id="sections"):
                yield from self.sections
        yield Static(Text(HINTS, no_wrap=True), id="hints")

    def on_mount(self):
        self.base_screen = self.screen
        if not self.entries:
            self.call_after_refresh(self.action_modules)
        self.clock()
        self.set_interval(60, self.clock)
        for section in self.sections:
            section.reload()

    def action_layout(self):
        self.preset = "single" if self.preset == "two-column" else "two-column"
        state.save(layout=self.preset)
        self.size_sections(self.base_screen.query_one(PanelBody))

    def size_sections(self, body, height=None):
        height = height or body.size.height
        wide = self.preset == "two-column" and self.size.width >= 2 * PANEL_WIDTH
        body.query_one("#sections").set_class(wide, "wide")
        columns = 2 if wide else 1
        rows = max(1, (len(self.sections) + columns - 1) // columns)
        limit = max(3, min(int(height * .6), height // rows))
        for section in self.sections:
            section.styles.max_height = limit

    def action_help(self):
        if self.screen is self.base_screen:
            self.push_screen(KeyHelp())

    def action_cycle_theme(self):
        themes = list(self.available_themes)
        self.theme = themes[(themes.index(self.theme) + 1) % len(themes)]
        state.save(theme=self.theme)

    def action_move(self, delta):
        section = self.focused
        if section not in self.sections:
            return
        index = self.sections.index(section)
        target = index + delta
        if 0 <= target < len(self.sections):
            neighbor = self.sections[target]
            section.parent.move_child(section, before=neighbor if delta < 0 else None,
                                      after=neighbor if delta > 0 else None)
            self.sections[index], self.sections[target] = neighbor, section
            state.save(order=[s.key for s in self.sections])

    def action_modules(self):
        from .catalog_screen import CatalogScreen
        if self.screen is self.base_screen:
            self.push_screen(CatalogScreen(self.entries, runner=self.runner))

    async def sync_sections(self):
        self.entries = discover(self.commands)
        grid = self.base_screen.query_one("#sections")
        await grid.remove_children()
        self.sections = [Section(k, self.entries[k]) for k in self.visible(read_order(), state.preferences())]
        await grid.mount(*self.sections)
        self.size_sections(self.base_screen.query_one(PanelBody))
        for section in self.sections:
            section.reload()
        self.clock()

    async def run_open(self, argv):
        proc = await asyncio.create_subprocess_exec(*argv)
        self.open_child = proc
        try:
            await proc.wait()
        finally:
            self.open_child = None

    def update_hints(self):
        if not hasattr(self, "base_screen"):
            return
        section = self.focused
        argv = (section.data or {}).get("open") if isinstance(section, Section) else None
        hint = "Enter → " + clean(shlex.join(argv)) + " · " if argv else ""
        full = hint + HINTS
        short = hint + "? yardım · q çık"
        self.base_screen.query_one("#hints", Static).update(
            Text(full if cell_len(full) <= self.size.width else short, no_wrap=True))

    def action_refresh(self):
        if isinstance(self.focused, Section):
            self.focused.reload()

    def action_refresh_all(self):
        for section in self.sections:
            section.reload()

    def on_input_submitted(self, event: Input.Submitted):
        if not self.provider or not event.value.strip():
            return
        self.request += 1
        self.base_screen.query_one("#answer", Static).update(Text("düşünüyor…"))
        self.ask(self.request, event.value, llm.context(s.data for s in self.sections if s.data))
        event.input.value = ""

    @background
    def ask(self, token, question, context):
        response = llm.answer(self.provider, question, context)
        self.call_from_thread(self.show_answer, token, response)

    def show_answer(self, token, response):
        if token == self.request:
            self.base_screen.query_one("#answer", Static).update(Text(response))

    def action_cancel(self):
        self.request += 1
        self.show_answer(self.request, "")

    def clock(self):
        now = datetime.now()
        count = sum(s.unresponsive for s in self.sections)
        warning = f" · {count} panel yanıt vermiyor" if count else ""
        self.base_screen.query_one("#greeting", Static).update(Text(
            f"{greeting(now.hour)} · {now:%d.%m.%Y %H:%M} · {len(self.entries)} panel yüklü{warning}"))


def run_dashboard():
    original_threads = set(threading.enumerate())
    app = Dashboard()
    previous = {}

    def stop(signum, frame):
        app.call_later(app.shutdown)

    try:
        if current_thread() is main_thread():
            for name in ("SIGINT", "SIGTERM", "SIGHUP"):
                if hasattr(signal, name):
                    sig = getattr(signal, name)
                    previous[sig] = signal.signal(sig, stop)
        app.run()
    finally:
        for sig, handler in previous.items():
            signal.signal(sig, handler)
    # Third-party code can explicitly create a non-daemon thread. The terminal
    # and signal handlers are restored before bypassing its interpreter join.
    if any(not thread.daemon and thread not in original_threads
           for thread in threading.enumerate()):
        sys.stdout.flush()
        sys.stderr.flush()
        os._exit(0)
