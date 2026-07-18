from __future__ import annotations

import json
import logging
from typing import Any

from anthropic import AsyncAnthropic

from app.config import Settings
from app.memory import ConversationMemory

logger = logging.getLogger("whatsapp-agent.psn")


class PsnAgent:
    def __init__(self, settings: Settings, memory: ConversationMemory):
        self.settings = settings
        self.memory = memory
        self.client = AsyncAnthropic(api_key=settings.anthropic_api_key) if settings.anthropic_api_key else None

    async def plan(
        self,
        wa_id: str,
        user_text: str,
        inventory: dict[str, Any],
        role: str = "admin",
    ) -> dict[str, Any]:
        if not self.client:
            return {"type": "answer", "text": "Claude API key haijawekwa kwenye server bado."}

        self.memory.add_message(wa_id, "user", user_text)
        history = self.memory.recent_messages(wa_id, self.settings.max_history_messages)
        prompt = _system_prompt(inventory, role)
        try:
            response = await self.client.messages.create(
                model=self.settings.claude_model,
                max_tokens=1200,
                temperature=0.2,
                system=prompt,
                messages=history,
            )
            raw = "".join(
                block.text for block in response.content if getattr(block, "type", "") == "text"
            ).strip()
            planned = _parse_json(raw)
        except Exception as exc:
            logger.exception("Claude PSN planning failed")
            planned = {"type": "answer", "text": f"Nimekwama kidogo kusoma request hii: {exc}"}

        planned = _normalize_plan(planned)
        self.memory.add_message(wa_id, "assistant", _conversation_text(planned))
        return planned


def _system_prompt(inventory: dict[str, Any], role: str = "admin") -> str:
    role = "customer" if role == "customer" else "admin"
    compact = _compact_inventory(inventory, role)
    role_rules = _customer_rules() if role == "customer" else _admin_rules()
    response_shapes = _customer_response_shapes() if role == "customer" else _admin_response_shapes()
    return f"""You are a WhatsApp PSN sales and inventory assistant for a PSN account reselling business.

CURRENT CHAT ROLE: {role.upper()}

STYLE:
- Speak like a helpful human assistant, not a corporate AI.
- Use Swahili, English, or mixed language matching the user.
- Keep replies short: usually 1-3 sentences.
- Ask ONE question at a time when information is missing.
- Never invent account, game, price, or customer data.

LIVE BUSINESS DATA JSON:
{json.dumps(compact, ensure_ascii=False)}

BUSINESS RULES:
- The system tracks PSN accounts, games, PS4/PS5 slots, money, and reset/deactivation cycles.
- Selling starts from the game the customer wants.
- Slot price is calculated from account buying price: PS4 = buying price / 2. PS5 = buying price / 2 + 10,000 TZS.
- Daily packages sent by admin must be saved to Supabase for customer reference, even if the admin writes them in a messy format.
- For selling a normal slot, required info is: game and console PS4/PS5. Sale price can be auto-calculated from the account buying price. Account/email is required only if multiple matching accounts are possible.
- Suggest normal slots first. Use reset slots only when no normal slot is available.
- If reset slot is locked or no slot is available, say so clearly.
{role_rules}

OUTPUT ONLY VALID JSON. No markdown, no extra text.

RESPONSE SHAPES:
{response_shapes}

WHEN USER ASKS REPORTS:
- Answer directly with summary from live data. Do not create an action.

WHEN MULTIPLE MATCHES:
- Return gathering and list the few options in text.
"""


def _admin_rules() -> str:
    return """- Mutating actions must be returned as JSON action objects for backend confirmation. Do not say an action is done until backend confirms.
- When admin sends daily package/package list/bundle text, extract each package name, games, prices, and notes into save_packages. The admin may write messy Swahili/English text, not a fixed format.
- If package text has one shared price, put it in price. If PS4/PS5 prices are separate, use ps4_price and ps5_price."""


def _admin_response_shapes() -> str:
    return """1. Read or analysis:
{"type":"answer","text":"short useful answer"}

2. Need one more detail:
{"type":"gathering","text":"short question","field":"field_name"}

3. Write action requiring WhatsApp confirmation:
{"type":"action","action":"sell_slot","params":{"game":"FIFA 25","console":"PS5","email":"account@example.com","customer":"optional"},"confirm":"Confirm kuuza FIFA 25 PS5 kwa account@example.com kwa auto price?"}

4. Save admin package list:
{"type":"action","action":"save_packages","params":{"source_text":"original admin message","packages":[{"label":"GTA Package","games":["GTA V","FIFA 25"],"ps4_price":20000,"ps5_price":30000,"notes":"optional"}]},"confirm":"Confirm ni-save package hizi kwa customer reference?"}

SUPPORTED ACTIONS:
- add_account params: email, password, region, games array, purchase_cost, notes
- sell_slot params: game, console, email/account_id if known, optional price, customer, note
- save_packages params: packages array of objects with label/name, games array, optional ps4_price, ps5_price, price, notes, plus source_text
- update_account params: email/account_id, fields object
- delete_account params: email/account_id
- mark_deactivated params: email/account_id
- record_psn_deposit params: email/account_id, amount, note
- record_game_purchase params: email/account_id, game, amount"""


