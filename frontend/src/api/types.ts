/** Shapes of the backend API (see docs/API_DOCUMENTATION.md). Dates are ISO strings. */

// ------------------------------------------------------------------ auth
/** Sign-in and refresh response. The refresh token is an HttpOnly cookie, never in the body. */
export interface AccessToken {
  access_token: string;
  token_type: string;
  expires_in: number;
}
export interface User {
  id: string;
  email: string;
  role: 'user' | 'admin';
  is_active: boolean;
  created_at: string;
}

// --------------------------------------------------------------- profile
export type ExperienceLevel = 'entry' | 'junior' | 'mid' | 'senior' | 'lead';
export type SkillCategory = 'technical' | 'soft';
export type Proficiency = 'beginner' | 'intermediate' | 'advanced' | 'expert';

export interface Education {
  institution: string;
  degree: string;
  field_of_study: string | null;
  start_date: string | null;
  end_date: string | null;
  description: string | null;
}
export interface WorkExperience {
  company: string;
  title: string;
  start_date: string | null;
  end_date: string | null;
  is_current: boolean;
  description: string | null;
}
export interface Skill {
  name: string;
  category: SkillCategory;
  proficiency: Proficiency | null;
}
export interface Project {
  name: string;
  description: string | null;
  technologies: string[];
  url: string | null;
}
export interface Certification {
  name: string;
  issuer: string | null;
  issued_date: string | null;
  credential_url: string | null;
}
/** What PUT /profile accepts, and what GET returns (plus ids and email). */
export interface ProfileInput {
  full_name: string;
  headline: string | null;
  career_objective: string | null;
  experience_level: ExperienceLevel | null;
  preferred_difficulty: Proficiency | null;
  preferred_roles: string[];
  education: Education[];
  work_experience: WorkExperience[];
  skills: Skill[];
  projects: Project[];
  certifications: Certification[];
}
export interface Profile extends ProfileInput {
  email: string;
  updated_at: string;
}

// --------------------------------------------------------------- resumes
export type ResumeStatus =
  'uploaded' | 'extracting' | 'extracted' | 'analyzing' | 'completed' | 'failed';
export interface Resume {
  id: string;
  display_name: string;
  file_format: string;
  size_bytes: number;
  status: ResumeStatus;
  failure_stage: string | null;
  error_code: string | null;
  error_message: string | null;
  page_count: number | null;
  char_count: number | null;
  word_count: number | null;
  has_analysis: boolean;
  created_at: string;
  extracted_at: string | null;
  analyzed_at: string | null;
}
export interface ExtractedFacts {
  full_name: string | null;
  email: string | null;
  phone: string | null;
  location: string | null;
  links: string[];
  summary_as_written: string | null;
  education: Partial<Education>[];
  work_experience: Partial<WorkExperience>[];
  technical_skills: string[];
  soft_skills: string[];
  tools_and_technologies: string[];
  projects: Partial<Project>[];
  certifications: Partial<Certification>[];
}
/** Same shape as the apply-to-profile request: every field optional. */
export interface ProfileSuggestion {
  full_name?: string | null;
  headline?: string | null;
  career_objective?: string | null;
  education?: Education[];
  work_experience?: WorkExperience[];
  skills?: Skill[];
  projects?: Project[];
  certifications?: Certification[];
}
export interface ResumeAnalysis {
  resume_id: string;
  provider: string;
  model: string;
  consent_external_ai: boolean;
  input_truncated: boolean;
  created_at: string;
  result: {
    facts: ExtractedFacts;
    assessment: { ai_summary: string | null; strengths: string[]; potential_skill_gaps: string[] };
    missing_information: string[];
    unverified_items_removed: number;
  };
  profile_suggestion: ProfileSuggestion;
  suggestion_notes: string[];
}
export interface ApplyRequest extends ProfileSuggestion {
  mode?: 'merge' | 'replace';
  overwrite_existing?: boolean;
}
export interface ApplyResult {
  applied: Record<string, number>;
  skipped: { field: string; reason: string }[];
  profile: Profile;
}

