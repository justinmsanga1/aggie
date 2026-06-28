import React, { useMemo, useState } from 'react';
import {
  Bell,
  Search,
  Settings,
  Wallet,
  Plus,
  ShoppingCart,
  ReceiptText,
  Send,
  TrendingUp,
  RotateCcw,
  AlertTriangle,
  ChevronRight,
  ShieldCheck,
  Clock3,
  Banknote,
  ArrowUpCircle,
  ArrowDownCircle,
  MinusCircle,
  Receipt
} from 'lucide-react';
import { useStore } from '../context/StoreContext';
import Sheet from '../components/Sheet';
import SideDrawer from '../components/SideDrawer';
import './Dashboard.css';

const currency = (value) => new Intl.NumberFormat('en-US', {
  style: 'currency',
  currency: 'TZS',
  maximumFractionDigits: 0
}).format(Number(value || 0));

const isInPeriod = (dateStr, period) => {
  if (period === 'all time') return true;
  const date = new Date(dateStr);
  const now = new Date();
  const diff = now - date;
  const msPerDay = 86400000;
  if (period === 'today') return diff < msPerDay && date.getDate() === now.getDate();
  if (period === 'week') return diff < 7 * msPerDay;
  if (period === 'month') return diff < 30 * msPerDay;
  return true;
};

