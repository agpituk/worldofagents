"use client";

// Friendly hero URL: /h/<hero-name> resolves to the canonical /heroes/<id>
// page. Server-side lookup keeps the URL stable even if a hero is renamed
// (today they can't be — names are unique — but this future-proofs the share
// link).

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { use } from "react";
import { api } from "@/lib/api";

export default function HeroByNamePage({
  params,
}: {
  params: Promise<{ name: string }>;
}) {
  const { name } = use(params);
  const router = useRouter();
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    api
      .getHeroByName(decodeURIComponent(name))
      .then((h) => {
        if (cancelled) return;
        // Dead heroes get the monument route; alive heroes get the live page.
        if (h.status === "dead") {
          router.replace(`/heroes/${h.id}/death`);
        } else {
          router.replace(`/heroes/${h.id}`);
        }
      })
      .catch((e) => {
        if (!cancelled) setError(e?.message ?? "not found");
      });
    return () => { cancelled = true; };
  }, [name, router]);

  if (error) {
    return (
      <div className="border border-rose-800 bg-rose-950/40 px-4 py-3 text-sm">
        No hero named <code>{decodeURIComponent(name)}</code>.
      </div>
    );
  }
  return <div className="text-fg-muted text-sm">resolving…</div>;
}
