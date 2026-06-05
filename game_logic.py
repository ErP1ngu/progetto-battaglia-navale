"""
game_logic.py - Logica pura della Battaglia Navale.

Contiene:
  - Ship: rappresenta una nave con posizione, orientamento, stato dei colpi.
  - Board: rappresenta la griglia di gioco (propria o avversaria).
  - place_ship / validate_placement: utility per il posizionamento.

Tutto questo modulo è indipendente dalla rete e dalla GUI.
"""

from dataclasses import dataclass, field
from typing import List, Tuple, Optional

# ---------------------------------------------------------------------------
# Configurazione della flotta e della griglia
# ---------------------------------------------------------------------------

GRID_SIZE: int = 10  # griglia 10x10

# Flotta standard: (nome, dimensione)
FLEET_CONFIG: List[Tuple[str, int]] = [
    ("Portaerei",   5),
    ("Corazzata",   4),
    ("Incrociatore",3),
    ("Sottomarino", 3),
    ("Cacciatorpediniere", 2),
]

# Risultati possibili di un colpo
MISS  = "miss"
HIT   = "hit"
SUNK  = "sunk"


# ---------------------------------------------------------------------------
# Classe Ship
# ---------------------------------------------------------------------------

@dataclass
class Ship:
    """
    Rappresenta una nave posizionata sulla griglia.

    Attributes:
        name:        Nome della nave (es. "Portaerei").
        size:        Numero di celle occupate.
        cells:       Lista di (row, col) occupate dalla nave.
        hits:        Insieme delle celle già colpite.
    """
    name:  str
    size:  int
    cells: List[Tuple[int, int]] = field(default_factory=list)
    hits:  set = field(default_factory=set)

    def is_sunk(self) -> bool:
        """Restituisce True se tutte le celle sono state colpite."""
        return len(self.hits) == self.size

    def receive_hit(self, row: int, col: int) -> bool:
        """
        Registra un colpo sulla cella (row, col).
        Restituisce True se la cella appartiene a questa nave.
        """
        if (row, col) in self.cells:
            self.hits.add((row, col))
            return True
        return False


# ---------------------------------------------------------------------------
# Classe Board
# ---------------------------------------------------------------------------

