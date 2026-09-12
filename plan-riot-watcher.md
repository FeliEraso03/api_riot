# Riot Account Watcher — Plan de implementación

Monitor simple que corre en **GitHub Actions** cada 15 minutos, comprueba el estado de una cuenta de Riot/**Valorant** (Riot ID, shard, nivel, rango, última partida) y envía una alerta por **Telegram** si detecta un cambio.

---

## 1. Arquitectura (simplificada, sin servidor)

```
GitHub Actions (cron cada 15 min)
        │
        ├─ 1. Ejecuta script (Python)
        │     ├─ Llama a la Riot API (Account-V1) + HenrikDev API (Valorant)
        │     ├─ Lee el último estado guardado (state.json en el propio repo)
        │     ├─ Compara campo a campo
        │     └─ Si hay cambio → dispara alerta por Telegram (bot propio)
        │
        └─ 2. Si hubo cambio: commitea el nuevo state.json al repo
```

No hace falta servidor, base de datos externa ni backend. Todo vive en un repo de GitHub:
- El propio repo hace de "servidor" (vía Actions).
- El propio repo hace de "base de datos" (un archivo `state.json` versionado).
- Un bot de Telegram hace de canal de alertas.
- `index.html` + GitHub Pages sirve de interfaz web de solo lectura.

**Coste: 0€.**

---

## 2. Requisitos previos

### 2.1 API Key de Riot (opcional)
- **Opcional desde la migración a HenrikDev**: sin ella, todo el monitoreo (Riot ID incluido) corre solo con `HENRIK_API_KEY`.
- Si la configuras, añade detección del shard activo vía `Account-V1 active-shards`. La dev key caduca cada 24h; si caduca, el workflow avisa por Telegram (error 403) pero el resto del monitoreo seguiría funcionando si también hay key de Henrik.

### 2.2 Telegram — bot propio (gratis)
1. En Telegram, habla con **@BotFather** → `/newbot` → te da un **token HTTP API**.
2. Abre tu bot (`t.me/<TuBot>`) y envíale `/start` — imprescindible para que el bot pueda escribirte.
3. El script resuelve el `chat_id` automáticamente vía `getUpdates`. Si hay varios chats, fija el secreto `TELEGRAM_CHAT_ID`.

### 2.3 HenrikDev API (opcional, para datos de Valorant)
- La API oficial de Riot no publica nivel/rango/partidas de Valorant con dev key.
- [api.henrikdev.xyz](https://api.henrikdev.xyz) (API no oficial) sí: nivel de cuenta, rango actual (MMR) y última partida.
- Regístrate con Discord → te dan una key gratuita. Sin ella, el watcher solo vigila Riot ID y shard.

### 2.4 Datos de tu cuenta
- Tu **Riot ID** (`gameName#tagLine`) y tu **PUUID** (fijo, se obtiene con una llamada a Account-V1 `by-riot-id`).

---

## 3. Estructura del repositorio

```
riot-watcher/
├── .github/
│   └── workflows/
│       └── check.yml        # workflow programado cada 15 min
├── check.py                 # script de comprobación
├── index.html               # interfaz web (GitHub Pages) que lee state.json
├── state.json               # último estado conocido (se autoactualiza)
├── .env                     # secretos para ejecución local (gitignored)
└── requirements.txt
```

---

## 4. El estado que se guarda (`state.json`)

```json
{
  "puuid": "PUUID_FIJO",
  "riot_id": "wons#UwU",
  "shard": "latam",
  "account_level": 35,
  "rank": "Gold 1",
  "rr": 18,
  "peak_rank": "Gold 1",
  "rank_icon": "https://media.valorant-api.com/.../smallicon.png",
  "card_id": "d010298a-...",
  "card_url": "https://media.valorant-api.com/.../smallart.png",
  "last_match_id": "95551c80-...",
  "last_match_map": "Summit",
  "last_match_queue": "Competitive",
  "last_match_agent": "Cypher",
  "last_match_kda": "19/17/8",
  "last_match_start": "2026-09-08T23:19:21Z",
  "checked_at": "2026-09-12T15:00:00Z"
}
```

Todos los campos salvo `puuid`, `riot_id`, `shard` y `checked_at` solo aparecen si hay `HENRIK_API_KEY` configurada. Los campos `last_match_*`, `card_url` y `rank_icon` son de solo visualización (no generan alerta propia).

---

## 5. Script de comprobación (`check.py`) — lógica

1. Leer `state.json` del repo (estado anterior). Carga `.env` si existe (para ejecución local).
2. Llamar a Riot API usando el `puuid` guardado:
   - `Account-V1 by-puuid` → nombre/tag actuales.
   - `Account-V1 active-shards (val)` → shard donde juega.
3. Si hay `HENRIK_API_KEY`, llamar a HenrikDev:
   - `v1/account/{name}/{tag}` → nivel de cuenta y player card.
   - `v2/mmr/{shard}/{name}/{tag}` → rango actual, RR y rango máximo.
   - `v4/matches/{shard}/pc/{name}/{tag}?size=1` → última partida (mapa, cola, agente, KDA).
4. Comparar cada campo con el estado anterior.
5. Si algo cambió: construir mensaje, enviarlo por Telegram (`sendMessage`), y escribir el nuevo `state.json`.
6. Si no cambió nada: solo actualizar `checked_at`.
7. Error 403 de Riot (key caducada) → alerta distinta por Telegram ("⚠️ Renueva la API key de Riot").

---

## 6. Workflow de GitHub Actions (`check.yml`) — lógica

- **Disparador:** `schedule` con cron `*/15 * * * *` + `workflow_dispatch` para ejecución manual.
- **Pasos:** checkout → setup Python → instalar `requests` → ejecutar `check.py` con secretos como env → commit/push de `state.json` si cambió (`GITHUB_TOKEN`).
- **Secretos** (Settings → Secrets and variables → Actions):
  - `TELEGRAM_BOT_TOKEN`
  - `HENRIK_API_KEY` (principal fuente de datos)
  - `RIOT_API_KEY` (opcional: añade detección de shard)
  - `TELEGRAM_CHAT_ID` (opcional)
- **Variables:** `RIOT_REGION` (por defecto `americas`).

---

## 7. Limitaciones a tener en cuenta

| Limitación | Detalle | Mitigación |
|---|---|---|
| Cron de GitHub Actions no es exacto | Puede retrasarse unos minutos en horas de mucha carga | Aceptable para este caso de uso |
| Workflows programados se desactivan tras ~60 días sin actividad | Si el repo no recibe ningún commit en 2 meses, el cron se pausa solo | El commit de `checked_at` cada ejecución ya mantiene el repo activo |
| Riot API key de desarrollo caduca cada 24h | Se detecta como error 403 | Alerta por Telegram cuando pasa, o usar Personal Key definitiva |
| VAL-MATCH-V1 no disponible con dev key | 403 en todos los shards | HenrikDev API para nivel/rango/partidas hasta que aprueben la app |
| HenrikDev es no oficial | Rate limits y posibles caídas | Es opcional: sin key el watcher sigue vigilando Riot ID y shard |
| Bot de Telegram no puede iniciar chats | Necesita que el usuario envíe /start primero | Documentado en 2.2; el script auto-resuelve el chat_id |

---

## 8. Pasos de implementación (checklist)

- [x] Crear cuenta de desarrollador en Riot y obtener API key.
- [ ] Registrar Personal App en Riot para key permanente (paralelo, tarda ~2 semanas).
- [x] Crear bot de Telegram con @BotFather y guardar el token.
- [ ] Enviar `/start` al bot desde tu Telegram (necesario para que pueda escribirte).
- [x] Obtener el PUUID con Account-V1 `by-riot-id`.
- [x] Registrarse en henrikdev.xyz y obtener su API key.
- [x] Escribir `check.py` con la lógica del punto 5.
- [x] Escribir `check.yml` con la lógica del punto 6.
- [x] Crear `index.html` + activar GitHub Pages (Settings → Pages → branch `master`, root).
- [ ] Añadir los secretos en la configuración del repo.
- [ ] Subir el repo a GitHub.
- [ ] Probar manualmente el workflow ("Run workflow") antes de dejarlo en automático.
- [ ] Forzar un cambio de prueba (editar `state.json` a mano) para confirmar que llega la alerta de Telegram.
