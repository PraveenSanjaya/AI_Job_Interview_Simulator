import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { toApiError } from '@/lib/errors';
import { integrationApi, interviewApi, jobApi, profileApi, resumeApi } from './endpoints';

export const keys = {
  profile: ['profile'] as const,
  resumes: ['resumes'] as const,
  resumeAnalysis: (id: string) => ['resumes', id, 'analysis'] as const,
  github: ['integrations', 'github'] as const,
  portfolio: ['integrations', 'portfolio'] as const,
  analyses: ['integrations', 'analysis'] as const,
  analysisDetail: (id: string) => ['integrations', 'analysis', id] as const,
  jobs: ['jobs'] as const,
  job: (id: string) => ['jobs', id] as const,
  jobAnalysis: (id: string) => ['jobs', id, 'analysis'] as const,
  matches: (id: string) => ['jobs', id, 'matches'] as const,
  match: (id: string, matchId: string) => ['jobs', id, 'matches', matchId] as const,
  interviews: ['interviews'] as const,
  interview: (id: string) => ['interviews', id] as const,
  current: (id: string) => ['interviews', id, 'current'] as const,
  questions: (id: string) => ['interviews', id, 'questions'] as const,
  evaluations: (id: string) => ['interviews', id, 'evaluations'] as const,
  report: (id: string) => ['interviews', id, 'report'] as const,
};

/** A 404 for an optional resource (nothing connected yet) is an empty state, not an error. */
async function orNull<T>(request: () => Promise<T>): Promise<T | null> {
  try {
    return await request();
  } catch (error) {
    if (toApiError(error).status === 404) return null;
    throw error;
  }
}

// ----------------------------------------------------------------- queries
export const useProfile = () => useQuery({ queryKey: keys.profile, queryFn: profileApi.get });
export const useResumes = () => useQuery({ queryKey: keys.resumes, queryFn: resumeApi.list });
export const useResumeAnalysis = (id: string, enabled: boolean) =>
  useQuery({ queryKey: keys.resumeAnalysis(id), queryFn: () => resumeApi.analysis(id), enabled });
export const useGithub = () =>
  useQuery({ queryKey: keys.github, queryFn: () => orNull(integrationApi.github) });
export const usePortfolio = () =>
  useQuery({ queryKey: keys.portfolio, queryFn: () => orNull(integrationApi.portfolio) });
export const useIntegrationAnalyses = () =>
  useQuery({ queryKey: keys.analyses, queryFn: integrationApi.analyses });
export const useIntegrationAnalysis = (id: string | undefined) =>
  useQuery({
    queryKey: keys.analysisDetail(id ?? ''),
    queryFn: () => integrationApi.analysis(id as string),
    enabled: Boolean(id),
  });
export const useJobs = () => useQuery({ queryKey: keys.jobs, queryFn: jobApi.list });
export const useJob = (id: string) =>
  useQuery({ queryKey: keys.job(id), queryFn: () => jobApi.get(id) });
export const useJobAnalysis = (id: string, enabled = true) =>
  useQuery({
    queryKey: keys.jobAnalysis(id),
    queryFn: () => orNull(() => jobApi.analysis(id)),
    enabled,
  });
export const useMatches = (id: string) =>
  useQuery({ queryKey: keys.matches(id), queryFn: () => jobApi.matches(id) });
export const useMatch = (id: string, matchId: string | undefined) =>
  useQuery({
    queryKey: keys.match(id, matchId ?? ''),
    queryFn: () => jobApi.getMatch(id, matchId as string),
    enabled: Boolean(matchId),
  });
export const useInterviews = () =>
  useQuery({ queryKey: keys.interviews, queryFn: interviewApi.list });
export const useInterview = (id: string) =>
  useQuery({ queryKey: keys.interview(id), queryFn: () => interviewApi.get(id) });
export const useCurrentQuestion = (id: string, enabled: boolean) =>
  useQuery({ queryKey: keys.current(id), queryFn: () => interviewApi.current(id), enabled });
export const useQuestions = (id: string, enabled = true) =>
  useQuery({ queryKey: keys.questions(id), queryFn: () => interviewApi.questions(id), enabled });
export const useInterviewReport = (id: string, enabled = true) =>
  useQuery({ queryKey: keys.report(id), queryFn: () => interviewApi.report(id), enabled });

// --------------------------------------------------------------- mutations
export function useInvalidate() {
  const client = useQueryClient();
  return (...queryKeys: readonly (readonly unknown[])[]) =>
    Promise.all(queryKeys.map((queryKey) => client.invalidateQueries({ queryKey })));
}

export function useApiMutation<TVars, TData>(
  fn: (vars: TVars) => Promise<TData>,
  invalidate: readonly (readonly unknown[])[] = [],
) {
  const invalidateKeys = useInvalidate();
  return useMutation<TData, Error, TVars>({
    mutationFn: fn,
    onSuccess: () => invalidateKeys(...invalidate),
  });
}
