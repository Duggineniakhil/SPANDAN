/**
 * Original line-art illustrations for SPANDAN (drawn for this project — no licence needed).
 * Monochrome with a single volt-green accent. Animations are CSS classes in styles.css.
 */
const INK = "#e8e8e8"; // main line colour
const DIM = "#3d3d3d"; // secondary lines
const FILL = "#101010"; // shape fill
const VOLT = "#ccff00"; // accent

const line = { stroke: INK, strokeWidth: 1.6, fill: FILL, strokeLinejoin: "round" as const };
const dim = { stroke: DIM, strokeWidth: 1.2, fill: "none" };

export function SensorArt({ className = "" }: { className?: string }) {
  return (
    <svg className={className} viewBox="0 0 200 160" role="img" aria-label="Clip-on vibration sensor on a motor">
      <g className="vib">
        <rect x="24" y="62" width="112" height="66" rx="12" {...line} />
        {[0, 1, 2, 3, 4, 5].map((i) => (
          <line key={i} x1={40 + i * 16} y1="62" x2={40 + i * 16} y2="128" {...dim} />
        ))}
        <rect x="92" y="38" width="40" height="26" rx="5" fill={VOLT} />
        <rect x="100" y="45" width="12" height="11" rx="2" fill="#000" />
        <circle cx="122" cy="50" r="3" fill="#000" className="blink" />
      </g>
      <path d="M150 64 q12 -10 0 -20 q-12 -10 0 -20" stroke={VOLT} strokeWidth="2" fill="none" className="wave-draw" />
      <path d="M168 70 q16 -16 0 -32 q-16 -16 0 -32" stroke={VOLT} strokeWidth="2" fill="none" opacity="0.5" className="wave-draw delay-1" />
      <line x1="10" y1="140" x2="190" y2="140" {...dim} strokeDasharray="2 4" />
    </svg>
  );
}

export function PhoneArt({ className = "", health = 41 }: { className?: string; health?: number }) {
  const c = 2 * Math.PI * 28;
  return (
    <svg className={className} viewBox="0 0 200 160" role="img" aria-label="Phone showing machine health">
      <g className="float">
        <rect x="66" y="8" width="70" height="144" rx="14" {...line} />
        <line x1="92" y1="16" x2="110" y2="16" stroke={DIM} strokeWidth="3" strokeLinecap="round" />
        <circle cx="101" cy="64" r="28" fill="none" stroke="#222" strokeWidth="6" />
        <circle cx="101" cy="64" r="28" fill="none" stroke={VOLT} strokeWidth="6" strokeLinecap="round"
          strokeDasharray={c} strokeDashoffset={c * (1 - health / 100)} transform="rotate(-90 101 64)" className="ring-fill" />
        <text x="101" y="70" textAnchor="middle" fontSize="16" fontWeight="700" fill={INK} fontFamily="Space Grotesk Variable, sans-serif">{health}%</text>
        <rect x="80" y="104" width="42" height="6" rx="3" fill={VOLT} />
        <rect x="80" y="116" width="28" height="5" rx="2.5" fill={DIM} />
      </g>
      <g className="float delay-1">
        <rect x="8" y="46" width="48" height="22" rx="4" fill="none" stroke={VOLT} />
        <text x="32" y="61" textAnchor="middle" fontSize="9" fontWeight="600" fill={VOLT} fontFamily="JetBrains Mono, monospace">ALERT</text>
      </g>
      <text x="166" y="66" textAnchor="middle" fontSize="8" fill="#777" fontFamily="JetBrains Mono, monospace">OFFLINE</text>
      <text x="166" y="78" textAnchor="middle" fontSize="8" fill="#777" fontFamily="JetBrains Mono, monospace">OK</text>
    </svg>
  );
}

export function CloudArt({ className = "" }: { className?: string }) {
  return (
    <svg className={className} viewBox="0 0 200 160" role="img" aria-label="Cloud models and AI agent planning the repair">
      <path d="M48 96 a24 24 0 0 1 8 -46 a34 34 0 0 1 64 -8 a26 26 0 0 1 30 54z" {...line} />
      <g className="spin-slow" style={{ transformOrigin: "100px 68px" }}>
        <circle cx="100" cy="68" r="16" fill="none" stroke={DIM} strokeWidth="1.5" strokeDasharray="4 4" />
      </g>
      <circle cx="100" cy="68" r="6" fill={VOLT} className="blink" />
      {[
        [42, 132, "₹1,450"],
        [100, 146, "MECHANIC"],
        [158, 132, "SUN 10:00"],
      ].map(([x, y, label], i) => (
        <g key={i} className={`pop delay-${i}`}>
          <line x1="100" y1="96" x2={x as number} y2={(y as number) - 10} stroke={DIM} strokeDasharray="2 3" />
          <rect x={(x as number) - 30} y={(y as number) - 10} width="60" height="17" rx="3" fill="#000" stroke={i === 0 ? VOLT : DIM} />
          <text x={x as number} y={(y as number) + 2} textAnchor="middle" fontSize="8" fill={i === 0 ? VOLT : INK} fontFamily="JetBrains Mono, monospace">{label}</text>
        </g>
      ))}
    </svg>
  );
}

export function OwnerArt({ className = "" }: { className?: string }) {
  return (
    <svg className={className} viewBox="0 0 200 160" role="img" aria-label="Mill owner approving the plan by voice">
      <circle cx="68" cy="54" r="18" {...line} />
      <path d="M34 142 q2 -54 34 -56 q32 2 34 56" {...line} />
      <g className="pop">
        <rect x="106" y="28" width="82" height="40" rx="6" fill={VOLT} />
        <path d="M120 68 l-8 12 l18 -12z" fill={VOLT} />
        <text x="147" y="54" textAnchor="middle" fontSize="15" fontWeight="700" fill="#000">ಹೌದು ✓</text>
      </g>
      <g stroke={VOLT} strokeWidth="2" fill="none" strokeLinecap="round">
        <path className="blink" d="M96 98 q8 8 0 16" />
        <path className="blink delay-1" d="M104 92 q14 14 0 28" />
        <path className="blink delay-2" d="M112 86 q20 20 0 40" />
      </g>
    </svg>
  );
}
