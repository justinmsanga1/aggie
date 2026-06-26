import React from 'react';
import { User, Moon, Sun, Database, Download, Share2, ShieldCheck, RefreshCcw } from 'lucide-react';
import { useStore } from '../context/StoreContext';
import './Settings.css';

const Settings = () => {
  const { currentAdmin, theme, toggleTheme, accounts, transactions, dbReady, dbError, hasSupabaseConfig, refreshData } = useStore();
  const exportData = () => { const blob = new Blob([JSON.stringify({ accounts, transactions }, null, 2)], { type:'application/json' }); const url = URL.createObjectURL(blob); const a=document.createElement('a'); a.href=url; a.download=`psn-manager-backup-${new Date().toISOString().slice(0,10)}.json`; a.click(); URL.revokeObjectURL(url); };
  const supabaseStatus = !hasSupabaseConfig ? 'Not configured' : dbReady ? 'Connected' : dbError ? 'Error' : 'Connecting...';
  return <div className="nexus-page settings-page fade-in"><header className="page-top"></header><section className="settings-profile"><div className="settings-avatar"><User size={28}/></div><div><strong>{currentAdmin.name}</strong><span>Equal admin access</span></div><b><ShieldCheck size={15}/>Active</b></section><section className="settings-card"><h3>Admins</h3><div className="settings-row"><User size={18}/><span>Admin 1</span><b>Full access</b></div><div className="settings-row"><User size={18}/><span>Admin 2</span><b>Full access</b></div></section><section className="settings-card"><h3>Preferences</h3><button className="settings-row" onClick={toggleTheme}>{theme==='dark'?<Moon size={18}/>:<Sun size={18}/>}<span>Theme</span><b>{theme}</b></button><div className="settings-row"><RefreshCcw size={18}/><span>Currency</span><b>TZS</b></div></section><section className="settings-card"><h3>Backup</h3><button className="settings-row" onClick={refreshData} disabled={!hasSupabaseConfig}><Database size={18}/><span>Supabase</span><b className={dbReady ? 'positive' : ''}>{supabaseStatus}</b></button><div className="settings-row muted"><Share2 size={18}/><span>Google Sheets</span><b>Pending</b></div><button className="settings-row" onClick={exportData}><Download size={18}/><span>Manual JSON export</span><b>Download</b></button></section><footer className="settings-footer">Nexus PSN Ledger</footer></div>;
};
export default Settings;
