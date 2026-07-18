from __future__ import annotations

from datetime import date
from typing import Any
from urllib.parse import quote

import httpx

from app.config import Settings


class PsnStore:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.base_url = settings.supabase_url.rstrip("/")
        self.key = settings.supabase_service_role_key or settings.supabase_anon_key

    @property
    def configured(self) -> bool:
        return bool(self.base_url and self.key)

    async def inventory(self) -> dict[str, Any]:
        self._require_config()
        accounts, games, account_games, slots, transactions = await self._gather(
            self._get("accounts", "select=*"),
            self._get("games", "select=*"),
            self._get("account_games", "select=*"),
            self._get("slots", "select=*"),
            self._get("money_transactions", "select=*&order=created_at.desc&limit=200"),
        )
        game_by_id = {g["id"]: g for g in games}
        games_by_account: dict[str, list[dict[str, Any]]] = {}
        for row in account_games:
            game = game_by_id.get(row.get("game_id"))
            if game:
                games_by_account.setdefault(row["account_id"], []).append(game)
        slots_by_account: dict[str, list[dict[str, Any]]] = {}
        for slot in slots:
            slots_by_account.setdefault(slot["account_id"], []).append(slot)
        account_rows = []
        for account in accounts:
            account_rows.append(
                {
                    **account,
                    "games": games_by_account.get(account["id"], []),
                    "slots": sorted(
                        slots_by_account.get(account["id"], []),
                        key=lambda s: (s.get("console", ""), s.get("slot_number", 0), s.get("reset_cycle", 0)),
                    ),
                }
            )
        return {"accounts": account_rows, "games": games, "transactions": transactions}

    async def execute(self, action: str, params: dict[str, Any]) -> str:
        handlers = {
            "add_account": self.add_account,
            "sell_slot": self.sell_slot,
            "update_account": self.update_account,
            "delete_account": self.delete_account,
            "mark_deactivated": self.mark_deactivated,
            "record_psn_deposit": self.record_psn_deposit,
            "record_game_purchase": self.record_game_purchase,
        }
        handler = handlers.get(action)
        if not handler:
            raise ValueError(f"Unsupported PSN action: {action}")
        return await handler(params)

    async def add_account(self, params: dict[str, Any]) -> str:
        email = _clean(params.get("email"))
        if not email:
            raise ValueError("Email is required.")
        games = [_clean(g) for g in params.get("games", []) if _clean(g)]
        purchase_cost = _money(params.get("purchase_cost", params.get("cost_tzs", params.get("costTZS", 0))))
        account = await self._post(
            "accounts",
            {
                "email": email,
                "password": params.get("password") or None,
                "region": params.get("region") or "US",
                "purchase_cost": purchase_cost,
                "notes": params.get("notes") or None,
                "condition": params.get("condition") or "clean",
                "status": params.get("status") or "active",
            },
        )
        account_id = account["id"]
        await self._post_many("slots", _default_slots(account_id))
        for game_name in games:
            game = await self._ensure_game(game_name)
            await self._post(
                "account_games",
                {"account_id": account_id, "game_id": game["id"], "purchase_price": 0},
                upsert=True,
            )
        if purchase_cost > 0:
            await self._post(
                "money_transactions",
                {
                    "type": "account_purchase",
                    "amount": purchase_cost,
                    "account_id": account_id,
                    "note": f"New account: {email}",
                    "admin": "WhatsApp PSN Agent",
                    "transaction_date": _today(),
                },
            )
        return f"Done. Nimeongeza account {email} na slots zake za PS4/PS5."

    async def sell_slot(self, params: dict[str, Any]) -> str:
        inventory = await self.inventory()
        account = _find_account(inventory["accounts"], params)
        game = _find_game(inventory["games"], params)
        console = _console(params.get("console"))
        price = _money(params.get("price", params.get("sell_price", params.get("sellPrice", 0))))
        if not account:
            raise ValueError("Sijaipata account hiyo kwenye inventory.")
        if not game:
            raise ValueError("Sijaipata game hiyo kwenye game list.")
        if not console:
            raise ValueError("Console inahitajika: PS4 au PS5.")
        if price <= 0:
            raise ValueError("Sale price lazima iwe kubwa kuliko 0.")

        matching_game_ids = {g["id"] for g in account.get("games", [])}
        if game["id"] not in matching_game_ids:
            raise ValueError(f"{account['email']} haina {game['name']} kwenye games zake.")

        slot = _choose_slot(account.get("slots", []), console, params.get("slot"))
        if not slot:
            raise ValueError(f"Hakuna {console.upper()} slot available kwa {account['email']}.")

        customer = _clean(params.get("customer"))
        await self._patch(
            "slots",
            f"id=eq.{slot['id']}",
            {
                "status": "sold",
                "price": price,
                "customer": customer or None,
                "sold_date": params.get("date") or _today(),
            },
        )
        await self._post(
            "money_transactions",
            {
                "type": "slot_sale",
                "amount": price,
                "account_id": account["id"],
                "slot_id": slot["id"],
                "game_id": game["id"],
                "customer": customer or None,
                "note": params.get("note") or f"Sold slot for game: {game['name']}",
                "admin": "WhatsApp PSN Agent",
                "transaction_date": params.get("date") or _today(),
            },
        )
        next_revenue = _money(account.get("revenue")) + price
        await self._patch("accounts", f"id=eq.{account['id']}", {"revenue": next_revenue})
        return (
            f"Done. Nimeuza {game['name']} {console.upper()} slot {slot['slot_number']} "
            f"kwa {account['email']} - TZS {price:,.0f}."
        )

    async def update_account(self, params: dict[str, Any]) -> str:
        account = _find_account((await self.inventory())["accounts"], params)
        if not account:
            raise ValueError("Sijaipata account ya ku-update.")
        fields = params.get("fields") or {}
        payload = {}
        mapping = {
            "email": "email",
            "password": "password",
            "region": "region",
            "condition": "condition",
            "status": "status",
            "notes": "notes",
            "purchase_cost": "purchase_cost",
        }
        for key, column in mapping.items():
            if key in fields:
                payload[column] = fields[key]
        if not payload:
            raise ValueError("Hakuna field ya ku-update.")
        await self._patch("accounts", f"id=eq.{account['id']}", payload)
        return f"Done. Nime-update account {account['email']}."

    async def delete_account(self, params: dict[str, Any]) -> str:
        account = _find_account((await self.inventory())["accounts"], params)
        if not account:
            raise ValueError("Sijaipata account ya kufuta.")
        await self._delete("accounts", f"id=eq.{account['id']}")
        return f"Done. Nimefuta account {account['email']} na related data zake."

    async def mark_deactivated(self, params: dict[str, Any]) -> str:
        account = _find_account((await self.inventory())["accounts"], params)
        if not account:
            raise ValueError("Sijaipata account ya deactivation.")
        locked = [s for s in account.get("slots", []) if s.get("slot_type") == "reset" and s.get("status") == "locked"]
        if locked:
            await self._patch("slots", f"account_id=eq.{account['id']}&slot_type=eq.reset&status=eq.locked", {"status": "available"})
        else:
            next_cycle = max([int(s.get("reset_cycle") or 0) for s in account.get("slots", []) if s.get("slot_type") == "reset"] or [0]) + 1
            await self._post_many(
                "slots",
                [
                    {"account_id": account["id"], "console": "ps4", "slot_number": 3, "slot_type": "reset", "status": "available", "reset_cycle": next_cycle},
                    {"account_id": account["id"], "console": "ps5", "slot_number": 3, "slot_type": "reset", "status": "available", "reset_cycle": next_cycle},
                ],
            )
        await self._patch(
            "accounts",
            f"id=eq.{account['id']}",
            {"last_deactivation": _today(), "next_deactivation": _plus_six_months()},
        )
        return f"Done. Nimeweka reset slots available kwa {account['email']}."

    async def record_psn_deposit(self, params: dict[str, Any]) -> str:
        account = _find_account((await self.inventory())["accounts"], params)
        amount = _money(params.get("amount"))
        if not account:
            raise ValueError("Sijaipata account ya deposit.")
        if amount <= 0:
            raise ValueError("Amount lazima iwe kubwa kuliko 0.")
        await self._post(
            "money_transactions",
            {"type": "psn_deposit", "amount": amount, "account_id": account["id"], "note": params.get("note") or "PSN wallet deposit", "admin": "WhatsApp PSN Agent", "transaction_date": _today()},
        )
        await self._patch("accounts", f"id=eq.{account['id']}", {"psn_deposits": _money(account.get("psn_deposits")) + amount})
        return f"Done. Nime-record PSN deposit TZS {amount:,.0f} kwa {account['email']}."

    async def record_game_purchase(self, params: dict[str, Any]) -> str:
        inventory = await self.inventory()
        account = _find_account(inventory["accounts"], params)
        game_name = _clean(params.get("game") or params.get("game_name"))
        amount = _money(params.get("amount", params.get("cost", params.get("purchase_price", 0))))
        if not account:
            raise ValueError("Sijaipata account.")
        if not game_name:
            raise ValueError("Game name inahitajika.")
        if amount <= 0:
            raise ValueError("Game cost lazima iwe kubwa kuliko 0.")
        game = await self._ensure_game(game_name)
        await self._post("account_games", {"account_id": account["id"], "game_id": game["id"], "purchase_price": amount, "purchase_date": _today()}, upsert=True)
        await self._patch("accounts", f"id=eq.{account['id']}", {"psn_game_purchases": _money(account.get("psn_game_purchases")) + amount})
        return f"Done. Nimeongeza {game_name} kwa {account['email']}."

    async def _ensure_game(self, name: str) -> dict[str, Any]:
        rows = await self._get("games", f"select=*&name=ilike.{quote(name, safe='')}")
        if rows:
            return rows[0]
        return await self._post("games", {"name": name})

    async def _get(self, table: str, query: str) -> list[dict[str, Any]]:
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.get(f"{self.base_url}/rest/v1/{table}?{query}", headers=self._headers())
            response.raise_for_status()
            return response.json()

    async def _post(self, table: str, payload: dict[str, Any], upsert: bool = False) -> dict[str, Any]:
        headers = self._headers(prefer="return=representation")
        url = f"{self.base_url}/rest/v1/{table}"
        if upsert:
            headers["Prefer"] = "resolution=merge-duplicates,return=representation"
            if table == "account_games":
                url += "?on_conflict=account_id,game_id"
            elif table == "games":
                url += "?on_conflict=name"
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post(url, json=payload, headers=headers)
            response.raise_for_status()
            data = response.json()
            return data[0] if isinstance(data, list) and data else data

    async def _post_many(self, table: str, rows: list[dict[str, Any]]) -> None:
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post(f"{self.base_url}/rest/v1/{table}", json=rows, headers=self._headers())
            response.raise_for_status()

    async def _patch(self, table: str, query: str, payload: dict[str, Any]) -> None:
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.patch(f"{self.base_url}/rest/v1/{table}?{query}", json=payload, headers=self._headers())
            response.raise_for_status()

    async def _delete(self, table: str, query: str) -> None:
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.delete(f"{self.base_url}/rest/v1/{table}?{query}", headers=self._headers())
            response.raise_for_status()

    async def _gather(self, *calls: Any) -> tuple[Any, ...]:
        import asyncio

        return tuple(await asyncio.gather(*calls))

    def _headers(self, prefer: str | None = None) -> dict[str, str]:
        headers = {"apikey": self.key, "Authorization": f"Bearer {self.key}", "Content-Type": "application/json"}
        if prefer:
            headers["Prefer"] = prefer
        return headers

    def _require_config(self) -> None:
        if not self.configured:
            raise RuntimeError("Supabase is not configured. Set SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY.")


