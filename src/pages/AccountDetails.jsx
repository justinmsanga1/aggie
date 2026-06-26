import React, { useState } from 'react';
import { ArrowLeft, Copy, Wallet, Gamepad2, RotateCcw, Archive, Shield, Globe2, Clock3, Plus } from 'lucide-react';
import { useStore } from '../context/StoreContext';
import Sheet from '../components/Sheet';
import './AccountDetails.css';

const money = (v) => new Intl.NumberFormat('en-TZ', { style: 'currency', currency: 'TZS', maximumFractionDigits: 0 }).format(Number(v || 0));

const AccountDetails = ({ id, accountId, onBack }) => {
  const selectedId = id || accountId;
  const { accounts, games, transactions, getAccountStats, addTransaction, recordGamePurchase, markDeactivated, updateAccount } = useStore();
  const [sheet, setSheet] = useState(null);
  const [busy, setBusy] = useState(false);
  const account = accounts.find((item) => item.id === selectedId);
  if (!account) return <div className="details-page"><button className="icon-shell" onClick={onBack}><ArrowLeft size={20}/></button><p>Account not found.</p></div>;
  const stats = getAccountStats(account);
  const accountTx = transactions.filter((tx) => tx.accountId === account.id);
  const gameNames = account.games.map((gid) => games.find((game) => game.id === gid)).filter(Boolean);

  const deposit = async (event) => {
    event.preventDefault();
    try {
      const form = new FormData(event.target);
      await addTransaction({
        type: 'psn_deposit',
        amount: parseFloat(form.get('amount')),
        accountId: account.id,
        note: `Deposit to ${account.email}`,
      });
      setSheet(null);
    } catch (error) {
      alert(error.message || 'Could not save deposit.');
    }
  };
  const buyGame = async (event) => {
    event.preventDefault();
    try {
      const form = new FormData(event.target);
      await recordGamePurchase(account.id, form.get('gameId'), parseFloat(form.get('cost')));
      setSheet(null);
    } catch (error) {
      alert(error.message || 'Could not record game purchase.');
    }
  };
  const deactivate = async () => {
    if (busy) return;
    setBusy(true);
    try {
      await markDeactivated(account.id);
    } catch (error) {
      alert(error.message || 'Could not deactivate account.');
    } finally {
      setBusy(false);
    }
  };
  const archive = async () => {
    if (busy) return;
    setBusy(true);
    try {
      await updateAccount(account.id, { condition: 'archived', status: 'archived' });
    } catch (error) {
      alert(error.message || 'Could not archive account.');
    } finally {
      setBusy(false);
    }
  };

  return <div className="nexus-page details-page fade-in">
    <header className="details-top"><button className="icon-shell" onClick={onBack}><ArrowLeft size={20}/></button><div><span className="eyebrow">Account profile</span><h1>{account.email}</h1><p>{account.region} - {account.condition}</p></div><button className="icon-shell"><Copy size={19}/></button></header>
    <section className="detail-hero"><div className="detail-meta"><span><Shield size={14}/>{account.status}</span><span><Globe2 size={14}/>{account.region}</span><span><Clock3 size={14}/>{account.nextDeactivation || 'No reset date'}</span></div><div className="detail-money"><div><small>Profit / loss</small><b className={stats.profit>=0?'positive':'negative'}>{money(stats.profit)}</b></div><div><small>Total invested</small><b>{money(stats.totalInvested)}</b></div><div><small>Revenue</small><b>{money(account.revenue)}</b></div><div><small>PSN left</small><b>{money(stats.psnBalance)}</b></div></div></section>
    <section className="detail-actions"><button onClick={()=>setSheet('deposit')}><Wallet size={18}/>Deposit</button><button onClick={()=>setSheet('game')}><Gamepad2 size={18}/>Buy Game</button><button onClick={deactivate}><RotateCcw size={18}/>Deactivate</button><button onClick={archive}><Archive size={18}/>Archive</button></section>
    <section className="detail-card"><div className="section-head"><div><h3>Slot Map</h3><p>Normal and reset state by console</p></div></div><div className="deep-slots"><SlotBlock title="PS4" slots={account.slots.ps4}/><SlotBlock title="PS5" slots={account.slots.ps5}/></div></section>
    <section className="detail-card"><div className="section-head"><div><h3>Games</h3><p>Games attached to this account</p></div><button onClick={()=>setSheet('game')}><Plus size={15}/>Add</button></div><div className="detail-games">{gameNames.map((game)=><div key={game.id}><Gamepad2 size={18}/><span>{game.name}</span><b>{money(game.price)}</b></div>)}</div></section>
    <section className="detail-card"><div className="section-head"><div><h3>Account Ledger</h3><p>Account-specific money and sales timeline</p></div></div><div className="detail-timeline">{accountTx.length?accountTx.map((tx)=><div key={tx.id}><span>{tx.date}</span><strong>{tx.note}</strong><b className={['slot_sale','psn_deposit'].includes(tx.type)?'positive':'negative'}>{money(tx.amount)}</b></div>):<p className="empty-line">No account transactions yet.</p>}</div></section>
    <Sheet isOpen={sheet==='deposit'} onClose={()=>setSheet(null)} title="Deposit to PSN wallet"><form onSubmit={deposit}><div className="form-group"><label className="form-label">Amount</label><input className="form-input" name="amount" type="number" step="0.01" required/></div><button className="sheet-submit-btn">Confirm deposit</button></form></Sheet>
    <Sheet isOpen={sheet==='game'} onClose={()=>setSheet(null)} title="Buy game"><form onSubmit={buyGame}><div className="form-group"><label className="form-label">Game</label><select className="form-select" name="gameId">{games.map((game)=><option key={game.id} value={game.id}>{game.name}</option>)}</select></div><div className="form-group"><label className="form-label">Cost</label><input className="form-input" name="cost" type="number" step="0.01" required/></div><button className="sheet-submit-btn">Record purchase</button></form></Sheet>
  </div>;
};
const SlotBlock = ({ title, slots }) => <div className="slot-block"><h4>{title}</h4>{slots.map((slot, index)=><div key={slot.id} className={`slot-detail ${slot.status}`}><span>{slot.type === 'normal' ? `Normal ${index+1}` : 'Reset cycle'}</span><b>{slot.status}</b></div>)}</div>;
export default AccountDetails;