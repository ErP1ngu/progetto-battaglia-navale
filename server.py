"""
server.py - Server TCP per la Battaglia Navale.

Include il protocollo (protocol.py) e le statistiche (stats.py) direttamente
in questo file. Dipende solo da game_logic.py.

Utilizzo:
    python server.py [--host HOST] [--port PORT]
"""

import socket
import threading
import argparse
import logging
import json
import os

from game_logic import (
    FLEET_CONFIG, GRID_SIZE, validate_ship_placement,
    MISS, HIT, SUNK
)

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
def make_wait()                 -> dict: return {"type": MsgType.WAIT}
def make_ships_ok()             -> dict: return {"type": MsgType.SHIPS_OK}
def make_your_turn()            -> dict: return {"type": MsgType.YOUR_TURN}
def make_wait_turn()            -> dict: return {"type": MsgType.WAIT_TURN}
def make_error(reason: str)     -> dict: return {"type": MsgType.ERROR, "reason": reason}
def make_disconnect(name: str)  -> dict: return {"type": MsgType.DISCONNECT, "name": name}
def make_chat(text: str)        -> dict: return {"type": MsgType.CHAT, "text": text}

def make_start(opponent: str, first: bool) -> dict:
    return {"type": MsgType.START, "opponent": opponent, "first": first}

def make_place_ships(grid_size: int, fleet: list) -> dict:
    return {"type": MsgType.PLACE_SHIPS, "grid_size": grid_size, "fleet": fleet}

def make_ships_err(reason: str) -> dict:
    return {"type": MsgType.SHIPS_ERR, "reason": reason}

def make_fire(row: int, col: int) -> dict:
    return {"type": MsgType.FIRE, "row": row, "col": col}

def make_fire_result(row: int, col: int, result: str,
                     sunk_name: str = None, sunk_cells: list = None) -> dict:
    msg = {"type": MsgType.FIRE_RESULT, "row": row, "col": col, "result": result}
    if sunk_name:  msg["sunk_name"]  = sunk_name
    if sunk_cells: msg["sunk_cells"] = sunk_cells
    return msg

def make_opponent_fire(row: int, col: int, result: str,
                       sunk_name: str = None, sunk_cells: list = None) -> dict:
    msg = {"type": MsgType.OPPONENT_FIRE, "row": row, "col": col, "result": result}
    if sunk_name:  msg["sunk_name"]  = sunk_name
    if sunk_cells: msg["sunk_cells"] = sunk_cells
    return msg

def make_chat_msg(sender: str, text: str) -> dict:
    return {"type": MsgType.CHAT_MSG, "sender": sender, "text": text}

def make_win(reason: str = "")  -> dict: return {"type": MsgType.WIN,  "reason": reason}
def make_lose(reason: str = "") -> dict: return {"type": MsgType.LOSE, "reason": reason}


def encode(msg: dict) -> bytes:
    """Serializza un messaggio dict in bytes pronti per l'invio (con \\n finale)."""
    return (json.dumps(msg, ensure_ascii=False) + "\n").encode("utf-8")

def decode(raw: str) -> dict:
    """Deserializza una stringa JSON in dict."""
    return json.loads(raw.strip())


# ===========================================================================
# STATISTICHE (ex stats.py)
# ===========================================================================

STATS_FILE = "battleship_stats.json"
_stats_lock = threading.Lock()   # evita race condition su partite simultanee


def _load_stats() -> dict:
    if not os.path.exists(STATS_FILE):
        return {}
    try:
        with open(STATS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}


