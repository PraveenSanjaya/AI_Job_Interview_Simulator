import type { Profile } from '@/api/types';

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
