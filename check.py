import json
import os
import sys
import urllib.parse
from datetime import datetime, timezone

import requests

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

STATE_FILE = "state.json"


def load_dotenv():
    try:
        with open(".env", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    os.environ.setdefault(k.strip(), v.strip())
    except OSError:
        pass


load_dotenv()

# RIOT_API_KEY es opcional: sin ella todo el monitoreo corre con HenrikDev.
RIOT_API_KEY = os.environ.get("RIOT_API_KEY") or None
TELEGRAM_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID") or None
HENRIK_KEY = os.environ.get("HENRIK_API_KEY") or None

# Routing regional de la API de Riot (account): americas|europe|asia|sea
RIOT_REGION = os.environ.get("RIOT_REGION") or "americas"


class RiotKeyExpired(Exception):
    pass


def riot_get(path):
    resp = requests.get(
        f"https://{RIOT_REGION}.api.riotgames.com{path}",
        headers={"X-Riot-Token": RIOT_API_KEY},
        timeout=15,
    )
    if resp.status_code == 403:
        raise RiotKeyExpired()
    resp.raise_for_status()
    return resp.json()


def henrik_get(path):
    try:
        r = requests.get(
            f"https://api.henrikdev.xyz/valorant/{path}",
            headers={"Authorization": HENRIK_KEY},
            timeout=15,
        )
        return r.json().get("data") if r.status_code == 200 else None
    except requests.RequestException as e:
        print(f"Henrik API error ({path}): {e}")
        return None


def telegram_chat_id():
    if TELEGRAM_CHAT_ID:
        return TELEGRAM_CHAT_ID
    r = requests.get(
        f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/getUpdates", timeout=15
    )
    r.raise_for_status()
    for upd in reversed(r.json().get("result", [])):
        msg = upd.get("message") or upd.get("channel_post")
        if msg:
            return str(msg["chat"]["id"])
    raise RuntimeError(
        "Sin chat_id: envia /start a tu bot en Telegram y vuelve a intentar"
    )


def send_telegram(text):
    try:
        requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
            json={"chat_id": telegram_chat_id(), "text": text},
            timeout=15,
        ).raise_for_status()
    except Exception as e:
        print(f"Error enviando Telegram: {e}")


def send_telegram_photo(photo_url, caption):
    try:
        requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendPhoto",
            json={
                "chat_id": telegram_chat_id(),
                "photo": photo_url,
                "caption": caption,
            },
            timeout=15,
        ).raise_for_status()
    except Exception as e:
        print(f"Error enviando foto Telegram: {e}")


def fetch_current(prev, puuid):
    # Los PUUIDs viven solo en secrets/entorno: nunca se escriben en
    # state.json porque ese archivo se sirve publico via GitHub Pages.
    current = {
        # Sin RIOT_API_KEY no podemos refrescar el shard: se conserva el previo.
        "shard": prev.get("shard"),
        "checked_at": datetime.now(timezone.utc)
        .isoformat(timespec="seconds")
        .replace("+00:00", "Z"),
    }
    name = tag = None

    if RIOT_API_KEY:
        account = riot_get(
            f"/riot/account/v1/accounts/by-puuid/{puuid}"
        )
        name, tag = account["gameName"], account["tagLine"]
        current["riot_id"] = f"{name}#{tag}"
        current["shard"] = riot_get(
            f"/riot/account/v1/active-shards/by-game/val/by-puuid/{puuid}"
        ).get("activeShard")

    if HENRIK_KEY:
        hp = prev.get("henrik_puuid") or os.environ.get("HENRIK_PUUID")
        if hp:
            acc = henrik_get(f"v1/by-puuid/account/{hp}")
        else:
            if name is None:
                rid = prev.get("riot_id") or os.environ.get("RIOT_ID")
                if not rid or "#" not in rid:
                    print("Falta riot_id en state.json para resolver la cuenta")
                    sys.exit(1)
                name, tag = rid.split("#", 1)
            enc = f"{urllib.parse.quote(name)}/{urllib.parse.quote(tag)}"
            acc = henrik_get(f"v1/account/{enc}")
        if acc:
            hp = acc.get("puuid")
            name, tag = acc["name"], acc["tag"]
            current["riot_id"] = f"{name}#{tag}"
            current["account_level"] = acc.get("account_level")
            card = acc.get("card") or {}
            current["card_id"] = card.get("id")
            current["card_url"] = card.get("small")
            current["card_image"] = card.get("wide") or card.get("large")
            ts = acc.get("last_update_raw")
            if ts:
                current["card_updated_at"] = (
                    datetime.fromtimestamp(ts, timezone.utc)
                    .isoformat(timespec="seconds")
                    .replace("+00:00", "Z")
                )
            region = current.get("shard") or acc.get("region") or "na"
            mmr = henrik_get(f"v2/by-puuid/mmr/{region}/{hp}")
            if mmr:
                cd = mmr.get("current_data") or {}
                current["rank"] = cd.get("currenttierpatched")
                current["rr"] = cd.get("ranking_in_tier")
                current["rank_icon"] = (cd.get("images") or {}).get("small")
                current["rank_icon_lg"] = (cd.get("images") or {}).get(
                    "large"
                )
                current["peak_rank"] = (mmr.get("highest_rank") or {}).get(
                    "patched_tier"
                )
            matches = henrik_get(
                f"v4/by-puuid/matches/{region}/pc/{hp}?size=1"
            )
            if matches:
                match = matches[0]
                m = match["metadata"]
                current["last_match_id"] = m["match_id"]
                current["last_match_map"] = (m.get("map") or {}).get("name")
                current["last_match_map_id"] = (m.get("map") or {}).get("id")
                current["last_match_queue"] = (m.get("queue") or {}).get(
                    "name"
                )
                current["last_match_start"] = m.get("started_at")
                me = next(
                    (
                        p
                        for p in match.get("players") or []
                        if (p.get("name") or "").lower() == name.lower()
                        and (p.get("tag") or "").lower() == tag.lower()
                    ),
                    None,
                )
                if me:
                    agent = me.get("agent") or {}
                    current["last_match_agent"] = agent.get("name")
                    current["last_match_agent_id"] = agent.get("id")
                    st = me.get("stats") or {}
                    current["last_match_kda"] = (
                        f'{st.get("kills")}/{st.get("deaths")}'
                        f'/{st.get("assists")}'
                    )
                    teams = {
                        t["team_id"]: t for t in match.get("teams") or []
                    }
                    t = teams.get(me.get("team_id")) or {}
                    rnd = t.get("rounds") or {}
                    w, l = rnd.get("won"), rnd.get("lost")
                    if w is not None and l is not None:
                        current["last_match_score"] = f"{w}-{l}"
                        current["last_match_result"] = (
                            "draw"
                            if w == l
                            else ("win" if t.get("won") else "loss")
                        )
        else:
            # Henrik no respondio: conservar sus campos para no generar
            # alertas falsas ni perder el estado.
            for k, v in prev.items():
                if k != "checked_at":
                    current.setdefault(k, v)
    return current