def _save_stats(data: dict) -> None:
    try:
        with open(STATS_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except OSError as e:
        print(f"[stats] Impossibile salvare le statistiche: {e}")


def record_win(name: str) -> None:
    with _stats_lock:
        data = _load_stats()
        e = data.setdefault(name, {"wins": 0, "losses": 0, "games": 0})
        e["wins"]  += 1
        e["games"] += 1
        _save_stats(data)


def record_loss(name: str) -> None:
    with _stats_lock:
        data = _load_stats()
        e = data.setdefault(name, {"wins": 0, "losses": 0, "games": 0})
        e["losses"] += 1
        e["games"]  += 1
        _save_stats(data)


def get_stats(name: str) -> dict:
    return _load_stats().get(name, {"wins": 0, "losses": 0, "games": 0})


def all_stats() -> dict:
    return _load_stats()


def win_rate(name: str) -> float:
    s = get_stats(name)
    return s["wins"] / s["games"] if s["games"] else 0.0


# ===========================================================================
# SERVER
# ===========================================================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [SERVER] %(levelname)s %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("server")

DEFAULT_HOST = "0.0.0.0"
DEFAULT_PORT = 5555
FLEET = [{"name": n, "size": s} for n, s in FLEET_CONFIG]


class GameSession:
    """Gestisce l'intera sessione di gioco tra due client connessi."""

    def __init__(self, conn0: socket.socket, addr0,
                       conn1: socket.socket, addr1):
        self.conns  = [conn0, conn1]
        self.addrs  = [addr0, addr1]
        self.names  = ["", ""]
        self.boards = [None, None]
        self.files  = [conn0.makefile("r", encoding="utf-8"),
                       conn1.makefile("r", encoding="utf-8")]

    # ------------------------------------------------------------------
    # Invio / ricezione
    # ------------------------------------------------------------------

    def send(self, idx: int, msg: dict) -> bool:
        try:
            self.conns[idx].sendall(encode(msg))
            return True
        except OSError:
            return False

    def recv(self, idx: int) -> dict | None:
        try:
            line = self.files[idx].readline()
            if not line:
                return None
            return decode(line)
        except (OSError, ValueError):
            return None

    # ------------------------------------------------------------------
    # Fase 1: Handshake
    # ------------------------------------------------------------------

    def phase_hello(self) -> bool:
        for i in range(2):
            msg = self.recv(i)
            if msg is None or msg.get("type") != MsgType.HELLO:
                log.warning("Client %s: atteso HELLO, ricevuto %s", self.addrs[i], msg)
                return False
            self.names[i] = msg.get("name", f"Player{i+1}")
            log.info("Giocatore %d: '%s' da %s", i+1, self.names[i], self.addrs[i])
        return True

    # ------------------------------------------------------------------
    # Fase 2: Posizionamento navi
    # ------------------------------------------------------------------

    def phase_placement(self) -> bool:
        for i in range(2):
            self.send(i, make_place_ships(GRID_SIZE, FLEET))

        results = [None, None]
        errors  = [None, None]

        def collect(idx):
            msg = self.recv(idx)
            if msg is None or msg.get("type") != "PLACE_SHIPS_RESPONSE":
                errors[idx] = "Risposta non valida"
                return
            ok, reason, board = validate_ship_placement(
                msg.get("ships", []), GRID_SIZE, FLEET
            )
            if not ok:
                errors[idx] = reason
            else:
                results[idx] = board

        threads = [threading.Thread(target=collect, args=(i,)) for i in range(2)]
        for t in threads: t.start()
        for t in threads: t.join()

        for i in range(2):
            if errors[i]:
                log.warning("Posizionamento non valido per '%s': %s", self.names[i], errors[i])
                self.send(i, make_ships_err(errors[i]))
                self.send(1 - i, make_error("L'avversario ha inviato un posizionamento non valido."))
                return False
            self.send(i, make_ships_ok())

        self.boards[0], self.boards[1] = results[0], results[1]
        log.info("Posizionamento completato per entrambi i giocatori.")
        return True

    # ------------------------------------------------------------------
    # Fase 3: Gioco
    # ------------------------------------------------------------------

    def phase_game(self) -> None:
        current = 0
        self.send(0, make_start(self.names[1], first=True))
        self.send(1, make_start(self.names[0], first=False))
        log.info("Partita iniziata: '%s' vs '%s'", self.names[0], self.names[1])

        while True:
            opponent = 1 - current
            self.send(current,  make_your_turn())
            self.send(opponent, make_wait_turn())

            msg = self._wait_fire_or_chat(current, opponent)
            if msg is None:
                self._handle_disconnect(current)
                return

            row, col = msg["row"], msg["col"]
            log.info("'%s' spara su (%d,%d)", self.names[current], row, col)

            result, ship = self.boards[opponent].receive_shot(row, col)
            sunk_name  = ship.name  if result == SUNK else None
            sunk_cells = [list(c) for c in ship.cells] if result == SUNK else None

            self.send(current,  make_fire_result(row, col, result, sunk_name, sunk_cells))
            self.send(opponent, make_opponent_fire(row, col, result, sunk_name, sunk_cells))
            log.info("Risultato: %s%s", result, f" ({sunk_name})" if sunk_name else "")

            if self.boards[opponent].all_sunk():
                winner, loser = self.names[current], self.names[opponent]
                log.info("'%s' ha vinto!", winner)
                self.send(current,  make_win(f"Hai affondato tutta la flotta di {loser}!"))
                self.send(opponent, make_lose(f"{winner} ha affondato tutta la tua flotta!"))
                record_win(winner)
                record_loss(loser)
                return

            # Scambia il turno solo se il colpo è andato a vuoto
            if result == MISS:
                current = opponent

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _wait_fire_or_chat(self, current: int, opponent: int) -> dict | None:
        while True:
            msg = self.recv(current)
            if msg is None:
                return None
            mtype = msg.get("type")
            if mtype == MsgType.FIRE:
                return msg
            if mtype == MsgType.CHAT:
                self.send(opponent, make_chat_msg(self.names[current], msg.get("text", "")))

    def _handle_disconnect(self, disconnected_idx: int) -> None:
        name      = self.names[disconnected_idx]
        other_idx = 1 - disconnected_idx
        log.warning("'%s' si è disconnesso durante la partita.", name)
        self.send(other_idx, make_disconnect(name))
        self.send(other_idx, make_win("L'avversario si è disconnesso. Hai vinto!"))
        record_win(self.names[other_idx])

    # ------------------------------------------------------------------
    # Entry point
    # ------------------------------------------------------------------

    def run(self) -> None:
        try:
            if not self.phase_hello():
                return
            self.send(0, make_wait())
            self.send(1, make_wait())
            if not self.phase_placement():
                return
            self.phase_game()
        except Exception as e:
            log.exception("Errore imprevisto nella sessione: %s", e)
        finally:
            for i in range(2):
                try:
                    self.conns[i].close()
                except OSError:
                    pass
            log.info("Sessione terminata: '%s' vs '%s'", self.names[0], self.names[1])


class BattleshipServer:
    """Server TCP che accetta coppie di client e avvia una GameSession per ognuna."""

    def __init__(self, host: str = DEFAULT_HOST, port: int = DEFAULT_PORT):
        self.host = host
        self.port = port

    def start(self) -> None:
        srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        srv.bind((self.host, self.port))
        srv.listen(10)
        log.info("Server in ascolto su %s:%d", self.host, self.port)

        waiting = []

        try:
            while True:
                try:
                    conn, addr = srv.accept()
                except OSError:
                    break
                log.info("Nuova connessione da %s", addr)
                waiting.append((conn, addr))

                if len(waiting) >= 2:
                    (c0, a0), (c1, a1) = waiting.pop(0), waiting.pop(0)
                    session = GameSession(c0, a0, c1, a1)
                    t = threading.Thread(target=session.run, daemon=True)
                    t.start()
                    log.info("Sessione avviata tra %s e %s", a0, a1)

        except KeyboardInterrupt:
            log.info("Interruzione da tastiera.")
        finally:
            srv.close()
            log.info("Server chiuso.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Server Battaglia Navale TCP")
    parser.add_argument("--host", default=DEFAULT_HOST)
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    args = parser.parse_args()
    BattleshipServer(args.host, args.port).start()
