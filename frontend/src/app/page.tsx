"use client";

import { useEffect, useState } from "react";
import { api, CurrentEvents, Discovery, Hero, Highlight, Longevity, SkillLeaderboards, Zone } from "@/lib/api";
import HomeHero from "./components/home/HomeHero";
import EventBanners from "./components/home/EventBanners";
import MomentsAndDiscoveries from "./components/home/MomentsAndDiscoveries";
import SkillChampions from "./components/home/SkillChampions";
import LongevityBoards from "./components/home/LongevityBoards";
import ZonesGrid from "./components/home/ZonesGrid";
import HeroesGrid from "./components/home/HeroesGrid";

export default function WorldPage() {
  const [zones, setZones] = useState<Zone[]>([]);
  const [heroes, setHeroes] = useState<Hero[]>([]);
  const [longevity, setLongevity] = useState<Longevity | null>(null);
  const [events, setEvents] = useState<CurrentEvents | null>(null);
  const [highlights, setHighlights] = useState<Highlight[]>([]);
  const [discoveries, setDiscoveries] = useState<Discovery[]>([]);
  const [skillBoards, setSkillBoards] = useState<SkillLeaderboards | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let live = true;
    async function load() {
      try {
        const [zs, hs, lg, ev, hl, ds, sb] = await Promise.all([
          api.listZones(),
          api.listHeroes(),
          api.longevity(8),
          api.currentEvents(),
          api.listHighlights(8),
          api.listDiscoveries(),
          api.skillLeaderboards(3),
        ]);
        if (!live) return;
        setZones(zs);
        setHeroes(hs);
        setLongevity(lg);
        setEvents(ev);
        setHighlights(hl);
        setDiscoveries(ds);
        setSkillBoards(sb);
      } catch (e: any) {
        if (live) setError(e?.message ?? "fetch failed");
      }
    }
    load();
    const t = setInterval(load, 5000);
    return () => { live = false; clearInterval(t); };
  }, []);

  if (error) {
    return (
      <div className="border border-rose-700 bg-rose-950/40 px-4 py-3 text-sm">
        World API unreachable: <code>{error}</code>
        <div className="mt-2 text-fg-muted text-xs">
          Make sure the stack is up: <code>make dev</code>.
        </div>
      </div>
    );
  }

  const heroesByZone = new Map<string, Hero[]>();
  for (const h of heroes) {
    if (!heroesByZone.has(h.zone)) heroesByZone.set(h.zone, []);
    heroesByZone.get(h.zone)!.push(h);
  }

  return (
    <div className="space-y-8">
      <HomeHero />
      <EventBanners events={events} />
      <MomentsAndDiscoveries highlights={highlights} discoveries={discoveries} />
      <SkillChampions skillBoards={skillBoards} />
      <LongevityBoards longevity={longevity} />
      <ZonesGrid zones={zones} heroes={heroes} heroesByZone={heroesByZone} />
      <HeroesGrid heroes={heroes} />
    </div>
  );
}
