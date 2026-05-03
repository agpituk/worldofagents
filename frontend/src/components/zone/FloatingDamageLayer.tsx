"use client";

import { FloatingDamage } from "./constants";

export default function FloatingDamageLayer({ floats }: { floats: FloatingDamage[] }) {
  return (
    <>
      {floats.map((f) => {
        const age = (Date.now() - f.born) / 1500;
        const opacity = Math.max(0, 1 - age);
        const drift = age * -16;
        return (
          <text
            key={f.id}
            x={f.x}
            y={f.y + drift}
            fill={f.color}
            fontSize={11}
            fontFamily="ui-monospace, monospace"
            fontWeight="bold"
            textAnchor="middle"
            opacity={opacity}
            pointerEvents="none"
          >
            {f.text}
          </text>
        );
      })}
    </>
  );
}
