"use client";

import { ImpactFlash, TILE } from "./constants";

export default function ImpactFlashLayer({ flashes }: { flashes: ImpactFlash[] }) {
  return (
    <>
      {flashes.map((f) => {
        const age = (Date.now() - f.born) / 350;
        const opacity = Math.max(0, 0.6 * (1 - age));
        return (
          <rect
            key={f.id}
            x={f.tx * TILE}
            y={f.ty * TILE}
            width={TILE}
            height={TILE}
            fill={f.color}
            opacity={opacity}
            pointerEvents="none"
          />
        );
      })}
    </>
  );
}