def _default_slots(account_id: str) -> list[dict[str, Any]]:
    return [
        {"account_id": account_id, "console": "ps4", "slot_number": 1, "slot_type": "normal", "status": "available"},
        {"account_id": account_id, "console": "ps4", "slot_number": 2, "slot_type": "normal", "status": "available"},
        {"account_id": account_id, "console": "ps4", "slot_number": 3, "slot_type": "reset", "status": "locked"},
        {"account_id": account_id, "console": "ps5", "slot_number": 1, "slot_type": "normal", "status": "available"},
        {"account_id": account_id, "console": "ps5", "slot_number": 2, "slot_type": "normal", "status": "available"},
        {"account_id": account_id, "console": "ps5", "slot_number": 3, "slot_type": "reset", "status": "locked"},
    ]


def _find_account(accounts: list[dict[str, Any]], params: dict[str, Any]) -> dict[str, Any] | None:
    account_id = _clean(params.get("account_id"))
    email = _clean(params.get("email") or params.get("account"))
    if account_id:
        for account in accounts:
            if account.get("id") == account_id:
                return account
    if email:
        lowered = email.lower()
        exact = [a for a in accounts if str(a.get("email", "")).lower() == lowered]
        if exact:
            return exact[0]
        partial = [a for a in accounts if lowered in str(a.get("email", "")).lower()]
        if len(partial) == 1:
            return partial[0]
    return None


