"use client";

import dynamic from "next/dynamic";
import yaml from "js-yaml";
import { Hero } from "@/lib/api";

const HeroBlocksRO = dynamic(() => import("@/components/HeroBlocksRO"), { ssr: false });

type Props = { hero: Hero };

export default function CraftViewer({ hero }: Props) {
  const manifest = (hero.manifest || {}) as Record<string, any>;
  const reflexes = manifest.reflexes || manifest.extras?.reflexes || [];
  const abilities = manifest.abilities || manifest.extras?.abilities || {};

  return (
    <>
      <details className="mt-8 group" open>
        <summary className="text-xs uppercase tracking-wider text-fg-muted cursor-pointer hover:text-amber">
          craft · reflexes ({Array.isArray(reflexes) ? reflexes.length : 0})
          {Object.keys(abilities).length > 0 && ` · abilities (${Object.keys(abilities).length})`}
        </summary>
        {Array.isArray(reflexes) && reflexes.length > 0 && (
          <div className="mt-3 space-y-2">
            {reflexes.map((r: any, i: number) => (
              <div key={i} className="border-l-2 border-amber-dim pl-3 text-xs">
                <div className="text-amber-dim font-mono">when {r.when}</div>
                <div className="text-fg-muted">→ {JSON.stringify(r.then)}</div>
              </div>
            ))}
          </div>
        )}
        {Object.keys(abilities).length > 0 && (
          <div className="mt-4">
            <div className="text-xs uppercase text-fg-muted mb-1">abilities</div>
            <ul className="text-xs">
              {Object.entries(abilities).map(([name, spec]: [string, any]) => (
                <li key={name} className="mb-1">
                  <span className="text-amber">{name}</span>
                  <span className="text-fg-muted ml-2">{spec.description ?? "—"}</span>
                </li>
              ))}
            </ul>
          </div>
        )}
      </details>

      {hero?.manifest && (
        <details className="mt-6 group">
          <summary className="text-xs uppercase tracking-wider text-fg-muted cursor-pointer hover:text-amber">
            blocks (visual)
          </summary>
          <div className="mt-3">
            <HeroBlocksRO yaml={yaml.dump({ hero: hero.manifest })} height={420} />
          </div>
        </details>
      )}
    </>
  );
}