class Board:
    """
    Griglia di gioco.

    Può essere usata sia per la propria griglia (con le navi posizionate)
    sia per tracciare i colpi dati all'avversario.

    Attributes:
        size:    Dimensione della griglia (lato).
        ships:   Lista di Ship posizionate (vuota per la griglia avversaria).
        shots:   Dizionario {(row,col): result} dei colpi effettuati/ricevuti.
    """

    def __init__(self, size: int = GRID_SIZE):
        self.size  = size
        self.ships: List[Ship]          = []
        self.shots: dict                = {}   # (row,col) → MISS/HIT/SUNK

    # ------------------------------------------------------------------
    # Posizionamento navi
    # ------------------------------------------------------------------

    def can_place(self, row: int, col: int, size: int, horizontal: bool) -> bool:
        """
        Verifica se una nave di `size` celle può essere posizionata a partire
        da (row, col) con l'orientamento dato, rispettando i bordi e le
        distanze minime dalle navi già piazzate (incluse le diagonali).
        """
        cells = self._compute_cells(row, col, size, horizontal)
        if cells is None:
            return False
        occupied = self._occupied_with_border()
        for c in cells:
            if c in occupied:
                return False
        return True

    def place(self, name: str, size: int, row: int, col: int, horizontal: bool) -> Optional[Ship]:
        """
        Piazza una nave sulla griglia. Restituisce il Ship creato oppure None
        se il posizionamento non è valido.
        """
        if not self.can_place(row, col, size, horizontal):
            return None
        cells = self._compute_cells(row, col, size, horizontal)
        ship  = Ship(name=name, size=size, cells=cells)
        self.ships.append(ship)
        return ship

    # ------------------------------------------------------------------
    # Ricezione di un colpo (lato difensore)
    # ------------------------------------------------------------------

    def receive_shot(self, row: int, col: int) -> Tuple[str, Optional[Ship]]:
        """
        Elabora un colpo in arrivo sulla propria griglia.

        Restituisce (result, ship) dove:
          - result: MISS, HIT, o SUNK
          - ship:   oggetto Ship se colpita/affondata, None altrimenti
        """
        if (row, col) in self.shots:
            return self.shots[(row, col)], None

        for ship in self.ships:
            if ship.receive_hit(row, col):
                result = SUNK if ship.is_sunk() else HIT
                self.shots[(row, col)] = result
                if result == SUNK:
                    for cell in ship.cells:
                        self.shots[cell] = SUNK
                return result, ship

        self.shots[(row, col)] = MISS
        return MISS, None

    # ------------------------------------------------------------------
    # Registrazione di colpi sull'avversario (lato attaccante)
    # ------------------------------------------------------------------

    def record_shot(self, row: int, col: int, result: str):
        """
        Registra sulla griglia avversaria il risultato di un nostro colpo.
        """
        self.shots[(row, col)] = result

    # ------------------------------------------------------------------
    # Condizione di vittoria
    # ------------------------------------------------------------------

    def all_sunk(self) -> bool:
        """Restituisce True se tutte le navi sono affondate."""
        return all(ship.is_sunk() for ship in self.ships)

    # ------------------------------------------------------------------
    # Utility interne
    # ------------------------------------------------------------------

    def _compute_cells(self, row: int, col: int, size: int, horizontal: bool) -> Optional[List[Tuple[int,int]]]:
        """Calcola le celle occupate; restituisce None se fuori griglia."""
        cells = []
        for i in range(size):
            r = row + (0 if horizontal else i)
            c = col + (i if horizontal else 0)
            if not (0 <= r < self.size and 0 <= c < self.size):
                return None
            cells.append((r, c))
        return cells

    def _occupied_with_border(self) -> set:
        """
        Restituisce tutte le celle già occupate più il loro bordo (8 direzioni),
        per garantire la distanza minima di 1 cella tra le navi.
        """
        occupied = set()
        for ship in self.ships:
            for (r, c) in ship.cells:
                for dr in (-1, 0, 1):
                    for dc in (-1, 0, 1):
                        occupied.add((r + dr, c + dc))
        return occupied

    def cell_state(self, row: int, col: int) -> Optional[str]:
        """Restituisce lo stato di una cella (MISS/HIT/SUNK) o None."""
        return self.shots.get((row, col))

    def ship_at(self, row: int, col: int) -> Optional[Ship]:
        """Restituisce la nave nella cella (row,col), o None."""
        for ship in self.ships:
            if (row, col) in ship.cells:
                return ship
        return None


# ---------------------------------------------------------------------------
# Validazione del posizionamento ricevuto dal client
# ---------------------------------------------------------------------------

def validate_ship_placement(data: list, grid_size: int, fleet: list) -> Tuple[bool, str, Optional[Board]]:
    """
    Valida il posizionamento delle navi ricevuto dal client.

    Args:
        data:      Lista di dict {"name", "size", "row", "col", "horizontal"}
        grid_size: Dimensione della griglia
        fleet:     Configurazione attesa della flotta (lista di dict {"name","size"})

    Returns:
        (ok, reason, board) dove ok=True se valido, reason descrive l'errore,
        board è il Board costruito (None se non valido).
    """
    if len(data) != len(fleet):
        return False, f"Attese {len(fleet)} navi, ricevute {len(data)}", None

    board = Board(grid_size)
    expected = {item["name"]: item["size"] for item in fleet}
    placed_names = set()

    for item in data:
        name       = item.get("name")
        size       = item.get("size")
        row        = item.get("row")
        col        = item.get("col")
        horizontal = item.get("horizontal", True)

        if name not in expected:
            return False, f"Nome nave sconosciuto: {name}", None
        if expected[name] != size:
            return False, f"Dimensione errata per {name}", None
        if name in placed_names:
            return False, f"Nave duplicata: {name}", None

        ship = board.place(name, size, row, col, horizontal)
        if ship is None:
            return False, f"Posizionamento non valido per {name} ({row},{col})", None

        placed_names.add(name)

    return True, "", board