const Dashboard = ({ onAction }) => {
  const { walletStats, accounts, transactions, addTransaction, games, currentAdmin } = useStore();
  const [sheet, setSheet] = useState(null);
  const [saving, setSaving] = useState(false);
  const [showSearch, setShowSearch] = useState(false);
  const [searchQuery, setSearchQuery] = useState('');
  const [showAllTx, setShowAllTx] = useState(false);
  const [period, setPeriod] = useState('all time');

  const filteredTransactions = useMemo(() =>
    transactions.filter((tx) => isInPeriod(tx.date, period)),
  [transactions, period]);

  const periodStats = useMemo(() => {
    let capitalIn = 0;
    let accountPurchase = 0;
    let psnDeposit = 0;
    let slotSale = 0;
    let withdrawal = 0;
    let expense = 0;
    let adjustment = 0;

    filteredTransactions.forEach(t => {
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

    return {
      capitalIn, accountPurchase, psnDeposit, slotSale, withdrawal, expense, adjustment,
      totalInvested: capitalIn,
      revenue: slotSale,
      totalSpent: accountPurchase + psnDeposit + expense + withdrawal,
      cashIn: capitalIn + slotSale,
      cashOut: accountPurchase + psnDeposit + expense + withdrawal,
    };
  }, [filteredTransactions]);

  const searchResults = useMemo(() => {
    if (!searchQuery.trim()) return [];
    const q = searchQuery.toLowerCase();
    return accounts.filter((acc) => {
      const names = acc.games.map((id) => games.find((g) => g.id === id)?.name || '').join(' ');
      return `${acc.email} ${acc.region} ${names}`.toLowerCase().includes(q);
    }).slice(0, 8);
  }, [searchQuery, accounts, games]);

  const resetAvailable = useMemo(() => accounts.reduce((sum, account) => {
    const slots = [...account.slots.ps4, ...account.slots.ps5];
    return sum + slots.filter((slot) => slot.type === 'reset' && slot.status === 'available').length;
  }, 0), [accounts]);

  const readyToDeactivate = useMemo(() => accounts.filter((account) => {
    const ps4NormalSold = account.slots.ps4.filter((slot) => slot.type === 'normal' && slot.status === 'sold').length;
    const ps5NormalSold = account.slots.ps5.filter((slot) => slot.type === 'normal' && slot.status === 'sold').length;
    const resetLocked = [...account.slots.ps4, ...account.slots.ps5].some((slot) => slot.type === 'reset' && slot.status === 'locked');
    return ps4NormalSold >= 2 && ps5NormalSold >= 2 && resetLocked;
  }).length, [accounts]);

  const unrecovered = useMemo(() => accounts.filter((account) => {
    const invested = account.purchaseCost + account.psnDeposits + account.expenses.reduce((sum, expense) => sum + expense.amount, 0);
    return account.revenue < invested;
  }).length, [accounts]);

  const positiveTypes = useMemo(() => ['slot_sale', 'capital_in', 'adjustment'], []);

  const recentTransactions = useMemo(() => filteredTransactions
    .slice(0, 5)
    .map((transaction) => ({
      ...transaction,
      isPositive: positiveTypes.includes(transaction.type),
    })), [filteredTransactions, positiveTypes]);

  const iconFor = (type) => {
    if (type === 'slot_sale' || type === 'capital_in') return <ArrowUpCircle size={18} />;
    if (type === 'withdrawal') return <ArrowDownCircle size={18} />;
    if (type === 'expense') return <MinusCircle size={18} />;
    if (type === 'psn_deposit') return <Wallet size={18} />;
    return <Receipt size={18} />;
  };

  const handleSheetSubmit = async (event) => {
    event.preventDefault();
    setSaving(true);
    try {
      const formData = new FormData(event.target);
      await addTransaction({
        type: sheet,
        amount: parseFloat(formData.get('amount')),
        note: formData.get('note'),
      });
      setSheet(null);
      event.target.reset();
    } catch (error) {
      alert(error.message || 'Could not save transaction. Please try again.');
    } finally {
      setSaving(false);
    }
  };

  const closeSheet = () => {
    if (saving) return;
    setSheet(null);
  };

  const metrics = [
    { label: 'Total capital', value: currency(periodStats.totalInvested), tone: 'info' },
    { label: 'Sales revenue', value: currency(periodStats.revenue), tone: 'success' },
    { label: 'Total spent', value: currency(periodStats.totalSpent), tone: 'danger' },
    { label: 'PSN wallet locked', value: currency(walletStats.psnWalletsBalance), tone: 'muted' },
    { label: 'Withdrawn profit', value: currency(periodStats.withdrawal), tone: 'danger' }
  ];

  const quickActions = [
    { label: 'Add Money', icon: Plus, onClick: () => setSheet('capital_in') },
    { label: 'Buy Account', icon: ShoppingCart, onClick: () => onAction('accounts') },
    { label: 'Sell Slot', icon: Send, onClick: () => onAction('sell') },
    { label: 'Expense', icon: ReceiptText, onClick: () => setSheet('expense') }
  ];

  return (
    <div className="nexus-dashboard fade-in">
      <header className="nexus-topbar">
        <div className="admin-cluster">
          <h1>PSN Manager</h1>
        </div>
        <div className="topbar-actions">
          <button aria-label="Search" onClick={() => { setShowSearch((s) => !s); setSearchQuery(''); }}><Search size={20} /></button>
          <button aria-label="Settings" onClick={() => onAction('settings')}><Settings size={20} /></button>
          <button aria-label="Notifications"><Bell size={20} /></button>
        </div>
      </header>
      {showSearch && <div className="dashboard-search"><div className="search-control"><Search size={17} /><input value={searchQuery} onChange={(e) => setSearchQuery(e.target.value)} placeholder="Search accounts by email or game..." autoFocus /></div>{searchResults.length > 0 && <div className="dashboard-search-results">{searchResults.map((acc) => <button key={acc.id} className="dashboard-search-item" onClick={() => { setShowSearch(false); setSearchQuery(''); onAction('accounts'); }}><strong>{acc.email}</strong><span>{acc.region} - {acc.games.map((id) => games.find((g) => g.id === id)?.name).filter(Boolean).join(', ')}</span></button>)}</div>}</div>}

      <main className="dashboard-stack">
        <section className="wallet-panel">
          <div className="wallet-panel-glow" />
          <div className="wallet-row">
            <span className="eyebrow">Business wallet balance</span>
            <button className="icon-shell" onClick={() => setSheet('capital_in')} style={{width:34,height:34,borderRadius:999}}><Plus size={18}/></button>
          </div>
          <div className="wallet-amount-row">
            <h2>{currency(walletStats.balance)}</h2>
            <Wallet size={30} />
          </div>
          <div className="wallet-progress">
            <span style={{ width: `${Math.min(100, Math.max(12, (periodStats.revenue / Math.max(periodStats.totalInvested, 1)) * 100))}%` }} />
          </div>
          <div className="wallet-foot">
            <div><span>Cash in</span><strong>{currency(periodStats.cashIn)}</strong></div>
            <div><span>Cash out</span><strong>{currency(periodStats.cashOut)}</strong></div>
          </div>
        </section>

        <div className="chip-scroll" style={{marginBottom: 12}}>
          {['today','week','month','all time'].map((p) => (
            <button key={p} className={period === p ? 'active' : ''} onClick={() => setPeriod(p)}>{p}</button>
          ))}
        </div>

        <section className="quick-action-grid">
          {quickActions.map((action) => {
            const Icon = action.icon;
            return (
              <button key={action.label} className="nexus-action" onClick={action.onClick}>
                <span><Icon size={22} /></span>
                <strong>{action.label}</strong>
              </button>
            );
          })}
        </section>

        <section className="metric-grid">
          {metrics.map((metric) => (
            <div key={metric.label} className={`metric-card ${metric.tone}`}>
              <span>{metric.label}</span>
              <strong>{metric.value}</strong>
            </div>
          ))}
        </section>

        <section className="section-card">
          <div className="section-head">
            <div>
              <h3>Recent Activity</h3>
              <p>Latest 5 transactions ({period})</p>
            </div>
            <button onClick={() => setShowAllTx(true)}>View All</button>
          </div>
          <div className="sales-list">
            {recentTransactions.length ? recentTransactions.map((tx) => (
              <div className="sale-row" key={tx.id}>
                <div className={`sale-icon ${tx.isPositive ? 'positive' : 'negative'}`}>{iconFor(tx.type)}</div>
                <div className="sale-info">
                  <strong>{tx.note}</strong>
                  <span>{tx.type.replace('_', ' ')} - {tx.admin}</span>
                  <small>{tx.date}</small>
                </div>
                <div className={`sale-amount ${tx.isPositive ? '' : 'negative'}`}>{tx.isPositive ? '+' : '-'}{currency(tx.amount)}</div>
              </div>
            )) : (
              <div className="empty-line">No transactions yet.</div>
            )}
          </div>
        </section>

        <section className="section-card action-watch">
          <div className="section-head">
            <div>
              <h3>Accounts Needing Action</h3>
              <p>Reset, recovery, and account health</p>
            </div>
          </div>
          <button className="watch-row" onClick={() => onAction('accounts')}>
            <span className="watch-icon amber"><RotateCcw size={18} /></span>
            <span><strong>{readyToDeactivate} ready to deactivate</strong><small>Normal slots sold and reset slot waiting</small></span>
            <ChevronRight size={18} />
          </button>
          <button className="watch-row" onClick={() => onAction('sell')}>
            <span className="watch-icon green"><ShieldCheck size={18} /></span>
            <span><strong>{resetAvailable} reset slots available now</strong><small>Ready to sell after deactivation</small></span>
            <ChevronRight size={18} />
          </button>
          <button className="watch-row" onClick={() => onAction('reports')}>
            <span className="watch-icon red"><AlertTriangle size={18} /></span>
            <span><strong>{unrecovered} unrecovered accounts</strong><small>Revenue is still below invested money</small></span>
            <ChevronRight size={18} />
          </button>
        </section>

        <section className="reset-strip">
          <div><Clock3 size={17} /> Reset slots available</div>
          <strong>{resetAvailable}</strong>
          <div><Banknote size={17} /> PSN locked</div>
          <strong>{currency(walletStats.psnWalletsBalance)}</strong>
        </section>
      </main>

      <Sheet isOpen={!!sheet} onClose={closeSheet} title={sheet === 'capital_in' ? 'Add Business Capital' : sheet === 'expense' ? 'Record Expense' : 'Withdraw Funds'}>
        <form key={sheet || 'closed'} onSubmit={handleSheetSubmit}>
          <div className="form-group">
            <label className="form-label">Amount (TZS)</label>
            <input type="number" step="0.01" name="amount" className="form-input" required autoFocus />
          </div>
          <div className="form-group">
            <label className="form-label">Note / Description</label>
            <textarea name="note" className="form-textarea" placeholder="Describe the transaction..." required />
          </div>
          <button type="submit" className={`sheet-submit-btn ${sheet === 'expense' || sheet === 'withdrawal' ? 'danger' : ''}`} disabled={saving}>
            {saving ? 'Saving...' : sheet === 'capital_in' ? 'Deposit Capital' : 'Confirm Transaction'}
          </button>
        </form>
      </Sheet>

      <SideDrawer isOpen={showAllTx} onClose={() => setShowAllTx(false)} title="All Transactions" transactions={transactions} />
    </div>
  );
};

export default Dashboard;