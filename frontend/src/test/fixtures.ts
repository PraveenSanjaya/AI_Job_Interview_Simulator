import type {
  Job,
  JobAnalysis,
  Match,
  MatchSummary,
  Profile,
  Resume,
  ResumeAnalysis,
} from '@/api/types';

export const PROFILE: Profile = {
  email: 'ada@example.com',
  full_name: 'Ada Lovelace',
  headline: 'Junior backend developer',
  career_objective: null,
  experience_level: 'junior',
  preferred_difficulty: null,
  preferred_roles: ['Backend Developer'],
  education: [
    {
      institution: 'SLIIT',
      degree: 'BSc',
      field_of_study: 'IT',
      start_date: '2022-02-01',
      end_date: '2026-01-31',
      description: null,
    },
  ],
  work_experience: [
    {
      company: 'Acme',
      title: 'Intern',
      start_date: '2025-06-01',
      end_date: null,
      is_current: true,
      description: 'Built APIs.',
    },
  ],
  skills: [
    { name: 'Python', category: 'technical', proficiency: 'advanced' },
    { name: 'Teamwork', category: 'soft', proficiency: null },
  ],
  projects: [
    { name: 'Shop API', description: 'Orders', technologies: ['FastAPI', 'PostgreSQL'], url: null },
  ],
  certifications: [],
  updated_at: '2026-01-01T00:00:00Z',
};

export const RESUME: Resume = {
  id: 'r1',
  display_name: 'cv.pdf',
  file_format: 'pdf',
  size_bytes: 20480,
  status: 'completed',
  failure_stage: null,
  error_code: null,
  error_message: null,
  page_count: 2,
  char_count: 3000,
  word_count: 500,
  has_analysis: true,
  created_at: '2026-02-01T00:00:00Z',
  extracted_at: '2026-02-01T00:00:01Z',
  analyzed_at: '2026-02-01T00:00:05Z',
};

export const ANALYSIS: ResumeAnalysis = {
  resume_id: 'r1',
  provider: 'fake',
  model: 'fake-model',
  consent_external_ai: false,
  input_truncated: false,
  created_at: '2026-02-01T00:00:05Z',
  result: {
    facts: {
      full_name: 'Jane Doe',
      email: 'jane@example.com',
      phone: null,
      location: null,
      links: [],
      summary_as_written: null,
      education: [{ institution: 'UoC', degree: 'BSc' }],
      work_experience: [{ company: 'Acme', title: 'Engineer' }],
      technical_skills: ['Python', 'FastAPI'],
      soft_skills: ['Teamwork'],
      tools_and_technologies: ['Docker'],
      projects: [{ name: 'Shop API' }],
      certifications: [],
    },
    assessment: {
      ai_summary: 'A backend engineer.',
      strengths: ['Python experience'],
      potential_skill_gaps: ['No cloud'],
    },
    missing_information: ['phone'],
    unverified_items_removed: 2,
  },
  profile_suggestion: {
    headline: 'Backend engineer',
    skills: [
      { name: 'Python', category: 'technical', proficiency: null },
      { name: 'FastAPI', category: 'technical', proficiency: null },
    ],
    work_experience: [
      {
        company: 'Acme',
        title: 'Engineer',
        start_date: null,
        end_date: null,
        is_current: true,
        description: null,
      },
    ],
  },
  suggestion_notes: ['An education entry without a degree was left out'],
};

export const JOB: Job = {
  id: 'j1',
  title: 'Backend Engineer',
  company: 'Acme Payments',
  description: 'Requirements: Python and PostgreSQL. Nice to have: AWS.',
  source_url: null,
  status: 'parsed',
  has_analysis: true,
  created_at: '2026-03-01T00:00:00Z',
  updated_at: '2026-03-01T00:00:00Z',
};

const skill = (name: string, importance: 'required' | 'preferred' | 'unspecified', extra = {}) => ({
  name,
  kind: 'language',
  importance,
  importance_stated: importance !== 'unspecified',
  source: 'text' as const,
  quote: null,
  context_only: false,
  alternatives: [] as string[],
  ...extra,
});