// ---------------------------------------------------------- integrations
export interface GitHubSnapshot {
  login: string;
  profile_url: string;
  bio: string | null;
  followers: number;
  public_repos_total: number;
  repos_listed: number;
  repos_truncated: boolean;
  repositories: {
    name: string;
    url: string;
    description: string | null;
    primary_language: string | null;
    topics: string[];
    stars: number;
    is_fork: boolean;
    is_archived: boolean;
    pushed_at: string | null;
  }[];
  language_distribution: Record<string, number>;
  total_stars_own_repos: number;
  activity: {
    own_repos_pushed_last_90_days: number;
    own_repos_pushed_last_365_days: number;
    most_recent_push: string | null;
  };
  notice: string;
}
export interface GitHubSource {
  source_ref: string;
  fetched_at: string;
  snapshot: GitHubSnapshot;
}
export interface PortfolioSnapshot {
  requested_url: string;
  host: string;
  pages: {
    url: string;
    title: string | null;
    description: string | null;
    text_truncated: boolean;
  }[];
  skipped_pages: { url: string; reason: string }[];
  notice: string;
}
export interface PortfolioSource {
  source_ref: string;
  fetched_at: string;
  snapshot: PortfolioSnapshot;
}

// ------------------------------------------------------------------ jobs
export type JobStatus = 'saved' | 'parsed' | 'failed';
export interface JobSummary {
  id: string;
  title: string;
  company: string | null;
  source_url: string | null;
  status: JobStatus;
  created_at: string;
  updated_at: string;
}
export interface Job extends JobSummary {
  description: string;
  has_analysis: boolean;
}
export interface JobCreate {
  title: string;
  company?: string | null;
  description?: string | null;
  source_url?: string | null;
}
export type Importance = 'required' | 'preferred' | 'unspecified';
export interface JobSkill {
  name: string;
  kind: string;
  importance: Importance;
  importance_stated: boolean;
  source: 'text' | 'ai';
  quote: string | null;
  context_only: boolean;
  alternatives: string[];
}
export interface JobAnalysis {
  job_id: string;
  parser: string;
  provider: string | null;
  consent_external_ai: boolean;
  created_at: string;
  result: {
    parsed: {
      technical_skills: JobSkill[];
      soft_skills: { name: string; importance: Importance }[];
      certifications: { name: string; importance: Importance }[];
      responsibilities: { text: string }[];
      education: { level: string; field_of_study: string | null; importance: Importance }[];
      seniority: { level: string | null; basis: string };
      warnings: string[];
      overall_min_years: number | null;
      required_technical_skills: string[];
      preferred_technical_skills: string[];
      company_context_skills: string[];
    };
    unverified_items_removed: number;
  };
}