def _customer_response_shapes() -> str:
    return """1. Sales answer:
{"type":"answer","text":"short customer-facing reply"}

2. Need one more customer detail:
{"type":"gathering","text":"short customer-facing question","field":"game_or_console"}

Customer mode has no backend action response."""


def _customer_rules() -> str:
    return """- You are speaking to a CUSTOMER, not an admin.
- Never reveal account emails, passwords, purchase costs, PSN deposits, profit, internal notes, reset-cycle details, or supplier/admin data.
- Do not output action JSON in customer mode. Only answer or ask one sales question.
- Help the customer choose a game and console. Ask PS4 or PS5 when unclear.
- If a game exists with available slots, say it is available and mention 1-3 available packages that include that game, including public PS4/PS5 prices when available.
- A package is a safe public bundle from one account: show package label, games included, PS4/PS5 availability, and prices. Never show account email or internal account id.
- Use saved daily packages as the strongest reference when they include the requested game. Mention maximum 3 packages.
- When customer asks "do you have X", scan packages for packages whose games include X or close spelling matches. Prefer packages with the requested console available.
- If the exact game exists, answer naturally like "GTA ipo" / "FIFA ipo" first, then show up to 3 matching packages.
- If several packages include the game, present the best 2-3 in short lines, then ask which one they want.
- If unavailable, politely persuade the customer with close alternatives or popular packages from the system instead of ending the chat.
- You may negotiate confidently, but never quote a price above the stored public package price or the formula price shown in the data.
- Do not ask the customer to confirm a backend action. Ask normal sales questions like "PS4 au PS5?" or "Unahitaji game gani?"
- Keep the tone friendly, confident, and sales-focused."""


def _compact_inventory(inventory: dict[str, Any], role: str = "admin") -> dict[str, Any]:
    if role == "customer":
        return _customer_inventory(inventory)
    accounts = []
    for account in inventory.get("accounts", [])[:80]:
        games = [g.get("name") for g in account.get("games", []) if g.get("name")]
        slot_summary = []
        for slot in account.get("slots", []):
            slot_summary.append(
                {
                    "id": slot.get("id"),
                    "console": slot.get("console"),
                    "number": slot.get("slot_number"),
                    "type": slot.get("slot_type"),
                    "status": slot.get("status"),
                    "price": slot.get("price"),
                }
            )
        accounts.append(
            {
                "id": account.get("id"),
                "email": account.get("email"),
                "region": account.get("region"),
                "status": account.get("status"),
                "purchase_cost": account.get("purchase_cost"),
                "psn_deposits": account.get("psn_deposits"),
                "psn_game_purchases": account.get("psn_game_purchases"),
                "revenue": account.get("revenue"),
                "next_deactivation": account.get("next_deactivation"),
                "games": games,
                "slots": slot_summary,
            }
        )
    return {
        "accounts": accounts,
        "games": [{"id": g.get("id"), "name": g.get("name")} for g in inventory.get("games", [])[:120]],
        "packages": inventory.get("packages", [])[:80],
    }


