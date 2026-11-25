from threading import Event
import subprocess

from rich.text import Text
from textual import work
from textual.screen import ModalScreen
from textual.widgets import OptionList, RichLog, Static
from textual.widgets.option_list import Option
from textual.worker import get_current_worker

from . import catalog_store, installer, state
from .text import clean


class Confirmation(ModalScreen):
    def __init__(self, rows):
        super().__init__()
        self.rows = rows

    def compose(self):
        yield Static(Text("\n".join([*self.rows, "Onaylamak için y · diğer tuşlar iptal"])))

    def on_key(self, event):
        event.stop()
        event.prevent_default()
        self.dismiss(event.key == "y")


class CatalogScreen(ModalScreen):
    BINDINGS = [("escape", "close", "Kapat"), ("x", "remove", "Kaldır")]
    CSS = """
    CatalogScreen { padding: 1; background: $surface; }
    CatalogScreen RichLog { height: 1fr; border: round $secondary; }
    CatalogScreen OptionList { height: 2fr; }
    Confirmation { align: center middle; background: $background 85%; }
    Confirmation Static { width: 90%; height: auto; border: round $accent; }
    """

    def __init__(self, entries, runner=None):
        super().__init__()
        self.entries = entries
        self.runner = runner
        self.busy = False
        self.shown = set()

    def compose(self):
        yield Static(id="catalog-heading")
        yield OptionList()
        yield Static(id="source")
        yield RichLog(max_lines=1000, markup=False, highlight=False, wrap=True)
        yield Static("Enter kur · x kaldır · Esc kapat")

    def on_mount(self):
        self.catalog = catalog_store.load_catalog()
        self.seen = state.read_seen(self.catalog.modules)
        self.result = catalog_store.RefreshResult(catalog_store.Status.DISABLED)
        self.populate()
        self.refresh_catalog()

    def populate(self):
        self.shown.update(self.catalog.modules)
        self.query_one("#catalog-heading", Static).update(
            "Modüller" if self.entries else "Henüz modül yok. Başlamak için bir modül seç.")
        options = self.query_one(OptionList)
        selected = self.selection()
        options.clear_options()
        for item in sorted(self.catalog.modules.values(), key=lambda m: (not m.featured, m.id)):
            badge = "kurulu" if item.id in self.entries else "yeni" if item.id not in self.seen else ""
            star = "★ " if item.featured else ""
            options.add_option(Option(Text(f"{star}{item.id} · {item.title} {badge}\n{item.description}"),
                                      id=item.id))
        if selected in self.catalog.modules:
            options.highlighted = options.get_option_index(selected)
        elif options.option_count:
            options.highlighted = 0
        self.query_one("#source", Static).update(Text("\n".join(
            catalog_store.footer(self.catalog, self.result.status, self.result.http_code))))

    @work(thread=True, exit_on_error=False)
    def refresh_catalog(self):
        try:
            result = catalog_store.refresh_result()
            catalog = catalog_store.load_catalog()
        except Exception:
            result = catalog_store.RefreshResult(catalog_store.Status.OFFLINE)
            catalog = self.catalog
        self.app.call_from_thread(self.refreshed, result, catalog)

    def refreshed(self, result, catalog):
        if self.is_mounted:
            self.result, self.catalog = result, catalog
            self.populate()

    def selection(self):
        options = self.query_one(OptionList)
        if options.highlighted is not None and options.highlighted < options.option_count:
            return options.get_option_at_index(options.highlighted).id
        return None

    def action_close(self):
        if not self.busy:
            self.dismiss()

    def on_unmount(self):
        state.mark_seen(self.shown)

    def on_option_list_option_selected(self, event):
        key = event.option.id
        if key not in self.entries:
            self.start("add", key)

    def action_remove(self):
        key = self.selection()
        if key in self.entries:
            self.start("remove", key)

    def start(self, action, key):
        if not self.busy:
            self.busy = True
            self.query_one(RichLog).clear()
            self.operation(action, key, self.catalog)

    @work(thread=True, exit_on_error=False)
    def operation(self, action, key, catalog):
        rows = []
        worker = get_current_worker()
        confirmed = False

        def emit(value, **kwargs):
            text = clean(value)
            if not confirmed:
                rows.append(text)
            self.app.call_from_thread(self.query_one(RichLog).write, Text(text))

        def confirm():
            nonlocal confirmed
            done = Event()

            def decided(value):
                nonlocal confirmed
                confirmed = bool(value)
                done.set()

            self.app.call_from_thread(self.app.push_screen, Confirmation(rows.copy()), decided)
            while not done.wait(0.1):
                if worker.is_cancelled:
                    return False
            return confirmed

        def run(argv, **kwargs):
            if kwargs.get("capture_output"):
                return subprocess.run(argv, **kwargs)
            with subprocess.Popen(argv, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                  text=True, errors="replace", **kwargs) as proc:
                for row in proc.stdout:
                    emit(row.rstrip("\n"))
                return subprocess.CompletedProcess(argv, proc.wait())

        try:
            runner = run if self.runner is None else lambda argv, **kw: self.runner(argv, emit=emit, **kw)
            code = installer.manage(action, key, False, self.entries, runner=runner,
                                    emit=emit, confirm=confirm, catalog=catalog)
            if confirmed and code == 0:
                self.app.call_from_thread(self.installed)
        except Exception:
            emit("Paket işlemi gerçekleştirilemedi.")
        finally:
            self.busy = False

    async def installed(self):
        await self.app.sync_sections()
        self.entries = self.app.entries
        self.populate()
