import React, { createContext, useContext, useEffect, useMemo, useState } from 'react';
import { INITIAL_ACCOUNTS, INITIAL_TRANSACTIONS, GAMES, ADMINS } from '../data/mock-data';
import { supabase, hasSupabaseConfig } from '../lib/supabase';

const StoreContext = createContext();

const today = () => new Date().toISOString().split('T')[0];
const plusSixMonths = () => {
  const date = new Date();
  date.setMonth(date.getMonth() + 6);
  return date.toISOString().split('T')[0];
};

const dbGameToUi = (game) => ({
  id: game.id,
  name: game.name,
  default_ps4_price: Number(game.default_ps4_price || 0),
  default_ps5_price: Number(game.default_ps5_price || 0),
});

const dbSlotToUi = (slot) => ({
  id: slot.id,
  type: slot.slot_type,
  status: slot.status,
  price: Number(slot.price || 0),
  customer: slot.customer || '',
  date: slot.sold_date || '',
  resetCycle: slot.reset_cycle || 0,
});

const dbAccountToUi = (account) => {
  const accountGames = account.account_games || [];
  const slots = account.slots || [];
  return {
    id: account.id,
    email: account.email,
    password: account.password || '',
    region: account.region || 'US',
    condition: account.condition || 'clean',
    status: account.status || 'active',
    notes: account.notes || '',
    purchaseCost: Number(account.purchase_cost || 0),
    psnDeposits: Number(account.psn_deposits || 0),
    psnGamePurchases: Number(account.psn_game_purchases || 0),
    revenue: Number(account.revenue || 0),
    games: accountGames.map((item) => item.game_id),
    gameDetails: accountGames.map((item) => item.games).filter(Boolean).map(dbGameToUi),
    slots: {
      ps4: slots.filter((slot) => slot.console === 'ps4').sort((a, b) => a.slot_number - b.slot_number).map(dbSlotToUi),
      ps5: slots.filter((slot) => slot.console === 'ps5').sort((a, b) => a.slot_number - b.slot_number).map(dbSlotToUi),
    },
    expenses: [],
    lastDeactivation: account.last_deactivation,
    nextDeactivation: account.next_deactivation,
    createdAt: account.created_at?.split('T')[0] || today(),
  };
};

const dbTransactionToUi = (tx) => ({
  id: tx.id,
  type: tx.type,
  amount: Number(tx.amount || 0),
  date: tx.transaction_date,
  accountId: tx.account_id,
  slotId: tx.slot_id,
  gameId: tx.game_id,
  customer: tx.customer || '',
  note: tx.note || '',
  admin: tx.admin || 'Admin',
});

const getAccountExpenseTotal = (accountId, txs) =>
  txs.filter((t) => t.accountId === accountId && t.type === 'expense')
    .reduce((sum, t) => sum + Number(t.amount || 0), 0);

const SPEND_TYPES = new Set(['account_purchase', 'psn_deposit', 'withdrawal', 'expense']);

const computeBusinessBalance = (txs) => {
  let capitalIn = 0;
  let accountPurchase = 0;
  let psnDeposit = 0;
  let slotSale = 0;
  let withdrawal = 0;
  let expense = 0;
  let adjustment = 0;

  txs.forEach((t) => {
    const amount = Number(t.amount || 0);
    switch (t.type) {
      case 'capital_in': capitalIn += amount; break;
      case 'account_purchase': accountPurchase += amount; break;
      case 'psn_deposit': psnDeposit += amount; break;
      case 'slot_sale': slotSale += amount; break;
      case 'withdrawal': withdrawal += amount; break;
      case 'expense': expense += amount; break;
      case 'adjustment': adjustment += amount; break;
      default: break;
    }
  });

  return (capitalIn + slotSale + adjustment) - (accountPurchase + psnDeposit + withdrawal + expense);
};

const formatTzs = (value) => new Intl.NumberFormat('en-TZ', {
  style: 'currency',
  currency: 'TZS',
  maximumFractionDigits: 0,
}).format(Number(value || 0));

const assertSufficientBusinessBalance = (amount, txs) => {
  const balance = computeBusinessBalance(txs);
  if (amount > balance) {
    throw new Error(
      balance <= 0
        ? `Not enough money. Your balance is ${formatTzs(balance)}. Add capital before spending.`
        : `Not enough money. Your current balance is ${formatTzs(balance)}. You can spend up to ${formatTzs(balance)}.`
    );
  }
};