def _customer_inventory(inventory: dict[str, Any]) -> dict[str, Any]:
    games: dict[str, dict[str, Any]] = {}
    packages = []
    for saved_package in inventory.get("packages", []):
        package = _public_saved_package(saved_package, len(packages) + 1)
        if not package:
            continue
        packages.append(package)
        for game_name in package["games"]:
            item = games.setdefault(
                game_name,
                {
                    "name": game_name,
                    "ps4_available": False,
                    "ps5_available": False,
                    "ps4_price": None,
                    "ps5_price": None,
                    "package_price": None,
                },
            )
            item["ps4_available"] = item["ps4_available"] or package["ps4_available"]
            item["ps5_available"] = item["ps5_available"] or package["ps5_available"]
            item["ps4_price"] = item["ps4_price"] or package.get("ps4_price")
            item["ps5_price"] = item["ps5_price"] or package.get("ps5_price")
            item["package_price"] = item["package_price"] or package.get("price")

    for index, account in enumerate(inventory.get("accounts", []), start=1):
        account_games = [g.get("name") for g in account.get("games", []) if g.get("name")]
        available = {
            "ps4": any(_is_primary_available(s, "ps4") for s in account.get("slots", [])),
            "ps5": any(_is_primary_available(s, "ps5") for s in account.get("slots", [])),
        }
        ps4_price = _default_slot_price(account, "ps4")
        ps5_price = _default_slot_price(account, "ps5")
        for game_name in account_games:
            item = games.setdefault(
                game_name,
                {
                    "name": game_name,
                    "ps4_available": False,
                    "ps5_available": False,
                    "ps4_price": None,
                    "ps5_price": None,
                    "package_price": None,
                },
            )
            item["ps4_available"] = item["ps4_available"] or available["ps4"]
            item["ps5_available"] = item["ps5_available"] or available["ps5"]
            if available["ps4"] and not item["ps4_price"]:
                item["ps4_price"] = ps4_price
            if available["ps5"] and not item["ps5_price"]:
                item["ps5_price"] = ps5_price
        if account_games and (available["ps4"] or available["ps5"]):
            packages.append(
                {
                    "label": f"Package {len(packages) + 1}",
                    "games": account_games[:8],
                    "ps4_available": available["ps4"],
                    "ps5_available": available["ps5"],
                    "ps4_price": ps4_price if available["ps4"] else None,
                    "ps5_price": ps5_price if available["ps5"] else None,
                    "source": "account",
                }
            )
    return {
        "games": sorted(games.values(), key=lambda item: item["name"])[:120],
        "packages": packages[:80],
    }


def _public_saved_package(saved_package: dict[str, Any], index: int) -> dict[str, Any] | None:
    games = [str(game).strip() for game in saved_package.get("games", []) if str(game).strip()]
    if not games:
        return None
    ps4_price = _optional_int(saved_package.get("ps4_price"))
    ps5_price = _optional_int(saved_package.get("ps5_price"))
    price = _optional_int(saved_package.get("price"))
    has_console_price = bool(ps4_price or ps5_price)
    return {
        "label": str(saved_package.get("label") or f"Package {index}").strip(),
        "games": games[:8],
        "ps4_available": bool(ps4_price or (price and not has_console_price)),
        "ps5_available": bool(ps5_price or (price and not has_console_price)),
        "ps4_price": ps4_price,
        "ps5_price": ps5_price,
        "price": price,
        "notes": str(saved_package.get("notes") or "").strip(),
        "source": "saved",
    }


def _optional_int(value: Any) -> int | None:
    try:
        amount = float(str(value or 0).replace(",", "").replace("TZS", "").replace("TSh", "").strip())
    except (TypeError, ValueError):
        return None
    if amount <= 0:
        return None
    return int(round(amount))


def _is_primary_available(slot: dict[str, Any], console: str) -> bool:
    return (
        slot.get("console") == console
        and slot.get("status") == "available"
        and slot.get("slot_type") == "normal"
        and _slot_number(slot) in {1, 2}
    )


def _slot_number(slot: dict[str, Any]) -> int:
    try:
        return int(slot.get("slot_number") or 0)
    except (TypeError, ValueError):
        return 0


def _default_slot_price(account: dict[str, Any], console: str) -> int | None:
    try:
        buying_price = float(account.get("purchase_cost") or 0)
    except (TypeError, ValueError):
        buying_price = 0
    if buying_price <= 0:
        return None
    price = buying_price / 2
    if console == "ps5":
        price += 10000
    return int(round(price))


def _parse_json(raw: str) -> dict[str, Any]:
    cleaned = raw.replace("```json", "").replace("```", "").strip()
    return json.loads(cleaned)


def _normalize_plan(plan: Any) -> dict[str, Any]:
    if not isinstance(plan, dict):
        return {"type": "answer", "text": "Sijaelewa vizuri. Niambie tena kwa kifupi."}
    kind = plan.get("type")
    if kind not in {"answer", "gathering", "action"}:
        return {"type": "answer", "text": str(plan.get("text") or "Sijaelewa vizuri.")}
    if kind == "action":
        if plan.get("action") not in {
            "add_account",
            "sell_slot",
            "save_packages",
            "update_account",
            "delete_account",
            "mark_deactivated",
            "record_psn_deposit",
            "record_game_purchase",
        }:
            return {"type": "answer", "text": "Action hiyo bado sijai-support."}
        plan.setdefault("params", {})
        plan.setdefault("confirm", "Confirm nifanye hii action?")
    else:
        plan["text"] = str(plan.get("text") or "Nimekupata.")
    return plan


def _conversation_text(plan: dict[str, Any]) -> str:
    if plan.get("type") == "action":
        return str(plan.get("confirm") or "Confirm action?")
    return str(plan.get("text") or "")
