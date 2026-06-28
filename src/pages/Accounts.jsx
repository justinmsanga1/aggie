import React, { useMemo, useState } from 'react';
import { Search, Plus, ChevronRight, ChevronDown, ChevronUp, X, Pencil, Trash2 } from 'lucide-react';
import { useStore } from '../context/StoreContext';
import './Accounts.css';

const money = (v) => new Intl.NumberFormat('en-TZ', { style: 'currency', currency: 'TZS', maximumFractionDigits: 0 }).format(Number(v || 0));

const Accounts = ({ onViewDetails }) => {
  const { accounts, games, getAccountStats, addAccount, createGame, deleteAccount, updateAccount } = useStore();
  const [query, setQuery] = useState('');
  const [filter, setFilter] = useState('all');
  const [open, setOpen] = useState(false);
  const [editingAccount, setEditingAccount] = useState(null);
  const [selectedGames, setSelectedGames] = useState([]);
  const [newGameNames, setNewGameNames] = useState(['']);
  const [saving, setSaving] = useState(false);
  const [showAll, setShowAll] = useState(false);
  const openAddAccount = () => { setEditingAccount(null); setSelectedGames([]); setNewGameNames(['']); setOpen(true); };
  const openEditAccount = (account) => { setEditingAccount(account); setSelectedGames([...account.games]); setNewGameNames(['']); setOpen(true); };

  const enriched = useMemo(() => accounts.map((account) => {
    const stats = getAccountStats(account);
    const names = account.games.map((id) => games.find((g) => g.id === id)?.name || 'Unknown');
    const allSlots = [...account.slots.ps4, ...account.slots.ps5];
    const availablePs4 = account.slots.ps4.filter((slot) => slot.status === 'available').length;
    const availablePs5 = account.slots.ps5.filter((slot) => slot.status === 'available').length;
    const resetReady = allSlots.some((slot) => slot.type === 'reset' && slot.status === 'available');
    const soldOut = allSlots.every((slot) => slot.status === 'sold' || slot.status === 'locked');
    return { account, stats, names, availablePs4, availablePs5, resetReady, soldOut };
  }), [accounts, games, getAccountStats]);

  const filtered = enriched.filter(({ account, stats, names, availablePs4, availablePs5, resetReady, soldOut }) => {
    const haystack = `${account.email} ${account.region} ${account.condition} ${names.join(' ')}`.toLowerCase();
    const byQuery = haystack.includes(query.toLowerCase());
    const byFilter = filter === 'all' ||
      (filter === 'ps4' && availablePs4 > 0) ||
      (filter === 'ps5' && availablePs5 > 0) ||
      (filter === 'reset' && resetReady) ||
      (filter === 'unrecovered' && stats.profit < 0) ||
      (filter === 'profitable' && stats.profit >= 0) ||
      (filter === 'issue' && ['warning', 'issue', 'archived'].includes(account.condition)) ||
      (filter === 'soldout' && soldOut);
    return byQuery && byFilter;
  });

  const visible = showAll ? filtered : filtered.slice(0, 5);

  const toggleGame = (gameId) => {
    setSelectedGames((prev) => prev.includes(gameId) ? prev.filter((id) => id !== gameId) : [...prev, gameId]);
  };

  const resetAddForm = () => {
    setSelectedGames([]);
    setNewGameNames(['']);
    setEditingAccount(null);
    setOpen(false);
  };

  const submit = async (event) => {
    event.preventDefault();
    setSaving(true);
    try {
      const form = new FormData(event.target);
      let gameIds = [...selectedGames];
      for (const raw of newGameNames) {
        const trimmed = raw.trim();
        if (!trimmed) continue;
        const created = await createGame({ name: trimmed, defaultPs4Price: 0, defaultPs5Price: 0 });
        if (created?.id) gameIds.push(created.id);
      }
      if (!gameIds.length) {
        alert('Choose at least one game or add a new game name.');
        return;
      }
      const data = {
        email: form.get('email'),
        password: form.get('password'),
        region: form.get('region'),
        purchaseCost: parseFloat(form.get('cost')),
        notes: form.get('notes'),
        games: [...new Set(gameIds)],
      };
      if (editingAccount) {
        await updateAccount(editingAccount.id, data);
      } else {
        await addAccount(data);
      }
      event.target.reset();
      resetAddForm();
    } catch (error) {
      alert(error.message || 'Could not save account. Please try again.');
    } finally {
      setSaving(false);
    }
  };

  const filters = [['all','All'],['ps4','PS4 available'],['ps5','PS5 available'],['reset','Reset ready'],['unrecovered','Unrecovered'],['profitable','Profitable'],['issue','Issue'],['soldout','Sold out']];

  return (
    <div className="nexus-page accounts-page fade-in">
      {!open && <button type="button" className="add-account-wide" onClick={openAddAccount}><Plus size={18}/> Buy / Add Account</button>}
      {open && <section className="inline-add-account"><div className="inline-add-head"><div><h3>{editingAccount ? 'Edit Account' : 'Buy / Add Account'}</h3><p>{editingAccount ? 'Update account details and attached games.' : 'Record the account purchase and attach one or more games from database.'}</p></div><button type="button" onClick={resetAddForm} disabled={saving}>Close</button></div><form key={editingAccount ? editingAccount.id : 'add'} onSubmit={submit}><div className="form-group"><label className="form-label">Email</label><input className="form-input" name="email" type="email" required autoFocus defaultValue={editingAccount?.email || ''}/></div><div className="form-group"><label className="form-label">Password</label><input className="form-input" name="password" type="text" placeholder="PSN account password" defaultValue={editingAccount?.password || ''}/></div><div className="form-group"><label className="form-label">Region</label><select className="form-select" name="region" defaultValue={editingAccount?.region || 'US'}><option>US</option><option>UK</option><option>TR</option><option>JP</option></select></div><div className="form-group"><label className="form-label">Cost (TZS)</label><input className="form-input" name="cost" type="number" step="1" min="0" required defaultValue={editingAccount?.purchaseCost || ''}/></div><div className="form-group"><label className="form-label">Notes</label><input className="form-input" name="notes" type="text" placeholder="Optional notes" defaultValue={editingAccount?.notes || ''}/></div><div className="form-group"><label className="form-label">Games on this account</label>{games.length ? <div className="game-check-list">{games.map(g=><label key={g.id} className="game-check-row"><input type="checkbox" checked={selectedGames.includes(g.id)} onChange={()=>toggleGame(g.id)}/><span>{g.name}</span></label>)}</div> : <p className="empty-line">No games yet. Type a new game name below.</p>}</div><div className="form-group"><label className="form-label">+ Add new game names</label><div className="dynamic-game-inputs">{newGameNames.map((val, i)=><div key={i} className="game-input-row"><input className="form-input" value={val} onChange={(e)=>{const next=[...newGameNames]; next[i]=e.target.value; setNewGameNames(next);}} placeholder="e.g. FIFA 26 Ultimate Edition"/>{newGameNames.length>1 ? <button type="button" className="icon-shell game-input-remove" onClick={()=>setNewGameNames(newGameNames.filter((_,j)=>j!==i))}><X size={16}/></button> : null}</div>)}<button type="button" className="game-input-add" onClick={()=>setNewGameNames([...newGameNames, ''])}><Plus size={16}/> Add game</button></div></div><div className="form-group"><label className="form-label">Notes</label><textarea className="form-textarea" name="notes"/></div><button type="submit" className="sheet-submit-btn" disabled={saving}>{saving ? 'Saving...' : 'Add account'}</button></form></section>}
      <section className="control-card"><div className="search-control"><Search size={17}/><input value={query} onChange={(e)=>setQuery(e.target.value)} placeholder="Search email, game, region..."/></div><div className="chip-scroll">{filters.map(([id,label])=><button key={id} className={filter===id?'active':''} onClick={()=>setFilter(id)}>{label}</button>)}</div></section>
      <section className="accounts-list">
        {filtered.length === 0 ? (
          <p className="empty-line">No accounts yet. Tap Buy / Add Account to create your first one.</p>
        ) : visible.map(({ account, stats, names }) => (
          <article key={account.id} className="account-card" onClick={() => onViewDetails(account.id)}>
            <div className="account-head"><div><strong>{account.email}</strong><span>{account.region} - {account.condition}</span></div><div className="account-actions"><button className="icon-shell" onClick={(e) => { e.stopPropagation(); openEditAccount(account); }} title="Edit"><Pencil size={16}/></button><button className="icon-shell" onClick={(e) => { e.stopPropagation(); if (confirm('Delete this account and all its data?')) deleteAccount(account.id); }} title="Delete"><Trash2 size={16}/></button></div></div>
            <div className="game-chips">{names.slice(0,3).map((name)=><span key={name}>{name}</span>)}{names.length>3 && <span>+{names.length-3}</span>}</div>
            <div className="slot-map"><SlotLine label="PS4" slots={account.slots.ps4}/><SlotLine label="PS5" slots={account.slots.ps5}/></div>
            <div className="account-money"><div><small>Invested</small><b>{money(stats.totalInvested)}</b></div><div><small>Revenue</small><b>{money(account.revenue)}</b></div><div><small>P/L</small><b className={stats.profit>=0?'positive':'negative'}>{money(stats.profit)}</b></div><div><small>PSN left</small><b>{money(stats.psnBalance)}</b></div></div>
          </article>
        ))}
        {filtered.length > 5 && (
          <button className="ledger-toggle" onClick={() => setShowAll((s) => !s)}>
            {showAll ? <><ChevronUp size={16} /> Show Less</> : <><ChevronDown size={16} /> Show More ({filtered.length})</>}
          </button>
        )}
      </section>
    </div>
  );
};
const SlotLine = ({ label, slots }) => <div className="slot-line"><span>{label}</span><div>{slots.map((slot)=><i key={slot.id} className={`${slot.status} ${slot.type}`} title={`${slot.type} ${slot.status}`}/>)}</div></div>;
export default Accounts;