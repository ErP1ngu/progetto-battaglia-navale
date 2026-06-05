# ⚓ Battaglia Navale TCP

Gioco di Battaglia Navale client-server in Python con GUI Tkinter.
Due giocatori si connettono allo stesso server e si sfidano in tempo reale via TCP.

---

## Struttura del progetto

```
battleship/
├── game_logic.py   # Logica pura del gioco (griglia, navi, colpi)
├── server.py       # Server TCP + protocollo + statistiche
├── client.py       # Client TCP con GUI Tkinter + protocollo + statistiche
└── README.md       # Questo file
```

> **Nota:** il progetto è volutamente compatto — solo 3 file Python.
> `server.py` e `client.py` includono ciascuno il protocollo di rete
> e la gestione delle statistiche direttamente al proprio interno,
> senza file separati.

---

## Requisiti

- Python **3.10** o superiore
- Nessuna dipendenza esterna (solo stdlib: `socket`, `threading`, `tkinter`, `json`, `os`, `random`)

---

## Avvio rapido

### 1. Avvia il server

```bash
python server.py
```

Con opzioni esplicite:

```bash
python server.py --host 0.0.0.0 --port 5555
```

Il server rimane in ascolto e abbina automaticamente i giocatori a coppie.
Supporta **più partite simultanee** — ogni coppia gira in un thread separato.

### 2. Avvia due client (su finestre o macchine diverse)

```bash
# Finestra 1
python client.py

# Finestra 2 (stesso PC o IP diverso)
python client.py --host <IP_SERVER>
```

---

## Flusso di una partita

```
Client 1                  Server                  Client 2
   |                        |                        |
   |──── HELLO ────────────►|◄──────────── HELLO ────|
   |◄─── WAIT ──────────────|──── WAIT ─────────────►|
   |◄─── PLACE_SHIPS ───────|──── PLACE_SHIPS ───────►|
   |──── PLACE_SHIPS_RESP ──►|◄─── PLACE_SHIPS_RESP ──|
   |◄─── SHIPS_OK ──────────|──── SHIPS_OK ──────────►|
   |◄─── START ─────────────|──── START ─────────────►|
   |                        |                        |
   |   [turni alternati — chi colpisce ritira]        |
   |   FIRE / FIRE_RESULT / OPPONENT_FIRE             |
   |   CHAT / CHAT_MSG                                |
   |                        |                        |
   |◄─── WIN / LOSE ────────|──── WIN / LOSE ────────►|
```

---

## Regole di gioco

- La griglia è **10×10**.
- Ogni giocatore posiziona la propria flotta prima che la partita inizi.
- I turni sono **alternati**: chi manca (`MISS`) passa il turno all'avversario.
- Chi **colpisce** (`HIT`) o **affonda** (`SUNK`) una nave **ritira subito**.
- Vince chi affonda per primo tutta la flotta avversaria.
- Se un giocatore si disconnette, l'avversario vince automaticamente.

---

## Flotta

| Nave                | Celle |
|---------------------|-------|
| Portaerei           | 5     |
| Corazzata           | 4     |
| Incrociatore        | 3     |
| Sottomarino         | 3     |
| Cacciatorpediniere  | 2     |

Le navi devono rispettare almeno **1 cella di distanza** tra loro (incluse le diagonali).

---

## Schermate del client

1. **Login** — inserimento nome, host e porta. Mostra le statistiche salvate.
2. **Posizionamento** — griglia interattiva con anteprima hover e rotazione (`R`).
   Il pulsante `AUTO POSIZIONA` piazza le navi rimanenti casualmente.
3. **Gioco** — due griglie affiancate (la tua flotta + la flotta nemica) e chat integrata.
4. **Fine partita** — risultato, statistiche aggiornate, pulsante per nuova partita.

---

## Chat

Durante la partita entrambi i giocatori possono scrivere messaggi in qualsiasi momento
senza interrompere il gioco. Il server li inoltra all'avversario in tempo reale.

