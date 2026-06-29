# PSN Manager Reference

## Purpose

PSN Manager is a mobile-first business system for two admins who buy PSN accounts, add games, sell PS4 and PS5 slots, track money, and manage deactivation/reset cycles.

The app is a tracking system only. It does not process real money.

## Core Business Split

The system has two main sides:

1. Business Money
2. Account Buying and Selling

## Business Wallet Formula

```text
Business wallet balance =
capital added + adjustments
- account purchases
- PSN deposits
- withdrawals
- expenses
```

## Account Money Formulas

```text
PSN wallet balance = PSN deposits into account - game purchases from that account
```

```text
Account total invested = account purchase cost + PSN wallet deposits + account-specific expenses
```

```text
Account profit/loss = slot sale revenue + remaining PSN wallet balance - total invested
```

## Account Fields

Each account should track:

- Email
- Password
- Region
- Condition/status
- Notes
- Multiple games
- Purchase cost
- PSN wallet deposits
- Game purchase history
- PSN wallet balance left
- Total invested
- Slot sale revenue
- Profit/loss
- Reset/deactivation status
- Last deactivation date
- Next deactivation available date

## Slot Model

Each account starts with:

- 3 PS4 slots
- 3 PS5 slots

Slot behavior:

- First 2 PS4 slots are normal slots.
- First 2 PS5 slots are normal slots.
- Third PS4 slot requires deactivation/reset.
- Third PS5 slot requires deactivation/reset.

After normal slots are sold:

1. Admin marks account as deactivated.
2. Third PS4 reset slot becomes available.
3. Third PS5 reset slot becomes available.
4. Next deactivation date becomes 6 months later.

After 6 months:

- Admin can deactivate again.
- One new PS4 reset slot becomes available.
- One new PS5 reset slot becomes available.

## Selling Workflow

Selling must start from the game the customer wants.

```text
Customer asks for game
Admin searches/selects game
System shows all accounts containing that game
Admin sees PS4/PS5 slot status for each account
Admin selects account and console
System suggests correct slot
Admin enters actual negotiated sale price
Sale is saved
```

Slot suggestion rule:

- Sell normal slot first if available.
- If normal slots are sold and reset slot is available, sell reset slot.
- If reset slot is locked, show locked warning.

## Screens

Main screens:

1. Dashboard
2. Money / Ledger
3. Accounts
4. Sell Slot
5. Reports
6. Settings / Backup

Detail screen:

7. Account Details

Account Details opens from the Accounts screen.

## Recommended Stack

- React PWA frontend
- Supabase Postgres main database
- Google Sheets backup/export later

## Supabase Tables

- admins
- games
- accounts
- account_games
- slots
- money_transactions
- reset_cycles
- activity_log

## Mobile Requirements

The system will mostly be used on phones.

- Bottom navigation must fit small screens.
- Financial numbers must not overflow.
- Account cards must stay compact.
- Forms must use at least 16px inputs to avoid iPhone zoom.
- Long emails/game names must truncate cleanly.
- Grids should collapse on narrow screens.
- Add Account must be inline or clearly visible, not hidden behind blur.