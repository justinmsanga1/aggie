import React, { useMemo, useState } from 'react';
import { Search, CheckCircle2, Gamepad2, User, Lock, Send, ChevronLeft } from 'lucide-react';
import { useStore } from '../context/StoreContext';
import './SellSlot.css';

const money = (v) => new Intl.NumberFormat('en-TZ', { style: 'currency', currency: 'TZS', maximumFractionDigits: 0 }).format(Number(v || 0));

const SellSlot = ({ onComplete }) => {
  const { games, accounts, sellSlot, getAccountStats } = useStore();
  const [gameQuery, setGameQuery] = useState('');
  const [selectedGame, setSelectedGame] = useState(null);
  const [filter, setFilter] = useState('all');
  const [selected, setSelected] = useState(null);
  const [form, setForm] = useState({ price: '', customer: '', note: '', payment: 'paid' });
  const [submitting, setSubmitting] = useState(false);

  const availableGameIds = useMemo(() => new Set(accounts.flatMap((acc) => acc.games)), [accounts]);
  const filteredGames = games.filter((game) => availableGameIds.has(game.id)).filter((game) => game.name.toLowerCase().includes(gameQuery.toLowerCase()));
  const matches = useMemo(() => {
    if (!selectedGame) return [];
    return accounts.filter((account) => account.games.includes(selectedGame.id)).filter((account) => {
      const ps4 = account.slots.ps4.some((slot) => slot.status === 'available');
      const ps5 = account.slots.ps5.some((slot) => slot.status === 'available');
      const reset = [...account.slots.ps4, ...account.slots.ps5].some((slot) => slot.type === 'reset' && slot.status === 'available');
      const profit = getAccountStats(account).profit;
      return filter === 'all' || (filter === 'ps4' && ps4) || (filter === 'ps5' && ps5) || (filter === 'reset' && reset) || (filter === 'recovery' && profit < 0) || (filter === 'profit' && profit >= 0);
    });
  }, [accounts, selectedGame, filter, getAccountStats]);

  const chooseSlot = (account, consoleType) => {
    const slots = account.slots[consoleType];
    const normal = slots.find((slot) => slot.type === 'normal' && slot.status === 'available');
    const reset = slots.find((slot) => slot.type === 'reset' && slot.status === 'available');
    const slot = normal || reset;
    if (!slot) return;
    setSelected({ account, consoleType, slot });
    setForm((prev) => ({ ...prev, price: '0' }));
  };

  const submit = async (event) => {
    event.preventDefault();
    setSubmitting(true);
    try {
      await sellSlot({
        accountId: selected.account.id,
        slotId: selected.slot.id,
        price: parseFloat(form.price),
        customer: form.customer,
        gameId: selectedGame.id,
        note: form.note,
        payment: form.payment,
      });
      onComplete();
    } catch (error) {
      alert(error.message || 'Could not save sale. Please try again.');
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="nexus-page sell-page fade-in">
      <header className="page-top"><div><h1>Sell Slot</h1><p>Start with the game the customer wants.</p></div>{selectedGame && <button className="icon-shell" onClick={()=>{setSelectedGame(null); setSelected(null);}}><ChevronLeft size={21}/></button>}</header>
      {!selectedGame ? <section className="sell-panel"><div className="search-control"><Search size={17}/><input value={gameQuery} onChange={(e)=>setGameQuery(e.target.value)} placeholder="Search FIFA, GTA, Spider-Man..." autoFocus/></div><div className="game-select-grid">{filteredGames.map((game)=><button key={game.id} onClick={()=>setSelectedGame(game)}><Gamepad2 size={22}/><span>{game.name}</span></button>)}</div></section> : null}
      {selectedGame && !selected ? <><section className="selected-game"><CheckCircle2 size={18}/><span>{selectedGame.name}</span></section><div className="chip-scroll sell-filters">{[['all','All'],['ps4','PS4 available'],['ps5','PS5 available'],['reset','Reset ready'],['recovery','Needs recovery'],['profit','Profitable']].map(([id,label])=><button key={id} className={filter===id?'active':''} onClick={()=>setFilter(id)}>{label}</button>)}</div><section className="sell-match-list">{matches.map((account)=>{const stats=getAccountStats(account); return <article key={account.id} className="sell-match-card"><div className="match-top"><div><strong>{account.email}</strong><span>{account.region} - {account.condition}</span></div><b className={stats.profit>=0?'positive':'negative'}>{money(stats.profit)}</b></div><div className="slot-choice-grid"><ConsoleButton account={account} type="ps4" onChoose={chooseSlot}/><ConsoleButton account={account} type="ps5" onChoose={chooseSlot}/></div></article>})}</section></> : null}
      {selected ? <form className="sale-form-card" onSubmit={submit}><div className="sale-summary"><Gamepad2 size={18}/><div><strong>{selectedGame.name}</strong><span>{selected.account.email} - {selected.consoleType.toUpperCase()} {selected.slot.type}</span></div></div><label><span>Actual negotiated price</span><div><span className="currency-symbol">TSh</span><input type="number" step="0.01" value={form.price} onChange={(e)=>setForm({...form, price:e.target.value})} required/></div></label><label><span>Customer name / phone</span><div><User size={17}/><input value={form.customer} onChange={(e)=>setForm({...form, customer:e.target.value})} placeholder="Optional"/></div></label><label><span>Payment status</span><select value={form.payment} onChange={(e)=>setForm({...form, payment:e.target.value})}><option value="paid">Paid</option><option value="partial">Partial</option><option value="unpaid">Unpaid</option></select></label><label><span>Note</span><textarea value={form.note} onChange={(e)=>setForm({...form, note:e.target.value})}/></label><button className="confirm-sale" disabled={submitting}><Send size={18}/> {submitting ? 'Saving...' : 'Confirm sale'}</button></form> : null}
    </div>
  );
};
const ConsoleButton = ({ account, type, onChoose }) => { const slots=account.slots[type]; const normal=slots.find(s=>s.type==='normal'&&s.status==='available'); const reset=slots.find(s=>s.type==='reset'&&s.status==='available'); const locked=slots.some(s=>s.type==='reset'&&s.status==='locked'); const available=normal||reset; return <button className={`console-pick ${available?'available':'locked'}`} disabled={!available} onClick={()=>onChoose(account,type)}><strong>{type.toUpperCase()}</strong><span>{available ? `${available.type} slot ready` : locked ? 'reset locked' : 'sold out'}</span>{!available && <Lock size={14}/>}</button>; };
export default SellSlot;