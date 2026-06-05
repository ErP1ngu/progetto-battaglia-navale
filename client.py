"""
client.py - Client TCP con GUI Tkinter per la Battaglia Navale.

Include il protocollo (protocol.py) e le statistiche (stats.py) direttamente
in questo file. Dipende solo da game_logic.py.

Utilizzo:
    python client.py [--host HOST] [--port PORT]
"""

import socket
import threading
import queue
import argparse
import json
import os
import tkinter as tk
from tkinter import messagebox
from typing import Optional, List, Tuple

from game_logic import FLEET_CONFIG, GRID_SIZE, Board, MISS, HIT, SUNK


# ===========================================================================
# PROTOCOLLO (ex protocol.py)
# ===========================================================================

class MsgType:
    HELLO         = "HELLO"
    WAIT          = "WAIT"
    START         = "START"
    YOUR_TURN     = "YOUR_TURN"
    WAIT_TURN     = "WAIT_TURN"
    PLACE_SHIPS   = "PLACE_SHIPS"
    SHIPS_OK      = "SHIPS_OK"
    SHIPS_ERR     = "SHIPS_ERR"
    FIRE          = "FIRE"
    FIRE_RESULT   = "FIRE_RESULT"
    OPPONENT_FIRE = "OPPONENT_FIRE"
    CHAT          = "CHAT"
    CHAT_MSG      = "CHAT_MSG"
    WIN           = "WIN"
    LOSE          = "LOSE"
    ERROR         = "ERROR"
    DISCONNECT    = "DISCONNECT"


def make_hello(name: str)       -> dict: return {"type": MsgType.HELLO, "name": name}
def make_fire(row: int, col: int) -> dict: return {"type": MsgType.FIRE, "row": row, "col": col}
def make_chat(text: str)        -> dict: return {"type": MsgType.CHAT, "text": text}

def encode(msg: dict) -> bytes:
    return (json.dumps(msg, ensure_ascii=False) + "\n").encode("utf-8")

def decode(raw: str) -> dict:
    return json.loads(raw.strip())


# ===========================================================================
# STATISTICHE (ex stats.py)
# ===========================================================================

STATS_FILE = "battleship_stats.json"


def _load_stats() -> dict:
    if not os.path.exists(STATS_FILE):
        return {}
    try:
        with open(STATS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}


def get_stats(name: str) -> dict:
    return _load_stats().get(name, {"wins": 0, "losses": 0, "games": 0})


def all_stats() -> dict:
    return _load_stats()


def win_rate(name: str) -> float:
    s = get_stats(name)
    return s["wins"] / s["games"] if s["games"] else 0.0


# ===========================================================================
# PALETTE COLORI
# ===========================================================================

C = {
    "bg":       "#0a0e1a",
    "panel":    "#111827",
    "border":   "#1e3a5f",
    "accent":   "#00d4ff",
    "accent2":  "#ff6b35",
    "water":    "#0d2137",
    "water_h":  "#1a3a5c",
    "miss":     "#4a5568",
    "hit":      "#f6ad55",
    "sunk":     "#fc5c7d",
    "ship":     "#48bb78",
    "ship_h":   "#68d391",
    "text":     "#e2e8f0",
    "text_dim": "#718096",
    "green":    "#48bb78",
    "red":      "#fc5c7d",
    "yellow":   "#f6e05e",
    "white":    "#ffffff",
    "fog":      "#1a2744",
}

CELL_SIZE    = 42
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 5555


# ===========================================================================
# THREAD DI RETE
# ===========================================================================

class NetworkThread(threading.Thread):
    """Thread dedicato alla ricezione dei messaggi dal server."""

    def __init__(self, conn: socket.socket, msg_queue: queue.Queue):
        super().__init__(daemon=True)
        self.conn  = conn
        self.queue = msg_queue
        self.file  = conn.makefile("r", encoding="utf-8")

    def run(self):
        try:
            for line in self.file:
                line = line.strip()
                if line:
                    try:
                        self.queue.put(decode(line))
                    except ValueError:
                        pass
        except OSError:
            pass
        finally:
            self.queue.put({"type": "__DISCONNECTED__"})


