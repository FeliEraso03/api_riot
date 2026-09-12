# Riot Watcher

Monitor de una cuenta de Valorant que corre en **GitHub Actions** cada 15 minutos. Compara el estado actual (Riot ID, nivel, rango, RR, última partida, player card) contra `state.json` y envía una alerta por **Telegram** cuando algo cambia. Incluye una página de estado estática (`index.html`) pensada para GitHub Pages.

Sin servidor, sin base de datos: el repo hace de ambos.

## Cómo funciona

- `check.py` consulta la cuenta por **PUUID fijo** (nunca por Riot ID, que puede cambiar).
- Fuentes de datos:
  - **HenrikDev API** (`HENRIK_API_KEY`): nivel, rango, RR, rango máximo, player card, última partida (mapa, cola, agente, KDA, resultado). Fuente principal.
  - **Riot API oficial** (`RIOT_API_KEY`, opcional): shard activo. Sin ella el watcher funciona igualmente solo con Henrik.
- Si algo cambió → mensaje de Telegram vía bot propio.
- El workflow commitea el `state.json` actualizado, lo que también mantiene activo el cron (GitHub pausa schedules tras ~60 días sin commits).

## Setup

### 1. Obtener tu PUUID (una sola vez)

El PUUID es el identificador fijo de la cuenta — no cambia aunque cambies de nombre. Se obtiene con una llamada a Account-V1:

```
GET https://americas.api.riotgames.com/riot/account/v1/accounts/by-riot-id/{gameName}/{tagLine}
Header: X-Riot-Token: {RIOT_API_KEY}
```

Ejemplo para `wons#UwU`:

```bash
curl -H "X-Riot-Token: $RIOT_API_KEY" \
  "https://americas.api.riotgames.com/riot/account/v1/accounts/by-riot-id/wons/UwU"
```

El campo `"puuid"` de la respuesta es el valor que va en el secret `RIOT_PUUID`.

> Si no tienes API key de Riot a mano, también aparece como `puuid` en la respuesta de HenrikDev:
> `GET https://api.henrikdev.xyz/valorant/v1/account/{gameName}/{tag}` — pero en formato UUID
> (distinto al de Riot; va en el secret `HENRIK_PUUID`).
>
> Ningún PUUID se guarda en `state.json` ni se sirve en la web: viven solo en secrets.

### 2. Bot de Telegram

1. Habla con **@BotFather** → `/newbot` → guarda el token.
2. Abre tu bot y envíale `/start` (imprescindible: el bot no puede iniciar chats).
3. El `chat_id` se resuelve automáticamente vía `getUpdates`; si el bot habla con varios chats, fija `TELEGRAM_CHAT_ID`.

### 3. Secretos del repo

Settings → Secrets and variables → Actions:

| Secret | Obligatorio | Descripción |
|---|---|---|
| `RIOT_PUUID` | Sí | PUUID fijo de la cuenta (ver paso 1) |
| `HENRIK_PUUID` | Recomendado | PUUID en formato UUID de HenrikDev (ver paso 1) |
| `TELEGRAM_BOT_TOKEN` | Sí | Token del bot de @BotFather |
| `HENRIK_API_KEY` | Recomendado | Datos de Valorant (nivel, rango, partidas) |
| `RIOT_API_KEY` | No | Añade detección del shard activo |
| `TELEGRAM_CHAT_ID` | No | Forzar un chat concreto |

Variables (opcional): `RIOT_REGION` (default `americas`).

### 4. Activar

- Sube el repo a GitHub.
- Settings → Pages → "Deploy from a branch" → `master` / root (la web queda en `https://<usuario>.github.io/<repo>/`, requiere repo público).
- Actions → "Riot Watcher" → **Run workflow** para probar.

## Ejecución local

Crea un `.env` (gitignored) con los mismos nombres de variable y ejecuta:

```bash
pip install -r requirements.txt
python check.py
```

## Estructura

```
├── .github/workflows/check.yml   # cron */15 min
├── check.py                      # lógica del watcher
├── index.html                    # web de estado (GitHub Pages)
├── state.json                    # último estado conocido (auto-commit)
└── requirements.txt
```
