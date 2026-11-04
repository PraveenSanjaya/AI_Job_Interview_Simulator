import { z } from 'zod';
import type { Profile, ProfileInput } from '@/api/types';

/** Form values are plain strings; they are converted to and from the API shape below. */
const optionalDate = z.string().regex(/^(\d{4}-\d{2}-\d{2})?$/, 'Use the format YYYY-MM-DD');
const optionalUrl = z
  .string()
  .max(500, 'Use at most 500 characters')
  .refine((v) => v === '' || /^https?:\/\/\S+$/i.test(v), 'Enter a full http(s) address');
const text = (max: number) => z.string().max(max, `Use at most ${max} characters`);
const required = (max: number, message: string) =>
  z.string().trim().min(1, message).max(max, `Use at most ${max} characters`);

const education = z
  .object({
    institution: required(200, 'Enter the institution'),
    degree: required(200, 'Enter the degree'),
    field_of_study: text(200),
    start_date: optionalDate,
    end_date: optionalDate,
    description: text(5000),
  })
  .refine((v) => !v.start_date || !v.end_date || v.end_date >= v.start_date, {
    path: ['end_date'],
    message: 'The end date cannot be before the start date',
  });

const work = z
  .object({
    company: required(200, 'Enter the company'),
    title: required(200, 'Enter the job title'),
    start_date: optionalDate,
    end_date: optionalDate,
    is_current: z.boolean(),
    description: text(5000),
  })
  .refine((v) => !v.start_date || !v.end_date || v.end_date >= v.start_date, {
    path: ['end_date'],
    message: 'The end date cannot be before the start date',
  })
  .refine((v) => !(v.is_current && v.end_date), {
    path: ['end_date'],
    message: 'A current role has no end date',
  });

export const profileSchema = z
  .object({
    full_name: required(200, 'Enter your name'),
    headline: text(200),
    career_objective: text(5000),
    experience_level: z.enum(['', 'entry', 'junior', 'mid', 'senior', 'lead']),
    preferred_difficulty: z.enum(['', 'beginner', 'intermediate', 'advanced', 'expert']),
    preferred_roles: text(2000),
    skills: z
      .array(
        z.object({
          name: required(100, 'Enter the skill'),
          category: z.enum(['technical', 'soft']),
          proficiency: z.enum(['', 'beginner', 'intermediate', 'advanced', 'expert']),
        }),
      )
      .max(100, 'At most 100 skills'),
    education: z.array(education).max(20, 'At most 20 entries'),
    work_experience: z.array(work).max(30, 'At most 30 entries'),
    projects: z
      .array(
        z.object({
          name: required(200, 'Enter the project name'),
          description: text(5000),
          technologies: text(1500),
          url: optionalUrl,
        }),
      )
      .max(30, 'At most 30 entries'),
    certifications: z
      .array(
        z.object({
          name: required(200, 'Enter the certification'),
          issuer: text(200),
          issued_date: optionalDate,
          credential_url: optionalUrl,
        }),
      )
      .max(30, 'At most 30 entries'),
  })
  .superRefine((v, ctx) => {
    const roles = splitList(v.preferred_roles);
    if (roles.length > 20) {
      ctx.addIssue({ code: 'custom', path: ['preferred_roles'], message: 'At most 20 roles' });
    }
    if (new Set(roles.map((r) => r.toLowerCase())).size !== roles.length) {
      ctx.addIssue({
        code: 'custom',
        path: ['preferred_roles'],
        message: 'Remove duplicate roles',
      });
    }
    const seen = new Set<string>();
    v.skills.forEach((skill, index) => {
      const key = `${skill.category}:${skill.name.trim().toLowerCase()}`;
      if (seen.has(key)) {
        ctx.addIssue({
          code: 'custom',
          path: ['skills', index, 'name'],
          message: 'This skill is already listed',
        });
      }
      seen.add(key);
    });
  });

export type ProfileFormValues = z.infer<typeof profileSchema>;

export function splitList(value: string): string[] {
  return value
    .split(',')
    .map((part) => part.trim())
    .filter(Boolean);
}