export const JOB_ANALYSIS: JobAnalysis = {
  job_id: 'j1',
  parser: 'deterministic',
  provider: null,
  consent_external_ai: false,
  created_at: '2026-03-01T00:00:01Z',
  result: {
    parsed: {
      technical_skills: [
        skill('Python', 'required', { alternatives: ['Java'] }),
        skill('PostgreSQL', 'required'),
        skill('AWS', 'preferred'),
        skill('Git', 'unspecified'),
        skill('Kafka', 'unspecified', { context_only: true }),
        skill('Prefect', 'preferred', { source: 'ai' }),
      ],
      soft_skills: [],
      certifications: [],
      responsibilities: [],
      education: [{ level: 'bachelor', field_of_study: null, importance: 'required' }],
      seniority: { level: 'senior', basis: 'stated' },
      warnings: [
        '1 skill(s) are mentioned without saying whether they are required or preferred: Git.',
      ],
      overall_min_years: 5,
      required_technical_skills: ['Python', 'PostgreSQL'],
      preferred_technical_skills: ['AWS'],
      company_context_skills: ['Kafka'],
    },
    unverified_items_removed: 0,
  },
};

export const MATCH_SUMMARY: MatchSummary = {
  id: 'm1',
  job_id: 'j1',
  created_at: '2026-03-02T10:00:00Z',
  overall_score: 77,
  score_status: 'scored',
  confidence: 'low',
};

const requirement = (
  name: string,
  status: 'supported' | 'weakly_supported' | 'not_found',
  extra = {},
) => ({
  name,
  importance: 'required' as const,
  status,
  credit: status === 'supported' ? 1 : status === 'weakly_supported' ? 0.5 : 0,
  independent_evidence: status === 'supported' ? 1 : 0,
  evidence:
    status === 'supported'
      ? [{ source: 'profile' as const, kind: 'project', ref: 'Shop API' }]
      : [],
  job_quote: 'Experience with ' + name,
  satisfied_via: null,
  unchecked_sources: [],
  note:
    status === 'not_found'
      ? 'No evidence of this was found in the data on record.'
      : 'Shown in your own material.',
  ...extra,
});

export const MATCH: Match = {
  id: 'm1',
  job_id: 'j1',
  created_at: '2026-03-02T10:00:00Z',
  overall_score: 77,
  confidence: 'low',
  consent_external_ai: false,
  ai_advice: null,
  report: {
    score: {
      score: 77,
      status: 'scored',
      confidence: 'low',
      formula: 'score = 100 x sum(...)',
      explanation: '77/100 = Required skills 43.8 + Preferred skills 0.0.',
      dimensions: [
        {
          key: 'required_skills',
          label: 'Required skills',
          weight: 0.4,
          applicable: true,
          value: 0.75,
          effective_weight: 0.6,
          points: 43.8,
          explanation: '1 of 2 required skills shown.',
        },
        {
          key: 'experience',
          label: 'Experience',
          weight: 0.15,
          applicable: false,
          value: null,
          effective_weight: 0,
          points: 0,
          explanation: 'No work history recorded.',
        },
      ],
    },
    required_skills: {
      label: 'Required skills',
      total: 2,
      supported: 1,
      weakly_supported: 0,
      not_found: 1,
      unknown: 0,
      coverage: 0.5,
      items: [
        requirement('Python', 'supported'),
        requirement('PostgreSQL', 'not_found', { unchecked_sources: ['github (not connected)'] }),
      ],
    },
    preferred_skills: {
      label: 'Preferred skills',
      total: 0,
      supported: 0,
      weakly_supported: 0,
      not_found: 0,
      unknown: 0,
      coverage: null,
      items: [],
    },
    technical_strengths: [
      {
        skill: 'Python',
        importance: 'required',
        independent_evidence: 1,
        evidence: [{ source: 'profile', kind: 'project', ref: 'Shop API' }],
      },
    ],
    experience: {
      status: 'unknown',
      required_years: 5,
      candidate_years: null,
      notes: ['No work experience is recorded.'],
    },
    education: { status: 'not_required', required_level: null, candidate_level: null, notes: [] },
    project_relevance: {
      value: 1,
      projects: [{ name: 'Shop API', matched_technologies: ['Python'] }],
      notes: [],
    },
    missing_requirements: ['PostgreSQL'],
    weakly_supported_requirements: [],
    unverifiable_requirements: [],
    evidence_by_source: { profile: [], resume: [], github: [], portfolio: [] },
    sources: {
      profile: true,
      resume: false,
      github: false,
      portfolio: false,
      not_available: { github: 'not connected' },
    },
    improvement_areas: [
      {
        topic: 'PostgreSQL',
        priority: 'high',
        reason: 'The job requires PostgreSQL.',
        suggestion: 'Build a small project with it.',
      },
    ],
    preparation_topics: [
      { topic: 'Learn the basics of PostgreSQL', reason: 'Be honest about your level.' },
    ],
    caveats: ['Everything is checked against what you have recorded.'],
    disclaimer: 'This is a rule-based estimate. No score guarantees an interview or an offer.',
  },
};
