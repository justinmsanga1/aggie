import React from 'react';
import { X, ArrowUpCircle, ArrowDownCircle, MinusCircle, Wallet, Receipt } from 'lucide-react';
import './SideDrawer.css';

const money = (v) => new Intl.NumberFormat('en-TZ', { style: 'currency', currency: 'TZS', maximumFractionDigits: 0 }).format(Number(v || 0));
const positiveTypes = ['slot_sale', 'capital_in', 'adjustment'];

const iconFor = (type) => {
  if (type === 'slot_sale' || type === 'capital_in') return <ArrowUpCircle size={18} />;
  if (type === 'withdrawal') return <ArrowDownCircle size={18} />;
  if (type === 'expense') return <MinusCircle size={18} />;
  if (type === 'psn_deposit') return <Wallet size={18} />;
  return <Receipt size={18} />;
};

const SideDrawer = ({ isOpen, onClose, title, transactions }) => {
  if (!isOpen) return null;

  return (
    <div className="sidedrawer-layer" role="presentation">
      <button className="sidedrawer-backdrop" aria-label="Close" onClick={onClose} />
      <section className="sidedrawer-container" role="dialog" aria-modal="true" aria-label={title}>
        <div className="sidedrawer-header">
          <h3>{title}</h3>
          <button type="button" className="sidedrawer-close" onClick={onClose} aria-label="Close">
            <X size={20} />
          </button>
        </div>
        <div className="sidedrawer-body">
          {transactions.length === 0 ? (
            <div className="sidedrawer-empty">No transactions yet.</div>
          ) : (
            <div className="sidedrawer-list">
              {transactions.map((tx) => {
                const isPositive = positiveTypes.includes(tx.type);
                return (
                  <div key={tx.id} className="sidedrawer-row">
                    <div className={`sidedrawer-icon ${isPositive ? 'positive' : 'negative'}`}>{iconFor(tx.type)}</div>
                    <div className="sidedrawer-info">
                      <strong>{tx.note}</strong>
                      <span>{tx.type.replace('_', ' ')} - {tx.admin} - {tx.date}</span>
                    </div>
                    <div className={`sidedrawer-amount ${isPositive ? 'positive' : 'negative'}`}>{isPositive ? '+' : '-'}{money(tx.amount)}</div>
                  </div>
                );
              })}
            </div>
          )}
        </div>
      </section>
    </div>
  );
};

export default SideDrawer;
