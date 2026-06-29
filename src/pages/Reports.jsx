import React, { useMemo, useState } from 'react';
import { BarChart3, Crown, CalendarDays, Download, RotateCcw, TrendingUp, TrendingDown, Wallet } from 'lucide-react';
import { useStore } from '../context/StoreContext';
import './Reports.css';

const money = (v) => new Intl.NumberFormat('en-TZ', { style: 'currency', currency: 'TZS', maximumFractionDigits: 0 }).format(Number(v || 0));

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

const Reports = () => {
  const { accounts, transactions, walletStats } = useStore();
  const [period, setPeriod] = useState('month');

  const filteredTxs = useMemo(() => transactions.filter((tx) => isInPeriod(tx.date, period)), [transactions, period]);

  const periodStats = useMemo(() => {
    let capitalIn = 0;
    let accountPurchase = 0;
    let psnDeposit = 0;
    let slotSale = 0;
    let withdrawal = 0;
    let expense = 0;
    let adjustment = 0;
    const accountNet = {};
    filteredTxs.forEach((t) => {
      const amount = Number(t.amount || 0);
      switch (t.type) {
        case 'capital_in': capitalIn += amount; break;
        case 'account_purchase': accountPurchase += amount; if (t.accountId) accountNet[t.accountId] = (accountNet[t.accountId] || 0) - amount; break;
        case 'psn_deposit': psnDeposit += amount; if (t.accountId) accountNet[t.accountId] = (accountNet[t.accountId] || 0) - amount; break;
        case 'slot_sale': slotSale += amount; if (t.accountId) accountNet[t.accountId] = (accountNet[t.accountId] || 0) + amount; break;
        case 'withdrawal': withdrawal += amount; break;
        case 'expense': expense += amount; if (t.accountId) accountNet[t.accountId] = (accountNet[t.accountId] || 0) - amount; break;
        case 'adjustment': adjustment += amount; break;
      }
    });
    let accountProfit = 0;
    let accountLoss = 0;
    Object.values(accountNet).forEach(net => {
      if (net > 0) accountProfit += net;
      else accountLoss += Math.abs(net);
    });
    const balance = capitalIn + adjustment - accountPurchase - psnDeposit - withdrawal - expense;
    const profit = slotSale - expense;
    return {
      revenue: slotSale, profit, capitalIn,
      totalSpent: capitalIn - balance,
      totalInvested: capitalIn,
      accountProfit, accountLoss,
    };
  }, [filteredTxs]);

  const topGames = useMemo(() => {
    const map = new Map();
    filteredTxs.filter(t=>t.type==='slot_sale').forEach((tx)=>{ const name=(tx.note||'').replace('Sold slot for game: ','') || 'Unknown'; map.set(name,(map.get(name)||0)+tx.amount); });
    return [...map.entries()].sort((a,b)=>b[1]-a[1]).slice(0,5);
  }, [filteredTxs]);
  const resetList = accounts.filter(a=>a.nextDeactivation).slice(0,6);
  const getExpenses = (accId) => transactions.filter(t=>t.accountId===accId&&t.type==='expense').reduce((s,t)=>s+Number(t.amount||0),0);
  const unrecovered = accounts.filter((a)=>a.revenue < (Number(a.purchaseCost||0)+Number(a.psnDeposits||0)+getExpenses(a.id)));

  const downloadReport = () => {
    const lines = [];
    lines.push('PSN MANAGER — BUSINESS REPORT');
    lines.push(`Period: ${period}  |  ${new Date().toLocaleString()}`);
    lines.push('');
    lines.push('SUMMARY');
    lines.push(`Revenue:       ${money(periodStats.revenue)}`);
    lines.push(`Profit:        ${money(periodStats.accountProfit)}`);
    lines.push(`Loss:          ${money(periodStats.accountLoss)}`);
    lines.push(`Capital:       ${money(periodStats.totalInvested)}`);
    lines.push(`Total spent:   ${money(periodStats.totalSpent)}`);
    lines.push(`Total balance:   ${money(walletStats.balance + periodStats.revenue)}`);
    lines.push(`Unrecovered:   ${unrecovered.length} account(s)`);
    lines.push('');
    lines.push('TOP GAMES');
    if (topGames.length) {
      topGames.forEach(([name, total], i) => {
        lines.push(`${i + 1}. ${name.padEnd(35)} ${money(total)}`);
      });
    } else {
      lines.push('(no sales yet)');
    }
    lines.push('');
    lines.push('RESET SCHEDULE');
    if (resetList.length) {
      resetList.forEach((a) => {
        lines.push(`${a.email.padEnd(35)} ${a.nextDeactivation}`);
      });
    } else {
      lines.push('(no reset dates)');
    }
    lines.push('');
    const text = lines.join('\n');
    const blob = new Blob([text], { type: 'text/plain' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `psn-report-${period.replace(' ', '-')}-${new Date().toISOString().slice(0, 10)}.txt`;
    a.click();
    URL.revokeObjectURL(url);
  };

  return <div className="nexus-page reports-page fade-in"><header className="page-top"></header><div className="control-row" style={{marginBottom:12}}><div className="chip-scroll">{['today','week','month','all time'].map(p=><button key={p} className={period===p?'active':''} onClick={()=>setPeriod(p)}>{p}</button>)}</div><button className="icon-shell" onClick={downloadReport}><Download size={18}/></button></div><section className="report-hero"><div><span>Sales revenue</span><strong>{money(periodStats.revenue)}</strong><small>{period} performance</small></div><div className="mini-bars">{[32,62,46,78,52,88,69].map((h,i)=><i key={i} style={{height:`${h}%`}} />)}</div></section><section className="report-grid"><ReportCard icon={<TrendingUp/>} label="Total spent" value={money(periodStats.totalSpent)} tone='negative'/><ReportCard icon={<BarChart3/>} label="Total capital" value={money(periodStats.totalInvested)}/><ReportCard icon={<TrendingUp/>} label="Profit" value={money(periodStats.accountProfit)} tone='positive'/><ReportCard icon={<TrendingDown/>} label="Loss" value={money(periodStats.accountLoss)} tone='negative'/><ReportCard icon={<Wallet/>} label="Total balance" value={money(walletStats.balance + periodStats.revenue)}/><ReportCard icon={<Crown/>} label="Best game" value={topGames[0]?.[0] || 'No sales'}/><ReportCard icon={<RotateCcw/>} label="Unrecovered" value={unrecovered.length}/></section><section className="report-card"><h3>Top Games</h3>{topGames.length?topGames.map(([name,total],i)=><div className="rank-row" key={name}><span>#{i+1}</span><strong>{name}</strong><b>{money(total)}</b></div>):<p className="empty-line">No sales yet.</p>}</section><section className="report-card"><h3>Reset Schedule</h3>{resetList.length?resetList.map((account)=><div className="rank-row" key={account.id}><CalendarDays size={16}/><strong>{account.email}</strong><b>{account.nextDeactivation}</b></div>):<p className="empty-line">No reset dates yet.</p>}</section></div>;
};
const ReportCard = ({ icon, label, value, tone='' }) => <div className={`report-mini ${tone}`}><span>{icon}</span><small>{label}</small><strong>{value}</strong></div>;
export default Reports;