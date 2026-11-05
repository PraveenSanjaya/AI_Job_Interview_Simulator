import { useState } from 'react';
import { keys, useApiMutation } from '@/api/queries';
import type { ApplyRequest, ApplyResult, ProfileSuggestion } from '@/api/types';
import { Alert, Button, Checkbox } from '@/components/ui';
import { describeError } from '@/lib/errors';

type ListSection = 'skills' | 'education' | 'work_experience' | 'projects' | 'certifications';
const SECTION_LABEL: Record<ListSection, string> = {
  skills: 'Skills',
  education: 'Education',
  work_experience: 'Work experience',
  projects: 'Projects',
  certifications: 'Certifications',
};

function itemLabel(section: ListSection, item: Record<string, unknown>): string {
  const s = (key: string) => (typeof item[key] === 'string' ? (item[key] as string) : '');
  switch (section) {
    case 'skills':
      return `${s('name')} (${s('category')})`;
    case 'education':
      return `${s('degree')} · ${s('institution')}`;
    case 'work_experience':
      return `${s('title')} at ${s('company')}`;
    default:
      return s('name');
  }
}

/** The suggestion is only a starting point: the candidate picks exactly what to apply. */
export function ApplyPanel({
  suggestion,
  notes,
  onApply,
  emptyMessage,
}: {
  suggestion: ProfileSuggestion;
  notes: string[];
  onApply: (body: ApplyRequest) => Promise<ApplyResult>;
  emptyMessage: string;
}) {
  const sections = (Object.keys(SECTION_LABEL) as ListSection[]).filter(
    (k) => (suggestion[k]?.length ?? 0) > 0,
  );
  const scalars = (['full_name', 'headline', 'career_objective'] as const).filter((k) =>
    Boolean(suggestion[k]),
  );

  const [picked, setPicked] = useState<Record<string, boolean>>({});
  const [replace, setReplace] = useState(false);
  const [overwrite, setOverwrite] = useState(false);
  const [result, setResult] = useState<ApplyResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const apply = useApiMutation(onApply, [keys.profile]);

  const isOn = (key: string) => picked[key] ?? false;
  const toggle = (key: string) => setPicked((p) => ({ ...p, [key]: !(p[key] ?? false) }));
  const anySelected = Object.values(picked).some(Boolean);

  async function submit() {
    setError(null);
    const body: ApplyRequest = {
      mode: replace ? 'replace' : 'merge',
      overwrite_existing: overwrite,
    };
    for (const key of scalars) if (isOn(key)) body[key] = suggestion[key];
    for (const section of sections) {
      const chosen = (suggestion[section] ?? []).filter((_, i) => isOn(`${section}:${i}`));
      if (chosen.length > 0) (body as Record<string, unknown>)[section] = chosen;
    }
    try {
      setResult(await apply.mutateAsync(body));
      setPicked({});
    } catch (e) {
      setError(describeError(e));
    }
  }

  return (
    <section aria-labelledby="apply-heading" className="rounded-lg border border-slate-200 p-4">
      <h3 id="apply-heading" className="text-sm font-semibold text-slate-900">
        Add to your profile
      </h3>
      <p className="mb-3 text-xs text-slate-500">
        Tick only what is correct. Nothing is applied until you press the button, and existing
        profile data is kept unless you choose otherwise.
      </p>
      {notes.length > 0 && (
        <Alert tone="info" className="mb-3">
          <ul className="list-inside list-disc">
            {notes.map((n) => (
              <li key={n}>{n}</li>
            ))}
          </ul>
        </Alert>
      )}
      {scalars.length === 0 && sections.length === 0 ? (
        <p className="text-sm text-slate-600">{emptyMessage}</p>
      ) : (
        <div className="space-y-4">
          {scalars.map((key) => (
            <Checkbox
              key={key}
              checked={isOn(key)}
              onChange={() => toggle(key)}
              label={`${key === 'full_name' ? 'Name' : key === 'headline' ? 'Headline' : 'Career objective'}: ${suggestion[key]}`}
            />
          ))}
          {sections.map((section) => (
            <fieldset key={section}>
              <legend className="mb-1 text-xs font-semibold uppercase tracking-wide text-slate-500">
                {SECTION_LABEL[section]}
              </legend>
              <div className="space-y-1.5">
                {(suggestion[section] ?? []).map((item, i) => (
                  <Checkbox
                    key={`${section}:${i}`}
                    checked={isOn(`${section}:${i}`)}
                    onChange={() => toggle(`${section}:${i}`)}
                    label={itemLabel(section, item as unknown as Record<string, unknown>)}
                  />
                ))}
              </div>
            </fieldset>
          ))}
          <div className="space-y-2 rounded-lg bg-slate-50 p-3">
            <Checkbox
              checked={replace}
              onChange={(e) => setReplace(e.target.checked)}
              label="Replace the matching profile sections instead of adding to them"
              hint="Off by default: new items are added and duplicates are skipped."
            />
            <Checkbox
              checked={overwrite}
              onChange={(e) => setOverwrite(e.target.checked)}
              label="Overwrite my name, headline or objective if they already differ"
            />
          </div>
          {error && <Alert tone="error">{error}</Alert>}
          <Button onClick={() => void submit()} disabled={!anySelected} loading={apply.isPending}>
            Apply selected to my profile
          </Button>
        </div>
      )}
      {result && (
        <Alert tone="success" title="Profile updated" className="mt-4">
          <p>
            Added:{' '}
            {Object.entries(result.applied)
              .map(([k, v]) => `${v} ${k.replace('_', ' ')}`)
              .join(', ') || 'nothing new'}
            .
          </p>
          {result.skipped.length > 0 && (
            <ul className="mt-1 list-inside list-disc">
              {result.skipped.map((s) => (
                <li key={`${s.field}${s.reason}`}>
                  {s.field}: {s.reason}
                </li>
              ))}
            </ul>
          )}
        </Alert>
      )}
    </section>
  );
}
