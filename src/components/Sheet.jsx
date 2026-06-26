import React from 'react';
import { X } from 'lucide-react';
import './Sheet.css';

const Sheet = ({ isOpen, onClose, title, children }) => {
  if (!isOpen) return null;

  return (
    <div className="sheet-layer" role="presentation">
      <button className="sheet-backdrop" aria-label="Close sheet" onClick={onClose} />
      <section className="sheet-container" role="dialog" aria-modal="true" aria-label={title}>
        <div className="sheet-header">
          <h3>{title}</h3>
          <button type="button" className="sheet-close" onClick={onClose} aria-label="Close">
            <X size={20} />
          </button>
        </div>
        <div className="sheet-body">
          {children}
        </div>
      </section>
    </div>
  );
};

export default Sheet;