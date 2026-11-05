import { http } from '@/lib/http';
import type {
  AnswerSubmitted,
  ApplyRequest,
  ApplyResult,
  IntegrationAnalysis,
  IntegrationAnalysisSummary,
  CurrentQuestion,
  Evaluation,
  GitHubSource,
  Interview,
  InterviewCreate,
  InterviewReport,
  InterviewSummary,
  Job,
  JobAnalysis,
  JobCreate,
  JobSummary,
  Match,
  MatchRequest,
  MatchSummary,
  PortfolioSource,
  Profile,
  ProfileInput,
  Question,
  Resume,
  ResumeAnalysis,
  TokenPair,
  User,
} from './types';

const data = <T>(response: { data: T }): T => response.data;

export const authApi = {
  register: (body: { email: string; password: string; full_name: string }) =>
    http.post<{ message: string }>('/auth/register', body).then(data),
  login: (body: { email: string; password: string }) =>
    http.post<TokenPair>('/auth/login', body).then(data),
  logout: (refresh_token: string) =>
    http.post('/auth/logout', { refresh_token }).then(() => undefined),
  me: () => http.get<User>('/auth/me').then(data),
};

export const profileApi = {
  get: () => http.get<Profile>('/profile').then(data),
  update: (body: ProfileInput) => http.put<Profile>('/profile', body).then(data),
};

export const resumeApi = {
  list: () => http.get<Resume[]>('/resumes').then(data),
  upload: (file: File) => {
    const form = new FormData();
    form.append('file', file);
    return http.post<Resume>('/resumes', form).then(data);
  },
  remove: (id: string) => http.delete(`/resumes/${id}`).then(() => undefined),
  analyze: (id: string, allow_external_ai: boolean) =>
    http.post<ResumeAnalysis>(`/resumes/${id}/analyze`, { allow_external_ai }).then(data),
  analysis: (id: string) => http.get<ResumeAnalysis>(`/resumes/${id}/analysis`).then(data),
  apply: (id: string, body: ApplyRequest) =>
    http.post<ApplyResult>(`/resumes/${id}/apply-to-profile`, body).then(data),
};

export const integrationApi = {
  github: () => http.get<GitHubSource>('/integrations/github').then(data),
  connectGithub: (username: string) =>
    http.post<GitHubSource>('/integrations/github', { username }).then(data),
  disconnectGithub: () => http.delete('/integrations/github').then(() => undefined),
  portfolio: () => http.get<PortfolioSource>('/integrations/portfolio').then(data),
  connectPortfolio: (url: string) =>
    http.post<PortfolioSource>('/integrations/portfolio', { url }).then(data),
  disconnectPortfolio: () => http.delete('/integrations/portfolio').then(() => undefined),
  analyses: () => http.get<IntegrationAnalysisSummary[]>('/integrations/analysis').then(data),
  analysis: (id: string) =>
    http.get<IntegrationAnalysis>(`/integrations/analysis/${id}`).then(data),
  analyze: (body: { resume_id?: string; allow_external_ai: boolean }) =>
    http.post<IntegrationAnalysis>('/integrations/analysis', body).then(data),
  removeAnalysis: (id: string) => http.delete(`/integrations/analysis/${id}`).then(() => undefined),
  applyAnalysis: (id: string, body: ApplyRequest) =>
    http.post<ApplyResult>(`/integrations/analysis/${id}/apply-to-profile`, body).then(data),
};

export const jobApi = {
  list: () => http.get<JobSummary[]>('/jobs').then(data),
  get: (id: string) => http.get<Job>(`/jobs/${id}`).then(data),
  create: (body: JobCreate) => http.post<Job>('/jobs', body).then(data),
  update: (id: string, body: Partial<JobCreate>) => http.put<Job>(`/jobs/${id}`, body).then(data),
  remove: (id: string) => http.delete(`/jobs/${id}`).then(() => undefined),
  analysis: (id: string) => http.get<JobAnalysis>(`/jobs/${id}/analysis`).then(data),
  analyze: (id: string, body: { use_ai: boolean; allow_external_ai: boolean }) =>
    http.post<JobAnalysis>(`/jobs/${id}/analyze`, body).then(data),
  match: (id: string, body: MatchRequest) => http.post<Match>(`/jobs/${id}/match`, body).then(data),
  matches: (id: string) => http.get<MatchSummary[]>(`/jobs/${id}/matches`).then(data),
  getMatch: (id: string, matchId: string) =>
    http.get<Match>(`/jobs/${id}/matches/${matchId}`).then(data),
};

export const interviewApi = {
  list: () => http.get<InterviewSummary[]>('/interviews').then(data),
  get: (id: string) => http.get<Interview>(`/interviews/${id}`).then(data),
  create: (body: InterviewCreate) => http.post<Interview>('/interviews', body).then(data),
  start: (id: string) => http.post<Interview>(`/interviews/${id}/start`).then(data),
  cancel: (id: string) => http.post<Interview>(`/interviews/${id}/cancel`).then(data),
  complete: (id: string) => http.post<InterviewReport>(`/interviews/${id}/complete`).then(data),
  current: (id: string) =>
    http.get<CurrentQuestion>(`/interviews/${id}/current-question`).then(data),
  questions: (id: string) => http.get<Question[]>(`/interviews/${id}/questions`).then(data),
  answer: (id: string, body: { question_id: string; text?: string; skip?: boolean }) =>
    http.post<AnswerSubmitted>(`/interviews/${id}/answers`, body).then(data),
  evaluations: (id: string) => http.get<Evaluation[]>(`/interviews/${id}/evaluations`).then(data),
  report: (id: string) => http.get<InterviewReport>(`/interviews/${id}/report`).then(data),
};