export type SkillStatus = 'supported' | 'weakly_supported' | 'not_found' | 'unknown';
export interface EvidenceRef {
  source: 'profile' | 'resume' | 'github' | 'portfolio';
  kind: string;
  ref: string;
}
export interface RequirementMatch {
  name: string;
  importance: Importance;
  status: SkillStatus;
  credit: number;
  independent_evidence: number;
  evidence: EvidenceRef[];
  job_quote: string | null;
  satisfied_via: string | null;
  unchecked_sources: string[];
  note: string;
}
export interface SkillGroup {
  label: string;
  total: number;
  supported: number;
  weakly_supported: number;
  not_found: number;
  unknown: number;
  coverage: number | null;
  items: RequirementMatch[];
}
export interface MatchReport {
  score: {
    score: number | null;
    status: 'scored' | 'insufficient_evidence' | 'insufficient_job_detail';
    confidence: 'none' | 'low' | 'medium' | 'high';
    formula: string;
    explanation: string;
    dimensions: {
      key: string;
      label: string;
      weight: number;
      applicable: boolean;
      value: number | null;
      effective_weight: number;
      points: number;
      explanation: string;
    }[];
  };
  required_skills: SkillGroup;
  preferred_skills: SkillGroup;
  technical_strengths: {
    skill: string;
    importance: Importance;
    independent_evidence: number;
    evidence: EvidenceRef[];
  }[];
  experience: {
    status: string;
    required_years: number | null;
    candidate_years: number | null;
    notes: string[];
  };
  education: {
    status: string;
    required_level: string | null;
    candidate_level: string | null;
    notes: string[];
  };
  project_relevance: {
    value: number | null;
    projects: { name: string; matched_technologies: string[] }[];
    notes: string[];
  };
  missing_requirements: string[];
  weakly_supported_requirements: string[];
  unverifiable_requirements: string[];
  evidence_by_source: Record<string, EvidenceRef[]>;
  sources: {
    profile: boolean;
    resume: boolean;
    github: boolean;
    portfolio: boolean;
    not_available: Record<string, string>;
  };
  improvement_areas: {
    topic: string;
    priority: 'high' | 'medium' | 'low';
    reason: string;
    suggestion: string;
  }[];
  preparation_topics: { topic: string; reason: string }[];
  caveats: string[];
  disclaimer: string;
}
export interface MatchAdvice {
  summary: string | null;
  improvement_areas: { topic: string | null; why: string | null; suggested_actions: string[] }[];
  learning_topics: { topic: string | null; reason: string | null }[];
  project_ideas: { title: string | null; description: string | null }[];
  interview_preparation: { topic: string | null; reason: string | null }[];
  caveats: string[];
  notice: string;
}
export interface MatchSummary {
  id: string;
  job_id: string;
  created_at: string;
  overall_score: number | null;
  score_status: string;
  confidence: string;
}
export interface Match {
  id: string;
  job_id: string;
  created_at: string;
  overall_score: number | null;
  confidence: string;
  report: MatchReport;
  ai_advice: MatchAdvice | null;
  consent_external_ai: boolean;
}
export interface MatchRequest {
  include?: ('resume' | 'github' | 'portfolio')[];
  use_ai?: boolean;
  allow_external_ai?: boolean;
}

// ------------------------------------------------------------ interviews
export type InterviewType =
  'hr' | 'behavioral' | 'technical' | 'programming' | 'project' | 'system_design' | 'job_specific';
export type InterviewDifficulty = 'beginner' | 'intermediate' | 'advanced';
export type InterviewStatus =
  'created' | 'in_progress' | 'completed' | 'cancelled' | 'interrupted' | 'expired';