# ===========================================================================
# WIDGET GRIGLIA
# ===========================================================================

class GridWidget(tk.Canvas):
    """Canvas che disegna una griglia di gioco N×N."""

    def __init__(self, parent, size: int = GRID_SIZE, clickable: bool = True, **kw):
        total = size * CELL_SIZE + 24
        kw.pop("bg", None)
        super().__init__(parent, width=total, height=total,
                         bg=C["bg"], highlightthickness=0, **kw)
        self.size      = size
        self.clickable = clickable
        self.offset    = 22
        self._hover    = None
        self._callback = None
        self._hover_cb = None

        self._draw_grid()
        if clickable:
            self.bind("<Motion>",   self._on_motion)
            self.bind("<Button-1>", self._on_click)
            self.bind("<Leave>",    self._on_leave)

    def _draw_grid(self):
        self.delete("all")
        s, o, cs = self.size, self.offset, CELL_SIZE
        total = s * cs + o
        self.create_rectangle(o, o, total, total,
                               fill=C["water"], outline=C["border"], width=2)
        for c in range(s):
            self.create_text(o + c * cs + cs // 2, o // 2,
                             text=chr(65 + c), fill=C["text_dim"],
                             font=("Consolas", 9, "bold"))
        for r in range(s):
            self.create_text(o // 2, o + r * cs + cs // 2,
                             text=str(r + 1), fill=C["text_dim"],
                             font=("Consolas", 9))
        for i in range(s + 1):
            x, y = o + i * cs, o + i * cs
            self.create_line(o, y, o + s * cs, y, fill=C["border"], tags="grid")
            self.create_line(x, o, x, o + s * cs, fill=C["border"], tags="grid")

    def _cell(self, x, y):
        o = self.offset
        r, c = (y - o) // CELL_SIZE, (x - o) // CELL_SIZE
        if 0 <= r < self.size and 0 <= c < self.size:
            return r, c
        return None

    def _cell_rect(self, row, col):
        o = self.offset
        x0, y0 = o + col * CELL_SIZE, o + row * CELL_SIZE
        return x0, y0, x0 + CELL_SIZE, y0 + CELL_SIZE

    def on_click(self, fn):  self._callback = fn
    def on_hover(self, fn):  self._hover_cb = fn

    def paint_cell(self, row, col, color, tag=""):
        x0, y0, x1, y1 = self._cell_rect(row, col)
        tags = ("cell", tag) if tag else ("cell",)
        self.create_rectangle(x0+1, y0+1, x1-1, y1-1,
                               fill=color, outline="", tags=tags)

    def paint_symbol(self, row, col, symbol, color, tag=""):
        x0, y0, x1, y1 = self._cell_rect(row, col)
        tags = ("symbol", tag) if tag else ("symbol",)
        self.create_text((x0+x1)//2, (y0+y1)//2, text=symbol, fill=color,
                         font=("Consolas", 14, "bold"), tags=tags)

    def highlight_cells(self, cells, color, tag="preview"):
        self.delete(tag)
        for r, c in cells:
            x0, y0, x1, y1 = self._cell_rect(r, c)
            self.create_rectangle(x0+1, y0+1, x1-1, y1-1,
                                   fill=color, outline=C["accent"],
                                   width=2, tags=tag)

    def clear_tag(self, tag): self.delete(tag)

    def refresh_board(self, board: Board, show_ships: bool = True):
        self._draw_grid()
        if show_ships:
            for ship in board.ships:
                for (r, c) in ship.cells:
                    self.paint_cell(r, c, C["ship"])
        for (r, c), result in board.shots.items():
            if result == MISS:
                self.paint_cell(r, c, C["miss"])
                self.paint_symbol(r, c, "·", C["text"])
            elif result == HIT:
                self.paint_cell(r, c, C["hit"])
                self.paint_symbol(r, c, "✕", C["white"])
            elif result == SUNK:
                self.paint_cell(r, c, C["sunk"])
                self.paint_symbol(r, c, "✕", C["white"])

    def _on_motion(self, event):
        cell = self._cell(event.x, event.y)
        if cell != self._hover:
            self._hover = cell
            if self._hover_cb and cell:
                self._hover_cb(cell[0], cell[1])

    def _on_click(self, event):
        cell = self._cell(event.x, event.y)
        if cell and self._callback:
            self._callback(cell[0], cell[1])

    def _on_leave(self, event):
        self._hover = None
        self.clear_tag("hover")