---

## Statistiche

Le statistiche vengono salvate automaticamente in `battleship_stats.json`
nella stessa cartella del server, al termine di ogni partita.

```json
{
  "Alice": { "wins": 5, "losses": 3, "games": 8 },
  "Bob":   { "wins": 2, "losses": 4, "games": 6 }
}
```

Vengono mostrate nella schermata di login e aggiornate nella schermata di fine partita.

---

## Architettura

### `game_logic.py`

- **`Ship`**: dataclass con nome, dimensione, celle occupate (`cells`) e celle colpite (`hits`).
- **`Board`**: griglia N×N. Gestisce posizionamento navi, ricezione colpi (`receive_shot`),
  tracciamento dei colpi dati (`record_shot`) e condizione di vittoria (`all_sunk`).
- **`validate_ship_placement()`**: valida il posizionamento ricevuto dal client lato server,
  prevenendo dati malformati o posizionamenti illegali.

### `server.py`

Contiene tre sezioni:

- **Protocollo**: classe `MsgType` con tutte le costanti dei messaggi, funzioni `make_*`
  per costruirli, `encode`/`decode` per serializzarli in JSON con framing `\n`.
- **Statistiche**: funzioni `record_win`, `record_loss`, `get_stats`, `all_stats`, `win_rate`
  con un `threading.Lock` per evitare race condition su partite simultanee.
- **Server**: `BattleshipServer` accetta connessioni e abbina i client a coppie.
  `GameSession` gestisce l'intera sessione in un thread dedicato:
  handshake → posizionamento (parallelo) → loop di gioco.

### `client.py`

Contiene tre sezioni:

- **Protocollo** e **Statistiche**: stesse definizioni di `server.py`, integrate direttamente.
- **`NetworkThread`**: thread daemon che legge dal socket e inserisce i messaggi
  in una `queue.Queue` thread-safe.
- **`GridWidget`**: Canvas Tkinter che disegna la griglia, gestisce hover e click.
- **`BattleshipClient`**: classe principale con le 4 schermate. Il polling dei messaggi
  avviene con `root.after(50, self._poll)` per non bloccare mai il thread GUI.

---

## Comunicazione di rete

Tutti i messaggi viaggiano come **JSON UTF-8 terminato da `\n`** (line-framing).
Questo risolve la natura stream di TCP: `makefile().readline()` legge esattamente
fino al `\n`, quindi una chiamata corrisponde sempre a un messaggio completo.

```python
# Invio
conn.sendall((json.dumps(msg) + "\n").encode("utf-8"))

# Ricezione
line = file_object.readline()
msg  = json.loads(line.strip())
```

---

## Personalizzazione

Tutte le modifiche vanno fatte in `game_logic.py` — è l'unica fonte di verità
per griglia e flotta. Gli altri due file le ricevono dinamicamente.

**Cambiare dimensione della griglia:**
```python
# game_logic.py
GRID_SIZE: int = 8   # default: 10
```

**Aggiungere o rimuovere una nave:**
```python
# game_logic.py
FLEET_CONFIG: List[Tuple[str, int]] = [
    ("Portaerei",          5),
    ("Corazzata",          4),
    ("Incrociatore",       3),
    # ("Sottomarino",      3),  ← basta commentare per rimuoverla
    ("Cacciatorpediniere", 2),
]
```

---

## Note tecniche

- Il server usa `threading` per gestire più sessioni simultanee in modo isolato.
- Il `threading.Lock` su `battleship_stats.json` previene corruzione del file
  quando più partite terminano contemporaneamente.
- Il client non blocca mai il thread GUI: la rete è su un thread separato,
  la comunicazione avviene tramite `queue.Queue`.
- La validazione del posizionamento avviene **lato server** — non ci si fida mai del client.
- Il turno rimane al giocatore che ha colpito (`HIT` o `SUNK`);
  passa all'avversario solo su `MISS`.