export interface InterviewCreate {
  interview_types: InterviewType[];
  difficulty: InterviewDifficulty;
  question_count: number;
  job_id?: string | null;
  max_followups?: number | null;
  use_ai: boolean;
  allow_external_ai: boolean;
}
export interface Progress {
  main_questions_total: number;
  main_questions_asked: number;
  answered: number;
  skipped: number;
  followups_asked: number;
  remaining_main_questions: number;
}
export interface Interview {
  id: string;
  status: InterviewStatus;
  interview_types: InterviewType[];
  difficulty: InterviewDifficulty;
  question_count: number;
  max_followups: number;
  job_id: string | null;
  job_title: string | null;
  use_ai: boolean;
  consent_external_ai: boolean;
  mode: 'ai' | 'question_bank' | null;
  ai_status: string | null;
  adaptive_followups: boolean | null;
  notes: string[];
  progress: Progress;
  created_at: string;
  started_at: string | null;
  completed_at: string | null;
}
export interface InterviewSummary {
  id: string;
  status: InterviewStatus;
  interview_types: InterviewType[];
  difficulty: InterviewDifficulty;
  job_title: string | null;
  mode: string | null;
  created_at: string;
  completed_at: string | null;
}
export interface Question {
  id: string;
  main_index: number;
  followup_index: number;
  is_followup: boolean;
  followup_kind: string | null;
  category: InterviewType;
  text: string;
  source: 'ai' | 'question_bank';
  skill_tags: string[];
  asked_at: string | null;
  answer?: { id: string; text: string | null; skipped: boolean; submitted_at: string } | null;
}
export interface CurrentQuestion {
  status: InterviewStatus;
  question: Question | null;
  all_questions_answered: boolean;
}
export interface DimensionResult {
  score: number | null;
  rationale: string | null;
}
export interface EvaluationResult {
  dimensions: Record<string, DimensionResult>;
  star: Record<string, { present: boolean | null; note: string | null }> | null;
  correct_points: string[];
  missing_or_incorrect_points: string[];
  strengths: string[];
  improvements: string[];
  summary: string | null;
  suspicious_instructions: boolean;
}
export interface Evaluation {
  id: string;
  answer_id: string;
  question_id: string;
  status: 'evaluated' | 'unavailable' | 'failed' | 'not_evaluated';
  reason: string | null;
  result: EvaluationResult | null;
}
export interface AnswerSubmitted {
  answer: { id: string; text: string | null; skipped: boolean };
  evaluation: Evaluation;
  follow_up_asked: boolean;
  followups_note: string | null;
  next_question: Question | null;
  all_questions_answered: boolean;
  progress: Progress;
}
export interface QuestionOutcome {
  question_id: string;
  main_index: number;
  category: string;
  text: string;
  status: string;
  score: number | null;
  summary: string | null;
}
export interface InterviewReportData {
  session_id: string;
  interview_types: string[];
  difficulty: string;
  mode: string | null;
  job_title: string | null;
  counts: {
    main_questions_planned: number;
    main_questions_asked: number;
    answered: number;
    skipped: number;
    followups_asked: number;
    followups_answered: number;
    evaluated_answers: number;
    not_evaluated_answers: number;
  };
  overall_score: number | null;
  score_status: 'scored' | 'not_evaluated';
  score_explanation: string;
  dimension_scores: Record<string, number | null>;
  group_scores: Record<string, { score: number | null; subjective: boolean; note: string }>;
  category_scores: Record<string, number | null>;
  star_summary: Record<string, string> | null;
  strong_answers: QuestionOutcome[];
  weak_answers: QuestionOutcome[];
  not_evaluated: QuestionOutcome[];
  knowledge_gaps: string[];
  study_topics: { topic: string | null; reason: string | null; source: string }[];
  practice_questions: { text: string; topic: string | null; source: string }[];
  ai_feedback: {
    summary: string | null;
    study_topics: { topic: string | null; reason: string | null }[];
    practice_questions: string[];
    notice: string;
  } | null;
  ai_feedback_status: string;
  calculation_notes: string[];
  disclaimer: string;
}
export interface InterviewReport {
  id: string;
  session_id: string;
  created_at: string;
  overall_score: number | null;
  report: InterviewReportData;
}

// ------------------------------------------------- integration analysis
export interface SourceReference {
  source: 'github' | 'portfolio' | 'resume';
  ref: string | null;
}
export interface IntegrationAnalysisSummary {
  id: string;
  created_at: string;
  provider: string;
  model: string;
  sources_used: string[];
}
export interface IntegrationAnalysis {
  id: string;
  created_at: string;
  provider: string;
  model: string;
  consent_external_ai: boolean;
  input_truncated: boolean;
  github_source_id: string | null;
  portfolio_source_id: string | null;
  resume_id: string | null;
  result: {
    facts: {
      sources_used: string[];
      github: {
        login: string;
        profile_url: string;
        own_repositories_considered: number;
        language_distribution: Record<string, number>;
        notable_repositories: {
          name: string;
          url: string;
          description: string | null;
          primary_language: string | null;
          stars: number;
        }[];
        own_repos_pushed_last_365_days: number;
        note: string;
      } | null;
      portfolio: { host: string; pages: { url: string; title: string | null }[] } | null;
      consistency: {
        cv_skills_with_public_evidence: { skill: string; found_in: SourceReference[] }[];
        cv_skills_without_public_evidence: string[];
        note: string;
      } | null;
    };
    assessment: {
      summary: string | null;
      strengths: string[];
      potential_skill_gaps: string[];
      project_assessments: {
        name: string | null;
        source: SourceReference;
        technologies_demonstrated: string[];
        what_it_shows: string | null;
        relevance: string | null;
        complexity: 'basic' | 'moderate' | 'advanced' | 'unclear';
        complexity_basis: string | null;
      }[];
      demonstrated_skills: { name: string | null; evidence: SourceReference[] }[];
      consistency_notes: string[];
      caveats: string[];
    };
    unverified_items_removed: number;
  };
  profile_suggestion: ProfileSuggestion | null;
  suggestion_notes: string[];
}