# ===========================================================================
# APPLICAZIONE PRINCIPALE
# ===========================================================================

class BattleshipClient:
    """Classe principale del client con GUI Tkinter multi-schermata."""

    def __init__(self, root: tk.Tk, default_host: str, default_port: int):
        self.root         = root
        self.default_host = default_host
        self.default_port = default_port

        self.conn:      Optional[socket.socket] = None
        self.net:       Optional[NetworkThread] = None
        self.mq:        queue.Queue             = queue.Queue()

        self.my_name:   str            = ""
        self.opp_name:  str            = ""
        self.my_board:  Optional[Board] = None
        self.opp_board: Optional[Board] = None
        self.my_turn:   bool           = False

        self.fleet_to_place   = list(FLEET_CONFIG)
        self.current_ship_idx = 0
        self.horizontal       = True
        self.placed_ships     = []

        self._build_login()
        root.after(100, self._poll)

    # ==================================================================
    # Schermata 1: LOGIN
    # ==================================================================

    def _build_login(self):
        self._clear()
        self.root.title("Battaglia Navale")
        self.root.configure(bg=C["bg"])
        self.root.resizable(False, False)

        frame = tk.Frame(self.root, bg=C["bg"])
        frame.pack(expand=True, fill="both", padx=60, pady=40)

        tk.Label(frame, text="⚓", bg=C["bg"], fg=C["accent"],
                 font=("Segoe UI Emoji", 48)).pack(pady=(0, 5))
        tk.Label(frame, text="BATTAGLIA NAVALE", bg=C["bg"], fg=C["accent"],
                 font=("Consolas", 22, "bold")).pack()
        tk.Label(frame, text="GIOCO TCP CLIENT-SERVER", bg=C["bg"], fg=C["text_dim"],
                 font=("Consolas", 9)).pack(pady=(0, 30))

        def lbl(text):
            tk.Label(frame, text=text, bg=C["bg"], fg=C["text_dim"],
                     font=("Consolas", 10), anchor="w").pack(fill="x")

        lbl("NOME GIOCATORE")
        self.name_var = tk.StringVar()
        e1 = tk.Entry(frame, textvariable=self.name_var, bg=C["panel"],
                      fg=C["accent"], insertbackground=C["accent"],
                      font=("Consolas", 13), relief="flat", bd=6)
        e1.pack(fill="x", pady=(2, 14))
        e1.focus()

        lbl("HOST SERVER")
        self.host_var = tk.StringVar(value=self.default_host)
        tk.Entry(frame, textvariable=self.host_var, bg=C["panel"],
                 fg=C["text"], insertbackground=C["accent"],
                 font=("Consolas", 13), relief="flat", bd=6).pack(fill="x", pady=(2, 14))

        lbl("PORTA")
        self.port_var = tk.StringVar(value=str(self.default_port))
        tk.Entry(frame, textvariable=self.port_var, bg=C["panel"],
                 fg=C["text"], insertbackground=C["accent"],
                 font=("Consolas", 13), relief="flat", bd=6).pack(fill="x", pady=(2, 24))

        tk.Button(frame, text="CONNETTI  →",
                  bg=C["accent"], fg=C["bg"],
                  font=("Consolas", 13, "bold"),
                  relief="flat", bd=0, padx=20, pady=10,
                  activebackground=C["accent2"], cursor="hand2",
                  command=self._do_connect).pack(fill="x")

        self.status_lbl = tk.Label(frame, text="", bg=C["bg"], fg=C["text_dim"],
                                   font=("Consolas", 10))
        self.status_lbl.pack(pady=12)

        self._show_stats_preview(frame)
        self.root.bind("<Return>", lambda _: self._do_connect())

    def _show_stats_preview(self, parent):
        all_s = all_stats()
        if not all_s:
            return
        tk.Label(parent, text="── STATISTICHE ──", bg=C["bg"], fg=C["border"],
                 font=("Consolas", 9)).pack(pady=(20, 4))
        for name, s in list(all_s.items())[:5]:
            wr = win_rate(name) * 100
            tk.Label(parent,
                     text=f"{name:<16} V:{s['wins']:>3}  S:{s['losses']:>3}  {wr:.0f}%",
                     bg=C["bg"], fg=C["text_dim"],
                     font=("Consolas", 9)).pack()

    def _do_connect(self):
        name = self.name_var.get().strip()
        if not name:
            self._set_status("Inserisci un nome!", C["red"])
            return
        host = self.host_var.get().strip()
        try:
            port = int(self.port_var.get())
        except ValueError:
            self._set_status("Porta non valida!", C["red"])
            return

        self.my_name = name
        self._set_status("Connessione in corso...", C["yellow"])
        self.root.update()

        try:
            self.conn = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.conn.connect((host, port))
        except OSError as e:
            self._set_status(f"Errore: {e}", C["red"])
            return

        self.net = NetworkThread(self.conn, self.mq)
        self.net.start()
        self._send(make_hello(name))
        self._set_status("Connesso! In attesa dell'avversario...", C["green"])

    def _set_status(self, text: str, color: str = C["text_dim"]):
        if hasattr(self, "status_lbl"):
            self.status_lbl.configure(text=text, fg=color)

    # ==================================================================
    # Schermata 2: POSIZIONAMENTO NAVI
    # ==================================================================

    def _build_placement(self, grid_size: int):
        self._clear()
        self.root.title(f"Battaglia Navale – Posizionamento ({self.my_name})")
        self.root.configure(bg=C["bg"])
        self.my_board  = Board(grid_size)
        self.opp_board = Board(grid_size)
        self.placed_ships.clear()
        self.current_ship_idx = 0
        self.horizontal = True
        self.fleet_to_place = list(FLEET_CONFIG)

        outer = tk.Frame(self.root, bg=C["bg"])
        outer.pack(expand=True, fill="both", padx=20, pady=20)

        tk.Label(outer, text="POSIZIONA LA TUA FLOTTA", bg=C["bg"], fg=C["accent"],
                 font=("Consolas", 16, "bold")).pack(pady=(0, 4))
        tk.Label(outer, text="Click per posizionare · [R] per ruotare",
                 bg=C["bg"], fg=C["text_dim"], font=("Consolas", 10)).pack(pady=(0, 12))

        content = tk.Frame(outer, bg=C["bg"])
        content.pack()

        self.place_grid = GridWidget(content, size=grid_size, clickable=True)
        self.place_grid.pack(side="left", padx=(0, 20))
        self.place_grid.on_click(self._placement_click)
        self.place_grid.on_hover(self._placement_hover)

        side = tk.Frame(content, bg=C["panel"], padx=16, pady=16)
        side.pack(side="left", fill="y")

        tk.Label(side, text="FLOTTA", bg=C["panel"], fg=C["accent"],
                 font=("Consolas", 12, "bold")).pack(anchor="w", pady=(0, 8))

        self.fleet_frame = tk.Frame(side, bg=C["panel"])
        self.fleet_frame.pack(fill="x")
        self._update_fleet_list()

        self.orient_lbl = tk.Label(side, text="↔ ORIZZONTALE",
                                   bg=C["panel"], fg=C["accent2"],
                                   font=("Consolas", 11, "bold"))
        self.orient_lbl.pack(anchor="w", pady=(12, 4))

        tk.Button(side, text="[R] RUOTA",
                  bg=C["border"], fg=C["text"],
                  font=("Consolas", 10), relief="flat", padx=10, pady=6,
                  cursor="hand2",
                  command=self._toggle_orientation).pack(fill="x")

        self.ship_hint = tk.Label(side, text="", bg=C["panel"], fg=C["text"],
                                  font=("Consolas", 10), wraplength=160, justify="left")
        self.ship_hint.pack(anchor="w", pady=(12, 0))
        self._update_ship_hint()

        tk.Button(side, text="AUTO POSIZIONA",
                  bg=C["water"], fg=C["text_dim"],
                  font=("Consolas", 9), relief="flat", padx=8, pady=4,
                  cursor="hand2",
                  command=self._auto_place).pack(fill="x", pady=(14, 0))

        self.root.bind("<r>", lambda _: self._toggle_orientation())
        self.root.bind("<R>", lambda _: self._toggle_orientation())

    def _update_fleet_list(self):
        for w in self.fleet_frame.winfo_children():
            w.destroy()
        for i, (name, size) in enumerate(self.fleet_to_place):
            if i < self.current_ship_idx:
                color, prefix = C["green"], "✓"
            elif i == self.current_ship_idx:
                color, prefix = C["accent"], "▶"
            else:
                color, prefix = C["text_dim"], "·"
            tk.Label(self.fleet_frame,
                     text=f"{prefix} {name} ({'▪'*size})",
                     bg=C["panel"], fg=color,
                     font=("Consolas", 10)).pack(anchor="w", pady=1)

    def _update_ship_hint(self):
        if self.current_ship_idx < len(self.fleet_to_place):
            name, size = self.fleet_to_place[self.current_ship_idx]
            self.ship_hint.configure(text=f"Piazza:\n{name}\n(lunghezza {size})")
        else:
            self.ship_hint.configure(text="Tutte le navi\nposizionate!")

    def _toggle_orientation(self):
        self.horizontal = not self.horizontal
        self.orient_lbl.configure(
            text="↔ ORIZZONTALE" if self.horizontal else "↕ VERTICALE")

    def _get_preview_cells(self, row: int, col: int) -> List[Tuple[int,int]]:
        if self.current_ship_idx >= len(self.fleet_to_place):
            return []
        _, size = self.fleet_to_place[self.current_ship_idx]
        cells = []
        for i in range(size):
            r = row + (0 if self.horizontal else i)
            c = col + (i if self.horizontal else 0)
            if 0 <= r < GRID_SIZE and 0 <= c < GRID_SIZE:
                cells.append((r, c))
        return cells

    def _placement_hover(self, row: int, col: int):
        cells = self._get_preview_cells(row, col)
        if not cells or len(cells) < (self.fleet_to_place[self.current_ship_idx][1]
                                       if self.current_ship_idx < len(self.fleet_to_place) else 0):
            color = C["red"]
        else:
            valid = self.my_board.can_place(cells[0][0], cells[0][1], len(cells), self.horizontal)
            color = C["ship_h"] if valid else C["red"]
        self.place_grid.highlight_cells(cells, color, tag="hover")

    def _placement_click(self, row: int, col: int):
        if self.current_ship_idx >= len(self.fleet_to_place):
            return
        name, size = self.fleet_to_place[self.current_ship_idx]
        ship = self.my_board.place(name, size, row, col, self.horizontal)
        if ship is None:
            return
        self.placed_ships.append({
            "name": name, "size": size,
            "row": row, "col": col,
            "horizontal": self.horizontal
        })
        self.current_ship_idx += 1
        self.place_grid.refresh_board(self.my_board, show_ships=True)
        self._update_fleet_list()
        self._update_ship_hint()
        if self.current_ship_idx >= len(self.fleet_to_place):
            self._send_placement()

    def _auto_place(self):
        """Posiziona automaticamente le navi rimanenti in modo casuale."""
        import random
        for name, size in self.fleet_to_place[self.current_ship_idx:]:
            placed = False
            for _ in range(1000):
                r = random.randint(0, GRID_SIZE - 1)
                c = random.randint(0, GRID_SIZE - 1)
                h = random.choice([True, False])
                ship = self.my_board.place(name, size, r, c, h)
                if ship:
                    self.placed_ships.append({
                        "name": name, "size": size,
                        "row": r, "col": c, "horizontal": h
                    })
                    self.current_ship_idx += 1
                    placed = True
                    break
            if not placed:
                messagebox.showerror("Errore", f"Impossibile posizionare {name}")
                return
        self.place_grid.refresh_board(self.my_board, show_ships=True)
        self._update_fleet_list()
        self._update_ship_hint()
        self._send_placement()

    def _send_placement(self):
        self._send({"type": "PLACE_SHIPS_RESPONSE", "ships": self.placed_ships})
        if hasattr(self, "ship_hint"):
            self.ship_hint.configure(text="In attesa\ndell'avversario...", fg=C["yellow"])

    # ==================================================================
    # Schermata 3: GIOCO
    # ==================================================================

    def _build_game(self):
        self._clear()
        self.root.title(f"Battaglia Navale – {self.my_name} vs {self.opp_name}")
        self.root.configure(bg=C["bg"])

        hdr = tk.Frame(self.root, bg=C["bg"])
        hdr.pack(fill="x", padx=20, pady=(16, 0))
        tk.Label(hdr, text=f"⚓  {self.my_name}  vs  {self.opp_name}",
                 bg=C["bg"], fg=C["accent"],
                 font=("Consolas", 14, "bold")).pack(side="left")
        self.turn_lbl = tk.Label(hdr, text="", bg=C["bg"], fg=C["yellow"],
                                 font=("Consolas", 12, "bold"))
        self.turn_lbl.pack(side="right")

        grids_frame = tk.Frame(self.root, bg=C["bg"])
        grids_frame.pack(padx=20, pady=10)

        # Colonna griglia sinistra (la tua)
        f_my = tk.Frame(grids_frame, bg=C["bg"])
        f_my.pack(side="left", padx=10)
        tk.Label(f_my, text="LA TUA FLOTTA", bg=C["bg"], fg=C["text_dim"],
                 font=("Consolas", 10, "bold")).pack(pady=(0, 4))
        self.my_grid = GridWidget(f_my, size=GRID_SIZE, clickable=False)
        self.my_grid.pack()

        # Colonna griglia destra (nemica)
        f_opp = tk.Frame(grids_frame, bg=C["bg"])
        f_opp.pack(side="left", padx=10)
        tk.Label(f_opp, text="FLOTTA NEMICA", bg=C["bg"], fg=C["text_dim"],
                 font=("Consolas", 10, "bold")).pack(pady=(0, 4))
        self.opp_grid = GridWidget(f_opp, size=GRID_SIZE, clickable=True)
        self.opp_grid.pack()

        self.my_grid.refresh_board(self.my_board,   show_ships=True)
        self.opp_grid.refresh_board(self.opp_board, show_ships=False)
        self.opp_grid.on_click(self._fire)
        self.opp_grid.on_hover(self._hover_enemy)

        # Chat
        chat_frame = tk.Frame(self.root, bg=C["panel"])
        chat_frame.pack(fill="x", padx=20, pady=(0, 16))
        tk.Label(chat_frame, text="CHAT", bg=C["panel"], fg=C["accent"],
                 font=("Consolas", 9, "bold")).pack(anchor="w", padx=8, pady=(6, 0))
        self.chat_box = tk.Text(chat_frame, height=5, bg=C["water"], fg=C["text"],
                                font=("Consolas", 10), state="disabled",
                                relief="flat", bd=0, padx=6, pady=4)
        self.chat_box.pack(fill="x", padx=8)
        inp = tk.Frame(chat_frame, bg=C["panel"])
        inp.pack(fill="x", padx=8, pady=(4, 8))
        self.chat_var = tk.StringVar()
        chat_entry = tk.Entry(inp, textvariable=self.chat_var,
                              bg=C["water"], fg=C["text"],
                              insertbackground=C["accent"],
                              font=("Consolas", 10), relief="flat", bd=4)
        chat_entry.pack(side="left", fill="x", expand=True)
        chat_entry.bind("<Return>", lambda _: self._send_chat())
        tk.Button(inp, text="INVIA", bg=C["accent"], fg=C["bg"],
                  font=("Consolas", 9, "bold"), relief="flat", bd=0, padx=10,
                  cursor="hand2", command=self._send_chat).pack(side="left", padx=(4, 0))

        self._update_turn_label()

    def _update_turn_label(self):
        if self.my_turn:
            self.turn_lbl.configure(text="🎯 IL TUO TURNO", fg=C["green"])
        else:
            self.turn_lbl.configure(text=f"⏳ TURNO DI {self.opp_name}", fg=C["text_dim"])

    def _hover_enemy(self, row: int, col: int):
        if not self.my_turn or (row, col) in self.opp_board.shots:
            return
        self.opp_grid.highlight_cells([(row, col)], C["accent2"], tag="hover")

    def _fire(self, row: int, col: int):
        if not self.my_turn or (row, col) in self.opp_board.shots:
            return
        self.my_turn = False
        self._update_turn_label()
        self._send(make_fire(row, col))

    def _send_chat(self):
        text = self.chat_var.get().strip()
        if not text:
            return
        self._send(make_chat(text))
        self._append_chat(f"Tu: {text}", C["accent"])
        self.chat_var.set("")

    def _append_chat(self, text: str, color: str = C["text"]):
        self.chat_box.configure(state="normal")
        self.chat_box.insert("end", text + "\n")
        self.chat_box.configure(state="disabled")
        self.chat_box.see("end")

    def _apply_fire_result(self, row, col, result, sunk_cells=None, on_own=False):
        board  = self.my_board  if on_own else self.opp_board
        widget = self.my_grid   if on_own else self.opp_grid
        if result == MISS:
            board.shots[(row, col)] = MISS
            widget.paint_cell(row, col, C["miss"])
            widget.paint_symbol(row, col, "·", C["text"])
        elif result in (HIT, SUNK):
            board.shots[(row, col)] = result
            widget.paint_cell(row, col, C["hit"] if result == HIT else C["sunk"])
            widget.paint_symbol(row, col, "✕", C["white"])
            if result == SUNK and sunk_cells:
                for cell in sunk_cells:
                    r, c = cell[0], cell[1]
                    board.shots[(r, c)] = SUNK
                    widget.paint_cell(r, c, C["sunk"])
                    widget.paint_symbol(r, c, "✕", C["white"])

    # ==================================================================
    # Schermata 4: FINE PARTITA
    # ==================================================================

    def _build_end(self, won: bool, reason: str):
        self._clear()
        self.root.title("Battaglia Navale – Fine partita")
        self.root.configure(bg=C["bg"])

        frame = tk.Frame(self.root, bg=C["bg"])
        frame.pack(expand=True, fill="both", padx=60, pady=40)

        emoji = "🏆" if won else "💥"
        title = "VITTORIA!" if won else "SCONFITTA"
        color = C["green"] if won else C["red"]

        tk.Label(frame, text=emoji, bg=C["bg"], fg=color,
                 font=("Segoe UI Emoji", 52)).pack(pady=(0, 8))
        tk.Label(frame, text=title, bg=C["bg"], fg=color,
                 font=("Consolas", 26, "bold")).pack()
        tk.Label(frame, text=reason, bg=C["bg"], fg=C["text_dim"],
                 font=("Consolas", 11), wraplength=320).pack(pady=(8, 24))

        s  = get_stats(self.my_name)
        wr = win_rate(self.my_name) * 100
        tk.Label(frame,
                 text=(f"STATISTICHE DI {self.my_name}\n"
                       f"Partite: {s['games']}   Vittorie: {s['wins']}   "
                       f"Sconfitte: {s['losses']}   Win rate: {wr:.0f}%"),
                 bg=C["panel"], fg=C["text"],
                 font=("Consolas", 10), padx=16, pady=12,
                 justify="center").pack(fill="x", pady=(0, 24))

        btn_f = tk.Frame(frame, bg=C["bg"])
        btn_f.pack()
        tk.Button(btn_f, text="NUOVA PARTITA",
                  bg=C["accent"], fg=C["bg"],
                  font=("Consolas", 12, "bold"),
                  relief="flat", padx=20, pady=10, cursor="hand2",
                  command=self._new_game).pack(side="left", padx=6)
        tk.Button(btn_f, text="ESCI",
                  bg=C["panel"], fg=C["text"],
                  font=("Consolas", 12),
                  relief="flat", padx=20, pady=10, cursor="hand2",
                  command=self.root.quit).pack(side="left", padx=6)

    def _new_game(self):
        if self.conn:
            try:
                self.conn.close()
            except OSError:
                pass
        self.conn = None
        self.net  = None
        self.mq   = queue.Queue()
        self._build_login()
        self.root.after(100, self._poll)

    # ==================================================================
    # Polling messaggi
    # ==================================================================

    def _poll(self):
        try:
            while True:
                msg = self.mq.get_nowait()
                self._dispatch(msg)
        except queue.Empty:
            pass
        self.root.after(50, self._poll)

    def _dispatch(self, msg: dict):
        mtype = msg.get("type")

        if mtype == "__DISCONNECTED__":
            messagebox.showwarning("Connessione persa", "Connessione al server persa.")
            self._build_login()

        elif mtype == MsgType.WAIT:
            self._set_status("In attesa dell'avversario...", C["yellow"])

        elif mtype == MsgType.PLACE_SHIPS:
            self._build_placement(msg.get("grid_size", 10))

        elif mtype == MsgType.SHIPS_OK:
            if hasattr(self, "ship_hint"):
                self.ship_hint.configure(text="In attesa\ndell'avversario...", fg=C["yellow"])

        elif mtype == MsgType.SHIPS_ERR:
            messagebox.showerror("Errore posizionamento", msg.get("reason", ""))

        elif mtype == MsgType.START:
            self.opp_name = msg.get("opponent", "Avversario")
            self.my_turn  = msg.get("first", True)
            self._build_game()

        elif mtype == MsgType.YOUR_TURN:
            self.my_turn = True
            if hasattr(self, "turn_lbl"):
                self._update_turn_label()

        elif mtype == MsgType.WAIT_TURN:
            self.my_turn = False
            if hasattr(self, "turn_lbl"):
                self._update_turn_label()

        elif mtype == MsgType.FIRE_RESULT:
            self._apply_fire_result(
                msg["row"], msg["col"], msg["result"],
                msg.get("sunk_cells"), on_own=False)

        elif mtype == MsgType.OPPONENT_FIRE:
            self._apply_fire_result(
                msg["row"], msg["col"], msg["result"],
                msg.get("sunk_cells"), on_own=True)
            if hasattr(self, "turn_lbl"):
                self._update_turn_label()

        elif mtype == MsgType.CHAT_MSG:
            if hasattr(self, "chat_box"):
                self._append_chat(
                    f"{msg.get('sender','?')}: {msg.get('text','')}",
                    C["accent2"])

        elif mtype == MsgType.WIN:
            self._build_end(True,  msg.get("reason", "Hai vinto!"))

        elif mtype == MsgType.LOSE:
            self._build_end(False, msg.get("reason", "Hai perso!"))

        elif mtype == MsgType.DISCONNECT:
            if hasattr(self, "chat_box"):
                self._append_chat(f"⚠ {msg.get('name','Avversario')} si è disconnesso.", C["red"])

        elif mtype == MsgType.ERROR:
            messagebox.showerror("Errore", msg.get("reason", "Errore sconosciuto."))

    # ==================================================================
    # Utility
    # ==================================================================

    def _send(self, msg: dict):
        if self.conn:
            try:
                self.conn.sendall(encode(msg))
            except OSError:
                pass

    def _clear(self):
        for w in self.root.winfo_children():
            w.destroy()
        self.root.unbind("<Return>")
        self.root.unbind("<r>")
        self.root.unbind("<R>")


# ===========================================================================
# ENTRY POINT
# ===========================================================================

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Client Battaglia Navale TCP")
    parser.add_argument("--host", default=DEFAULT_HOST)
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    args = parser.parse_args()

    root = tk.Tk()
    root.minsize(400, 500)
    BattleshipClient(root, args.host, args.port)
    root.mainloop()
