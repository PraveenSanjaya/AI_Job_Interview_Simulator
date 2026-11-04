import type { Profile, Resume, ResumeAnalysis } from '@/api/types';

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