def _find_game(games: list[dict[str, Any]], params: dict[str, Any]) -> dict[str, Any] | None:
    game_id = _clean(params.get("game_id"))
    name = _clean(params.get("game") or params.get("game_name"))
    if game_id:
        for game in games:
            if game.get("id") == game_id:
                return game
    if name:
        lowered = name.lower()
        exact = [g for g in games if str(g.get("name", "")).lower() == lowered]
        if exact:
            return exact[0]
        partial = [g for g in games if lowered in str(g.get("name", "")).lower()]
        if len(partial) == 1:
            return partial[0]
    return None


def _choose_slot(slots: list[dict[str, Any]], console: str, requested: Any = None) -> dict[str, Any] | None:
    candidates = [s for s in slots if s.get("console") == console and s.get("status") == "available"]
    if requested:
        try:
            slot_number = int(requested)
            numbered = [s for s in candidates if int(s.get("slot_number") or 0) == slot_number]
            if numbered:
                return sorted(numbered, key=lambda s: int(s.get("reset_cycle") or 0))[0]
        except (TypeError, ValueError):
            pass
    normal = [s for s in candidates if s.get("slot_type") == "normal"]
    if normal:
        return sorted(normal, key=lambda s: int(s.get("slot_number") or 0))[0]
    reset = [s for s in candidates if s.get("slot_type") == "reset"]
    if reset:
        return sorted(reset, key=lambda s: int(s.get("reset_cycle") or 0))[0]
    return None


def _console(value: Any) -> str:
    lowered = str(value or "").lower()
    if "5" in lowered:
        return "ps5"
    if "4" in lowered:
        return "ps4"
    return ""


def _money(value: Any) -> float:
    try:
        return float(str(value or 0).replace(",", "").replace("TZS", "").replace("TSh", "").strip())
    except ValueError:
        return 0.0


def _clean(value: Any) -> str:
    return str(value or "").strip()


def _today() -> str:
    return date.today().isoformat()


def _plus_six_months() -> str:
    from datetime import timedelta

    return (date.today() + timedelta(days=183)).isoformat()