const nullIfEmpty = (value: string): string | null => (value.trim() === '' ? null : value.trim());

export function toFormValues(profile: Profile): ProfileFormValues {
  return {
    full_name: profile.full_name,
    headline: profile.headline ?? '',
    career_objective: profile.career_objective ?? '',
    experience_level: profile.experience_level ?? '',
    preferred_difficulty: profile.preferred_difficulty ?? '',
    preferred_roles: profile.preferred_roles.join(', '),
    skills: profile.skills.map((s) => ({
      name: s.name,
      category: s.category,
      proficiency: s.proficiency ?? '',
    })),
    education: profile.education.map((e) => ({
      institution: e.institution,
      degree: e.degree,
      field_of_study: e.field_of_study ?? '',
      start_date: e.start_date ?? '',
      end_date: e.end_date ?? '',
      description: e.description ?? '',
    })),
    work_experience: profile.work_experience.map((w) => ({
      company: w.company,
      title: w.title,
      start_date: w.start_date ?? '',
      end_date: w.end_date ?? '',
      is_current: w.is_current,
      description: w.description ?? '',
    })),
    projects: profile.projects.map((p) => ({
      name: p.name,
      description: p.description ?? '',
      technologies: p.technologies.join(', '),
      url: p.url ?? '',
    })),
    certifications: profile.certifications.map((c) => ({
      name: c.name,
      issuer: c.issuer ?? '',
      issued_date: c.issued_date ?? '',
      credential_url: c.credential_url ?? '',
    })),
  };
}

/** The whole profile is replaced on save (PUT), so every section is always sent. */
export function toApiInput(values: ProfileFormValues): ProfileInput {
  return {
    full_name: values.full_name.trim(),
    headline: nullIfEmpty(values.headline),
    career_objective: nullIfEmpty(values.career_objective),
    experience_level: values.experience_level === '' ? null : values.experience_level,
    preferred_difficulty: values.preferred_difficulty === '' ? null : values.preferred_difficulty,
    preferred_roles: splitList(values.preferred_roles),
    skills: values.skills.map((s) => ({
      name: s.name.trim(),
      category: s.category,
      proficiency: s.proficiency === '' ? null : s.proficiency,
    })),
    education: values.education.map((e) => ({
      institution: e.institution.trim(),
      degree: e.degree.trim(),
      field_of_study: nullIfEmpty(e.field_of_study),
      start_date: nullIfEmpty(e.start_date),
      end_date: nullIfEmpty(e.end_date),
      description: nullIfEmpty(e.description),
    })),
    work_experience: values.work_experience.map((w) => ({
      company: w.company.trim(),
      title: w.title.trim(),
      start_date: nullIfEmpty(w.start_date),
      end_date: w.is_current ? null : nullIfEmpty(w.end_date),
      is_current: w.is_current,
      description: nullIfEmpty(w.description),
    })),
    projects: values.projects.map((p) => ({
      name: p.name.trim(),
      description: nullIfEmpty(p.description),
      technologies: splitList(p.technologies),
      url: nullIfEmpty(p.url),
    })),
    certifications: values.certifications.map((c) => ({
      name: c.name.trim(),
      issuer: nullIfEmpty(c.issuer),
      issued_date: nullIfEmpty(c.issued_date),
      credential_url: nullIfEmpty(c.credential_url),
    })),
  };
}

/** Which parts of the profile a candidate has filled in (used for the dashboard checklist). */
export function profileCompleteness(profile: Profile): {
  done: number;
  total: number;
  missing: string[];
} {
  const checks: [string, boolean][] = [
    ['A headline', Boolean(profile.headline)],
    ['An experience level', Boolean(profile.experience_level)],
    ['Preferred roles', profile.preferred_roles.length > 0],
    ['Skills', profile.skills.length > 0],
    ['Work experience', profile.work_experience.length > 0],
    ['Education', profile.education.length > 0],
    ['Projects', profile.projects.length > 0],
  ];
  const missing = checks.filter(([, ok]) => !ok).map(([label]) => label);
  return { done: checks.length - missing.length, total: checks.length, missing };
}
