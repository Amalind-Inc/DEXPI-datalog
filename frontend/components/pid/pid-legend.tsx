"use client";

import type { SymbolKey } from "@/components/pid/pid-symbols";
import { symbolDataUri } from "@/components/pid/pid-symbols";

const SYMBOL_LEGEND: Array<{ key: SymbolKey; label: string }> = [
  { key: "pump", label: "Pump" },
  { key: "exchanger", label: "Heat exchanger" },
  { key: "vessel", label: "Vessel / tank" },
  { key: "column", label: "Column / tower" },
  { key: "valve", label: "Valve" },
  { key: "instrument", label: "Instrument" },
  { key: "generic", label: "Other tagged equipment" },
];

export function PidLegend({ onClose }: { onClose: () => void }) {
  return (
    <div className="pid-legend" role="dialog" aria-label="Diagram legend" data-testid="pid-legend">
      <header className="pid-legend-header">
        <span>Legend</span>
        <button type="button" onClick={onClose} aria-label="Close legend">
          ×
        </button>
      </header>

      <p className="pid-legend-section">Symbols</p>
      <ul className="pid-legend-grid">
        {SYMBOL_LEGEND.map((item) => (
          <li key={item.key}>
            <img src={symbolDataUri(item.key)} alt="" width={26} height={26} />
            <span>{item.label}</span>
          </li>
        ))}
      </ul>

      <p className="pid-legend-section">Lines</p>
      <ul className="pid-legend-lines">
        <li>
          <svg width="42" height="14" aria-hidden="true">
            <line x1="2" y1="7" x2="32" y2="7" stroke="#2563eb" strokeWidth="3" />
            <path d="M32 2 L40 7 L32 12 Z" fill="#2563eb" />
          </svg>
          <span>Process line — arrow shows flow direction</span>
        </li>
        <li>
          <svg width="42" height="14" aria-hidden="true">
            <line x1="2" y1="7" x2="40" y2="7" stroke="#94a3b8" strokeWidth="2" />
          </svg>
          <span>Connection (flow direction not shown)</span>
        </li>
      </ul>

      <p className="pid-legend-note">
        A compressed, P&amp;ID-style reading of the topology — equipment with their
        nozzles as ports, joined by collapsed process lines.
      </p>
    </div>
  );
}
