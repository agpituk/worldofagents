"use client";

type ValidationResult = { valid: boolean; issues: any[]; summary: any };

type Props = {
  manifest: string;
  validation: ValidationResult | null;
  validating: boolean;
  onValidate: () => void;
};

export default function ValidationPanel({ manifest, validation, validating, onValidate }: Props) {
  return (
    <>
      <div className="flex items-center gap-3 text-xs">
        <button
          onClick={onValidate}
          disabled={validating || manifest.trim().length === 0}
          className="border border-border bg-bg-card px-3 py-1 text-fg-muted hover:text-amber-dim hover:border-amber-dim disabled:opacity-50"
        >
          {validating ? "validating…" : "validate manifest"}
        </button>
        {validation && (
          <span className={validation.valid ? "text-emerald-400" : "text-rose-300"}>
            {validation.valid
              ? `✓ valid · ${validation.summary.spells_declared ?? 0} spells · ${validation.summary.reflexes_declared ?? 0} reflexes · ${validation.summary.tools_declared ?? 0} tools`
              : `${validation.issues.length} issue${validation.issues.length === 1 ? "" : "s"}`}
          </span>
        )}
      </div>

      {validation && validation.issues.length > 0 && (
        <ul className="border border-border bg-bg-card divide-y divide-border text-xs">
          {validation.issues.map((iss: any, i: number) => (
            <li key={i} className="px-3 py-2">
              <span
                className={
                  iss.severity === "error"
                    ? "text-rose-300 mr-2"
                    : iss.severity === "warning"
                    ? "text-amber mr-2"
                    : "text-fg-muted mr-2"
                }
              >
                {iss.severity}
              </span>
              {iss.path && <code className="text-fg-muted mr-2">{iss.path}</code>}
              <span>{iss.message}</span>
            </li>
          ))}
        </ul>
      )}
    </>
  );
}