def load_state():
    try:
        with open(STATE_FILE, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return {}


def main():
    if not RIOT_API_KEY and not HENRIK_KEY:
        print("Falta RIOT_API_KEY o HENRIK_API_KEY")
        sys.exit(1)

    prev = load_state()
    puuid = prev.get("puuid") or os.environ.get("RIOT_PUUID")
    if not puuid:
        print(
            "Falta el PUUID: configura el secret RIOT_PUUID en el repo "
            "(Settings -> Secrets and variables -> Actions) o guarda un "
            '"puuid" en state.json'
        )
        sys.exit(1)

    try:
        current = fetch_current(prev, puuid)
    except RiotKeyExpired:
        send_telegram(
            "⚠️ Riot Watcher: la API key de Riot ha caducado. "
            "Renuevala en developer.riotgames.com"
        )
        sys.exit(1)

    changes = []
    for key, label in (
        ("riot_id", "Riot ID"),
        ("shard", "Shard"),
        ("account_level", "Nivel"),
        ("rank", "Rango"),
        ("rr", "RR"),
        ("peak_rank", "Rango maximo"),
        ("card_id", "Player card"),
    ):
        old, new = prev.get(key), current.get(key)
        if old is not None and old != new:
            changes.append(f"{label}: {old} → {new}")

    if prev.get("last_match_id") and prev["last_match_id"] != current.get(
        "last_match_id"
    ):
        kda = (
            f" — {current['last_match_agent']} {current['last_match_kda']}"
            if current.get("last_match_agent")
            else ""
        )
        changes.append(
            "Nueva partida: "
            f"{current.get('last_match_map') or '?'} · "
            f"{current.get('last_match_queue') or '?'}"
            f"{kda}"
        )

    if prev.get("rr") is not None and prev.get("rr") != current.get("rr"):
        current["rr_prev"] = prev["rr"]
    elif "rr_prev" in prev:
        current["rr_prev"] = prev["rr_prev"]

    card_changed = (
        prev.get("card_id") is not None
        and prev.get("card_id") != current.get("card_id")
    )
    if card_changed:
        current["card_changed_at"] = current["checked_at"]
    elif "card_changed_at" in prev:
        current["card_changed_at"] = prev["card_changed_at"]

    if changes:
        send_telegram("🎮 Riot Watcher\n" + "\n".join(changes))
    if card_changed and current.get("card_image"):
        send_telegram_photo(
            current["card_image"],
            f'🎴 Nueva player card: {prev.get("card_id")} → '
            f'{current.get("card_id")}',
        )

    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(current, f, indent=2, ensure_ascii=False)
        f.write("\n")

    print("\n".join(changes) if changes else "Sin cambios")


if __name__ == "__main__":
    main()
