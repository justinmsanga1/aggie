import React, { useMemo, useState } from 'react';
import { BarChart3, Crown, CalendarDays, Download, RotateCcw, TrendingUp } from 'lucide-react';
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
    let slotSale = 0;
    let expense = 0;
    filteredTxs.forEach((t) => {
      const amount = Number(t.amount || 0);
      if (t.type === 'slot_sale') slotSale += amount;
      if (t.type === 'expense') expense += amount;
    });
    const profit = slotSale - expense;
    return { revenue: slotSale, profit };
  }, [filteredTxs]);

  const topGames = useMemo(() => {
    const map = new Map();
    filteredTxs.filter(t=>t.type==='slot_sale').forEach((tx)=>{ const name=(tx.note||'').replace('Sold slot for game: ','') || 'Unknown'; map.set(name,(map.get(name)||0)+tx.amount); });
    return [...map.entries()].sort((a,b)=>b[1]-a[1]).slice(0,5);
  }, [filteredTxs]);
  const resetList = accounts.filter(a=>a.nextDeactivation).slice(0,6);
  const unrecovered = accounts.filter((a)=>a.revenue < (a.purchaseCost + a.psnDeposits));

  const downloadReport = () => {
    const lines = [];
    lines.push('═══════════════════════════════════════');
    lines.push('  PSN MANAGER — BUSINESS REPORT');
    lines.push('═══════════════════════════════════════');
    lines.push(`  Period:        ${period}`);
    lines.push(`  Generated:     ${new Date().toLocaleString()}`);
    lines.push('───────────────────────────────────────');
    lines.push('  SUMMARY');
    lines.push('───────────────────────────────────────');
    lines.push(`  Revenue:       ${money(periodStats.revenue)}`);
    lines.push(`  Profit:        ${money(periodStats.profit)}`);
    lines.push(`  Invested:      ${money(walletStats.totalInvested)}`);
    lines.push(`  Unrecovered:   ${unrecovered.length} account(s)`);
    lines.push('');
    lines.push('───────────────────────────────────────');
    lines.push('  TOP GAMES');
    lines.push('───────────────────────────────────────');
    if (topGames.length) {
      topGames.forEach(([name, total], i) => {
        lines.push(`  ${i + 1}. ${name.padEnd(35)} ${money(total)}`);
      });
    } else {
      lines.push('  (no sales yet)');
    }
    lines.push('');
    lines.push('───────────────────────────────────────');
    lines.push('  RESET SCHEDULE');
    lines.push('───────────────────────────────────────');
    if (resetList.length) {
      resetList.forEach((a) => {
        lines.push(`  ${a.email.padEnd(35)} ${a.nextDeactivation}`);
      });
    } else {
      lines.push('  (no reset dates)');
    }
    lines.push('');
    lines.push('═══════════════════════════════════════');
    const text = lines.join('\n');
    const blob = new Blob([text], { type: 'text/plain' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `psn-report-${period.replace(' ', '-')}-${new Date().toISOString().slice(0, 10)}.txt`;
    a.click();
    URL.revokeObjectURL(url);
  };

  return <div className="nexus-page reports-page fade-in"><header className="page-top"></header><div className="chip-scroll report-periods">{['today','week','month','all time'].map(p=><button key={p} className={period===p?'active':''} onClick={()=>setPeriod(p)}>{p}</button>)}<button className="icon-shell" style={{marginLeft:'auto'}} onClick={downloadReport}><Download size={18}/></button></div><section className="report-hero"><div><span>Sales revenue</span><strong>{money(periodStats.revenue)}</strong><small>{period} performance</small></div><div className="mini-bars">{[32,62,46,78,52,88,69].map((h,i)=><i key={i} style={{height:`${h}%`}} />)}</div></section><section className="report-grid"><ReportCard icon={<TrendingUp/>} label="Profit / loss" value={money(periodStats.profit)} tone={periodStats.profit>=0?'positive':'negative'}/><ReportCard icon={<BarChart3/>} label="Total invested" value={money(walletStats.totalInvested)}/><ReportCard icon={<Crown/>} label="Best game" value={topGames[0]?.[0] || 'No sales'}/><ReportCard icon={<RotateCcw/>} label="Unrecovered" value={unrecovered.length}/></section><section className="report-card"><h3>Top Games</h3>{topGames.length?topGames.map(([name,total],i)=><div className="rank-row" key={name}><span>#{i+1}</span><strong>{name}</strong><b>{money(total)}</b></div>):<p className="empty-line">No sales yet.</p>}</section><section className="report-card"><h3>Reset Schedule</h3>{resetList.length?resetList.map((account)=><div className="rank-row" key={account.id}><CalendarDays size={16}/><strong>{account.email}</strong><b>{account.nextDeactivation}</b></div>):<p className="empty-line">No reset dates yet.</p>}</section></div>;
};
const ReportCard = ({ icon, label, value, tone='' }) => <div className={`report-mini ${tone}`}><span>{icon}</span><small>{label}</small><strong>{value}</strong></div>;
export default Reports;