import React, { useState } from 'react';
import { Search, Plus, ArrowUpCircle, ArrowDownCircle, MinusCircle, Wallet, Receipt, SlidersHorizontal, ChevronDown, ChevronUp } from 'lucide-react';
import { useStore } from '../context/StoreContext';
import Sheet from '../components/Sheet';
import './Ledger.css';

const money = (v) => new Intl.NumberFormat('en-TZ', { style: 'currency', currency: 'TZS', maximumFractionDigits: 0 }).format(Number(v || 0));
const positiveTypes = ['slot_sale', 'capital_in', 'adjustment'];

const Ledger = () => {
  const { transactions, walletStats, addTransaction } = useStore();
  const [activeFilter, setActiveFilter] = useState('all');
  const [query, setQuery] = useState('');
  const [isSheetOpen, setIsSheetOpen] = useState(false);
  const [saving, setSaving] = useState(false);
  const [showAll, setShowAll] = useState(false);

  const filtered = transactions.filter((tx) => {
    const byType = activeFilter === 'all' || tx.type === activeFilter;
    const haystack = `${tx.note} ${tx.admin} ${tx.type}`.toLowerCase();
    return byType && haystack.includes(query.toLowerCase());
  });

  const visible = showAll ? filtered : filtered.slice(0, 5);

  const submit = async (event) => {
    event.preventDefault();
    setSaving(true);
    try {
      const form = new FormData(event.target);
      await addTransaction({ type: form.get('type'), amount: parseFloat(form.get('amount')), note: form.get('note') });
      setIsSheetOpen(false);
    } catch (error) {
      alert(error.message || 'Could not save transaction.');
    } finally {
      setSaving(false);
    }
  };

  const iconFor = (type) => {
    if (type === 'slot_sale' || type === 'capital_in') return <ArrowUpCircle size={19} />;
    if (type === 'withdrawal') return <ArrowDownCircle size={19} />;
    if (type === 'expense') return <MinusCircle size={19} />;
    if (type === 'psn_deposit') return <Wallet size={19} />;
    return <Receipt size={19} />;
  };

  return (
    <div className="nexus-page ledger-page fade-in">
      <section className="ledger-balance-card">
        <div style={{display:'flex',justifyContent:'space-between',alignItems:'center'}}>
          <span>Business wallet</span>
          <button className="icon-shell" onClick={() => setIsSheetOpen(true)} style={{width:34,height:34,borderRadius:999}}><Plus size={18}/></button>
        </div>
        <strong>{money(walletStats.balance)}</strong>
        <div className="ledger-balance-grid">
          <div><small>Cash in</small><b>{money(walletStats.capitalIn + walletStats.adjustment)}</b></div>
          <div><small>Cash out</small><b>{money(walletStats.accountPurchase + walletStats.psnDeposit + walletStats.withdrawal + walletStats.expense)}</b></div>
          <div><small>Locked PSN</small><b>{money(walletStats.psnWalletsBalance)}</b></div>
        </div>
      </section>

      <section className="control-card">
        <div className="search-control"><Search size={17} /><input value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Search transaction, admin, account..." /></div>
        <div className="chip-scroll">
          {['all', 'capital_in', 'account_purchase', 'psn_deposit', 'slot_sale', 'withdrawal', 'expense', 'adjustment'].map((type) => (
            <button key={type} className={activeFilter === type ? 'active' : ''} onClick={() => setActiveFilter(type)}>{type === 'all' ? 'All' : type.replace('_', ' ')}</button>
          ))}
        </div>
      </section>

      <section className="ledger-list">
        {visible.map((tx) => {
          const isPositive = positiveTypes.includes(tx.type);
          return (
            <article key={tx.id} className="ledger-row">
              <div className={`ledger-icon ${isPositive ? 'positive' : 'negative'}`}>{iconFor(tx.type)}</div>
              <div className="ledger-info">
                <strong>{tx.note}</strong>
                <span>{tx.type.replace('_', ' ')} - {tx.admin} - {tx.date}</span>
              </div>
              <div className={`ledger-amount ${isPositive ? 'positive' : 'negative'}`}>{isPositive ? '+' : '-'}{money(tx.amount)}</div>
            </article>
          );
        })}
        {filtered.length > 5 && (
          <button className="ledger-toggle" onClick={() => setShowAll((s) => !s)}>
            {showAll ? <><ChevronUp size={16} /> Show Less</> : <><ChevronDown size={16} /> View All ({filtered.length})</>}
          </button>
        )}
      </section>

      <Sheet isOpen={isSheetOpen} onClose={() => setIsSheetOpen(false)} title="New Money Record">
        <form onSubmit={submit}>
          <div className="form-group"><label className="form-label">Type</label><select className="form-select" name="type"><option value="capital_in">Capital in</option><option value="withdrawal">Withdrawal</option><option value="expense">Expense</option><option value="adjustment">Adjustment</option></select></div>
          <div className="form-group"><label className="form-label">Amount</label><input className="form-input" name="amount" type="number" step="0.01" required /></div>
          <div className="form-group"><label className="form-label">Note</label><textarea className="form-textarea" name="note" required /></div>
          <button className="sheet-submit-btn">Record</button>
        </form>
      </Sheet>
    </div>
  );
};
export default Ledger;