const buildDefaultSlots = (accountId) => ({
  ps4: [
    { id: `${accountId}-ps4-1`, type: 'normal', status: 'available' },
    { id: `${accountId}-ps4-2`, type: 'normal', status: 'available' },
    { id: `${accountId}-ps4-3`, type: 'reset', status: 'locked' },
  ],
  ps5: [
    { id: `${accountId}-ps5-1`, type: 'normal', status: 'available' },
    { id: `${accountId}-ps5-2`, type: 'normal', status: 'available' },
    { id: `${accountId}-ps5-3`, type: 'reset', status: 'locked' },
  ],
});

export const StoreProvider = ({ children }) => {
  const [accounts, setAccounts] = useState(hasSupabaseConfig ? [] : INITIAL_ACCOUNTS);
  const [transactions, setTransactions] = useState(hasSupabaseConfig ? [] : INITIAL_TRANSACTIONS);
  const [games, setGames] = useState(hasSupabaseConfig ? [] : GAMES);
  const [currentAdmin] = useState(ADMINS[0]);
  const [theme, setTheme] = useState(() => localStorage.getItem('theme') || 'dark');
  const [dbReady, setDbReady] = useState(false);
  const [dbError, setDbError] = useState('');
  const [loading, setLoading] = useState(hasSupabaseConfig);

  const logActivity = async (action, entityType, entityId, metadata = {}) => {
    if (!supabase || !dbReady) return;
    const { error } = await supabase.from('activity_log').insert({
      actor: currentAdmin.name,
      action,
      entity_type: entityType,
      entity_id: entityId || null,
      metadata,
    });
    if (error) console.warn('Activity log skipped:', error.message);
  };

  useEffect(() => {
    document.documentElement.setAttribute('data-theme', theme);
    localStorage.setItem('theme', theme);
  }, [theme]);

  const toggleTheme = () => setTheme(prev => prev === 'dark' ? 'light' : 'dark');

  const loadFromSupabase = async ({ silent = false } = {}) => {
    if (!supabase) return;
    if (!silent) setLoading(true);
    setDbError('');
    try {
      const [gamesResult, accountsResult, txResult] = await Promise.all([
        supabase.from('games').select('*').order('name'),
        supabase
          .from('accounts')
          .select('*, account_games(game_id, purchase_price, purchase_date, games(*)), slots(*)')
          .order('created_at', { ascending: false }),
        supabase.from('money_transactions').select('*').order('created_at', { ascending: false }),
      ]);

      if (gamesResult.error) throw gamesResult.error;
      if (accountsResult.error) throw accountsResult.error;
      if (txResult.error) throw txResult.error;

      setGames(gamesResult.data.map(dbGameToUi));
      setAccounts(accountsResult.data.map(dbAccountToUi));
      setTransactions(txResult.data.map(dbTransactionToUi));
      setDbReady(true);
    } catch (error) {
      setDbReady(false);
      setDbError(error.message || 'Could not connect to Supabase. Check your setup.');
      console.warn('Supabase load failed:', error);
    } finally {
      if (!silent) setLoading(false);
    }
  };

  useEffect(() => {
    if (hasSupabaseConfig) loadFromSupabase();
  }, []);

  const walletStats = useMemo(() => {
    let capitalIn = 0;
    let accountPurchase = 0;
    let psnDeposit = 0;
    let slotSale = 0;
    let withdrawal = 0;
    let expense = 0;
    let adjustment = 0;

    transactions.forEach(t => {
      const amount = Number(t.amount || 0);
      switch (t.type) {
        case 'capital_in': capitalIn += amount; break;
        case 'account_purchase': accountPurchase += amount; break;
        case 'psn_deposit': psnDeposit += amount; break;
        case 'slot_sale': slotSale += amount; break;
        case 'withdrawal': withdrawal += amount; break;
        case 'expense': expense += amount; break;
        case 'adjustment': adjustment += amount; break;
      }
    });

    const balance = computeBusinessBalance(transactions);
    const psnWalletsBalance = accounts.reduce((sum, acc) => sum + (Number(acc.psnDeposits || 0) - Number(acc.psnGamePurchases || 0)), 0);
    const totalInvested = capitalIn;
    const revenue = slotSale;
    const profit = revenue + psnWalletsBalance - totalInvested;
    const totalSpent = capitalIn - balance;

    return { balance, capitalIn, accountPurchase, psnDeposit, slotSale, withdrawal, expense, adjustment, psnWalletsBalance, totalInvested, revenue, profit, totalSpent };
  }, [transactions, accounts]);

  const getAccountStats = (acc) => {
    const totalInvested = Number(acc.purchaseCost || 0) + Number(acc.psnDeposits || 0) + getAccountExpenseTotal(acc.id, transactions);
    const psnBalance = Number(acc.psnDeposits || 0) - Number(acc.psnGamePurchases || 0);
    const profit = Number(acc.revenue || 0) + psnBalance - totalInvested;
    return { totalInvested, psnBalance, profit };
  };

  const addLocalTransaction = (data) => {
    const newTx = { id: `t${Date.now()}`, date: today(), admin: currentAdmin.name, ...data };
    setTransactions(prev => [newTx, ...prev]);
    return newTx;
  };

  const applyLocalAccountEffects = (data, newTx) => {
    if (!data.accountId) return;
    setAccounts((prev) => prev.map((acc) => {
      if (acc.id !== data.accountId) return acc;
      const newAcc = { ...acc };
      const amount = Number(data.amount || 0);
      if (data.type === 'psn_deposit') newAcc.psnDeposits += amount;
      if (data.type === 'slot_sale') {
        newAcc.revenue += amount;
        if (data.slotId) {
          const consoleName = data.slotId.includes('-ps5-') ? 'ps5' : 'ps4';
          newAcc.slots[consoleName] = newAcc.slots[consoleName].map((slot) =>
            slot.id === data.slotId
              ? { ...slot, status: 'sold', price: amount, customer: data.customer, date: newTx.date }
              : slot
          );
        }
      }
      if (data.type === 'expense') {
        newAcc.expenses.push({ id: `e${Date.now()}`, amount, note: data.note, date: newTx.date });
      }
      return newAcc;
    }));
  };

  const addTransaction = async (data) => {
    const amount = Number(data.amount || 0);
    if (!Number.isFinite(amount) || amount <= 0) {
      throw new Error('Enter a valid amount greater than zero.');
    }

    if (SPEND_TYPES.has(data.type)) {
      assertSufficientBusinessBalance(amount, transactions);
    }

    const saveLocally = () => {
      const newTx = addLocalTransaction({ ...data, amount });
      applyLocalAccountEffects(data, newTx);
      return newTx;
    };

    if (hasSupabaseConfig && supabase) {
      try {
        const payload = {
          type: data.type,
          amount,
          account_id: data.accountId || null,
          slot_id: data.slotId || null,
          game_id: data.gameId || null,
          customer: data.customer || null,
          note: data.note || null,
          admin: currentAdmin.name,
          transaction_date: today(),
        };
        const { data: inserted, error } = await supabase
          .from('money_transactions')
          .insert(payload)
          .select('*')
          .single();
        if (error) throw error;

        const uiTx = dbTransactionToUi(inserted);
        setTransactions((prev) => [uiTx, ...prev]);

        if (data.accountId && data.type === 'psn_deposit') {
          const account = accounts.find((acc) => acc.id === data.accountId);
          const nextDeposits = Number(account?.psnDeposits || 0) + amount;
          await supabase.from('accounts').update({ psn_deposits: nextDeposits }).eq('id', data.accountId);
          setAccounts((prev) => prev.map((acc) => acc.id === data.accountId ? { ...acc, psnDeposits: nextDeposits } : acc));
        }

        if (data.accountId && data.type === 'slot_sale') {
          const account = accounts.find((acc) => acc.id === data.accountId);
          const nextRevenue = Number(account?.revenue || 0) + amount;
          await supabase.from('accounts').update({ revenue: nextRevenue }).eq('id', data.accountId);
          setAccounts((prev) => prev.map((acc) => {
            if (acc.id !== data.accountId) return acc;
            const updated = { ...acc, revenue: nextRevenue };
            if (data.slotId) {
              const consoleName = acc.slots.ps5.some((slot) => slot.id === data.slotId) ? 'ps5' : 'ps4';
              updated.slots = {
                ...acc.slots,
                [consoleName]: acc.slots[consoleName].map((slot) =>
                  slot.id === data.slotId
                    ? { ...slot, status: 'sold', price: amount, customer: data.customer || '', date: today() }
                    : slot
                ),
              };
            }
            return updated;
          }));
          if (data.slotId) {
            await supabase.from('slots').update({
              status: 'sold',
              price: amount,
              customer: data.customer || null,
              sold_date: today(),
            }).eq('id', data.slotId);
          }
        }

        await logActivity(`transaction_${data.type}`, 'transaction', inserted.id, { type: data.type, amount, accountId: data.accountId });
        setDbError('');
        setDbReady(true);
        loadFromSupabase({ silent: true });
        return uiTx;
      } catch (error) {
        const rlsBlocked = error?.code === '42501';
        setDbError(
          rlsBlocked
            ? 'Cloud save blocked by Supabase security. Run supabase/fix_rls.sql in SQL Editor.'
            : (error.message || 'Cloud save failed. Saved on this device only.')
        );
        return saveLocally();
      }
    }

    return saveLocally();
  };

  const recordGamePurchase = async (accountId, gameId, cost) => {
    if (dbReady && supabase) {
      const account = accounts.find((acc) => acc.id === accountId);
      const nextPurchases = Number(account.psnGamePurchases || 0) + Number(cost || 0);
      await supabase.from('accounts').update({ psn_game_purchases: nextPurchases }).eq('id', accountId);
      await supabase.from('account_games').upsert({ account_id: accountId, game_id: gameId, purchase_price: Number(cost || 0), purchase_date: today() });
      await loadFromSupabase({ silent: true });
      return;
    }

    setAccounts(prev => prev.map(acc => acc.id !== accountId ? acc : {
      ...acc,
      psnGamePurchases: Number(acc.psnGamePurchases || 0) + Number(cost || 0),
      games: [...new Set([...acc.games, gameId])]
    }));
  };

  const markDeactivated = async (accountId) => {
    const lastDeact = today();
    const nextDeact = plusSixMonths();

    if (dbReady && supabase) {
      await supabase.from('accounts').update({ last_deactivation: lastDeact, next_deactivation: nextDeact }).eq('id', accountId);
      await supabase.from('slots').update({ status: 'available' }).eq('account_id', accountId).eq('slot_type', 'reset').eq('status', 'locked');
      await supabase.from('reset_cycles').insert({ account_id: accountId, deactivated_at: lastDeact, next_available_at: nextDeact, created_by: currentAdmin.name });
      await logActivity('account_deactivated', 'account', accountId);
      await loadFromSupabase({ silent: true });
      return;
    }

    setAccounts(prev => prev.map(acc => {
      if (acc.id !== accountId) return acc;
      return {
        ...acc,
        slots: {
          ps4: acc.slots.ps4.map(s => s.type === 'reset' ? { ...s, status: 'available' } : s),
          ps5: acc.slots.ps5.map(s => s.type === 'reset' ? { ...s, status: 'available' } : s),
        },
        lastDeactivation: lastDeact,
        nextDeactivation: nextDeact,
      };
    }));
  };

  const deleteAccount = async (id) => {
    if (dbReady && supabase) {
      await supabase.from('account_games').delete().eq('account_id', id);
      await supabase.from('slots').delete().eq('account_id', id);
      await supabase.from('money_transactions').delete().eq('account_id', id);
      await supabase.from('accounts').delete().eq('id', id);
      await logActivity('account_deleted', 'account', id, {});
      await loadFromSupabase({ silent: true });
      return;
    }
    setAccounts((prev) => prev.filter((acc) => acc.id !== id));
  };

  const updateAccount = async (id, data) => {
    if (dbReady && supabase) {
      const payload = {};
      if (data.condition) payload.condition = data.condition;
      if (data.status) payload.status = data.status;
      if (data.notes !== undefined) payload.notes = data.notes;
      if (data.password !== undefined) payload.password = data.password;
      await supabase.from('accounts').update(payload).eq('id', id);
      await logActivity('account_updated', 'account', id, payload);
      await loadFromSupabase({ silent: true });
      return;
    }
    setAccounts(prev => prev.map(acc => acc.id === id ? { ...acc, ...data } : acc));
  };


  const createGame = async ({ name, defaultPs4Price = 0, defaultPs5Price = 0 }) => {
    const cleanName = name.trim();
    if (!cleanName) return null;

    const existing = games.find((game) => game.name.toLowerCase() === cleanName.toLowerCase());
    if (existing) return existing;

    if (dbReady && supabase) {
      const { data, error } = await supabase
        .from('games')
        .upsert({ name: cleanName, default_ps4_price: Number(defaultPs4Price || 0), default_ps5_price: Number(defaultPs5Price || 0) }, { onConflict: 'name' })
        .select('*')
        .single();
      if (error) throw error;
      const uiGame = dbGameToUi(data);
      setGames((prev) => prev.some((game) => game.id === uiGame.id) ? prev : [...prev, uiGame].sort((a, b) => a.name.localeCompare(b.name)));
      await logActivity('game_created', 'game', uiGame.id, { name: cleanName });
      return uiGame;
    }

    const localGame = { id: `g${Date.now()}`, name: cleanName, default_ps4_price: Number(defaultPs4Price || 0), default_ps5_price: Number(defaultPs5Price || 0) };
    setGames((prev) => [...prev, localGame].sort((a, b) => a.name.localeCompare(b.name)));
    return localGame;
  };
  const createDefaultSlots = async (accountId) => {
    const rows = [
      { account_id: accountId, console: 'ps4', slot_number: 1, slot_type: 'normal', status: 'available' },
      { account_id: accountId, console: 'ps4', slot_number: 2, slot_type: 'normal', status: 'available' },
      { account_id: accountId, console: 'ps4', slot_number: 3, slot_type: 'reset', status: 'locked' },
      { account_id: accountId, console: 'ps5', slot_number: 1, slot_type: 'normal', status: 'available' },
      { account_id: accountId, console: 'ps5', slot_number: 2, slot_type: 'normal', status: 'available' },
      { account_id: accountId, console: 'ps5', slot_number: 3, slot_type: 'reset', status: 'locked' },
    ];
    const { error } = await supabase.from('slots').insert(rows);
    if (error) throw error;
  };

  const buildLocalAccount = (accountId, newAcc, gameCatalog = games) => {
    const cost = Number(newAcc.purchaseCost || 0);
    const gameIds = newAcc.games || [];
    return {
      id: accountId,
      email: newAcc.email,
      password: newAcc.password || '',
      region: newAcc.region || 'US',
      condition: 'clean',
      status: 'active',
      notes: newAcc.notes || '',
      purchaseCost: cost,
      psnDeposits: 0,
      psnGamePurchases: 0,
      revenue: 0,
      games: gameIds,
      gameDetails: gameIds.map((gameId) => gameCatalog.find((game) => game.id === gameId)).filter(Boolean).map(dbGameToUi),
      slots: buildDefaultSlots(accountId),
      expenses: [],
      createdAt: today(),
    };
  };

  const upsertAccountInState = (account) => {
    setAccounts((prev) => [account, ...prev.filter((item) => item.id !== account.id)]);
  };

  const addAccount = async (newAcc) => {
    const cost = Number(newAcc.purchaseCost || 0);
    const email = String(newAcc.email || '').trim();
    if (!email) throw new Error('Email is required.');
    if (cost > 0) assertSufficientBusinessBalance(cost, transactions);

    const payload = { ...newAcc, email, purchaseCost: cost };
    let accountId = `acc${Date.now()}`;

    const finishAccount = async (id) => {
      const account = buildLocalAccount(id, payload);
      upsertAccountInState(account);
      await addTransaction({
        type: 'account_purchase',
        amount: cost,
        accountId: id,
        note: `New account: ${email}`,
      });
      return account;
    };

    if (hasSupabaseConfig && supabase) {
      try {
        const { data, error } = await supabase.from('accounts').insert({
          email,
          password: newAcc.password || null,
          region: newAcc.region || 'US',
          purchase_cost: cost,
          notes: newAcc.notes || null,
          condition: 'clean',
          status: 'active',
        }).select('*').single();
        if (error) throw error;

        accountId = data.id;

        try {
          await createDefaultSlots(accountId);
        } catch (slotsError) {
          console.warn('Slots save skipped:', slotsError.message);
        }

        if (newAcc.games?.length) {
          const { error: gamesError } = await supabase.from('account_games').insert(
            newAcc.games.map((gameId) => ({ account_id: accountId, game_id: gameId, purchase_price: 0 }))
          );
          if (gamesError) console.warn('Account games save skipped:', gamesError.message);
        }

        const account = await finishAccount(accountId);
        await logActivity('account_created', 'account', accountId, { email });
        setDbError('');
        loadFromSupabase({ silent: true });
        return account;
      } catch (error) {
        if (String(error?.message || '').includes('Not enough money')) throw error;
        console.warn('Supabase account save failed, saving locally:', error);
        setDbError(error.message || 'Cloud save failed. Account saved on this device only.');
      }
    }

    return finishAccount(accountId);
  };

  const sellSlot = async ({ accountId, slotId, gameId, price, customer, note, payment = 'paid' }) => {
    const game = games.find((g) => g.id === gameId);
    const gameName = game?.name || 'Unknown';
    const paymentTag = payment !== 'paid' ? ` (${payment})` : '';
    const saleNote = note?.trim() || `Sold slot for game: ${gameName}${paymentTag}`;
    await addTransaction({
      type: 'slot_sale',
      amount: Number(price || 0),
      accountId,
      slotId,
      gameId,
      customer: customer || '',
      note: saleNote,
    });
  };

  const value = {
    accounts, transactions, games, currentAdmin, walletStats, loading, dbReady, dbError, hasSupabaseConfig,
    getAccountStats, addTransaction, recordGamePurchase, markDeactivated, addAccount, updateAccount, deleteAccount, createGame, sellSlot, refreshData: loadFromSupabase,
    theme, toggleTheme
  };

  return <StoreContext.Provider value={value}>{children}</StoreContext.Provider>;
};

export const useStore = () => useContext(StoreContext);