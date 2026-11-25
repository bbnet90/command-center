from datetime import datetime

from rich.text import Text
from textual import work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Container, Vertical, VerticalScroll
from textual.widgets import Input, Static

from . import llm, state
from .config import read_order, settings
from .plugins import discover, load_panel
from .rendering import PANEL_WIDTH, clipped
from .text import clean


class Section(VerticalScroll):
    can_focus = True

    def __init__(self, key, entry):
        super().__init__()
        self.key = key
        self.entry = entry
        self.data = None
        self.caption = clean(key)
        self.rows = ["yükleniyor…"]
        self.generation = 0

    def compose(self):
        yield Static(Text(self.rows[0]), markup=False)

    def redraw(self):
        self.border_title = Text(("❯ " if self.has_focus else "") + self.caption)
        if self.is_mounted:
            self.query_one(Static).update(clipped(self.rows, self.scrollable_content_region.width))

    def reload(self):
        self.generation += 1
        token = self.generation
        self.data = None
        self.rows = ["yükleniyor…"]
        self.redraw()
        self.set_timer(10, lambda: self.slow(token))
        self.fetch(token)

    def slow(self, token):
        if self.generation == token and self.data is None:
            self.rows = ["yanıt vermiyor…"]
            self.redraw()

    @work(thread=True, exit_on_error=False)
    def fetch(self, token):
        data = load_panel(self.entry)
        self.app.call_from_thread(self.receive, token, data)

    def receive(self, token, data):
        if self.is_mounted and token == self.generation:
            self.data = data
            self.caption = clean(data["title"])
            self.rows = data["lines"]
            self.redraw()

    on_resize = redraw
    on_focus = redraw
    on_blur = redraw


class PanelBody(VerticalScroll):
    def on_resize(self, event):
        self.query_one("#sections").set_class(
            self.app.preset == "two-column" and self.screen.size.width >= 2 * PANEL_WIDTH, "wide"
        )


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
    Section:focus {{ border: round $accent; }}
    #hints {{ height: 1; width: 100%; border-top: none; background: $boost; }}
    """
    BINDINGS = [
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

    def __init__(self, *, runner=None):
        super().__init__()
        self.runner = runner
        providers, selected = llm.providers()
        self.provider = providers.get(selected)
        self.request = 0
        self.entries = discover()
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
        yield Static(Text("Tab odak · ↑↓ kaydır · r yenile · [ ] taşı · l yerleşim · t tema · m modüller · q çık",
                          no_wrap=True), id="hints")

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
        self.base_screen.query_one("#sections").set_class(
            self.preset == "two-column" and self.size.width >= 2 * PANEL_WIDTH, "wide")

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
        self.entries = discover()
        grid = self.base_screen.query_one("#sections")
        await grid.remove_children()
        self.sections = [Section(k, self.entries[k]) for k in self.visible(read_order(), state.preferences())]
        await grid.mount(*self.sections)
        for section in self.sections:
            section.reload()
        self.clock()

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

    @work(thread=True, exit_on_error=False)
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
        self.base_screen.query_one("#greeting", Static).update(Text(
            f"Merhaba · {datetime.now():%d.%m.%Y %H:%M} · {len(self.entries)} panel yüklü"))
