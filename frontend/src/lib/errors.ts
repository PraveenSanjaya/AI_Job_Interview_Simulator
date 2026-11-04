import axios from 'axios';

/** A normalised error from the backend (or from the network). */
export class ApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly requestId?: string;
  readonly retryAfter?: number;
  readonly details: { location: string[]; message: string }[];

  constructor(init: {
    status: number;
    code: string;
    message: string;
    requestId?: string;
    retryAfter?: number;
    details?: { location: string[]; message: string }[];
  }) {
    super(init.message);
    this.name = 'ApiError';
    this.status = init.status;
    this.code = init.code;
    this.requestId = init.requestId;
    this.retryAfter = init.retryAfter;
    this.details = init.details ?? [];
  }
}

interface ErrorBody {
  error?: {
    code?: string;
    message?: string;
    request_id?: string;
    details?: { location?: unknown[]; message?: string }[];
  };
}

/** Convert anything thrown by axios into an ApiError. */
export function toApiError(error: unknown): ApiError {
  if (error instanceof ApiError) return error;
  if (axios.isAxiosError(error)) {
    if (!error.response) {
      return new ApiError({
        status: 0,
        code: 'network_error',
        message: 'Cannot reach the server. Check your connection and try again.',
      });
    }
    const body = error.response.data as ErrorBody | undefined;
    const retry = Number(error.response.headers['retry-after']);
    return new ApiError({
      status: error.response.status,
      code: body?.error?.code ?? 'http_error',
      message: body?.error?.message ?? `The server answered with status ${error.response.status}.`,
      requestId: body?.error?.request_id,
      retryAfter: Number.isFinite(retry) ? retry : undefined,
      details: (body?.error?.details ?? []).map((d) => ({
        location: (d.location ?? []).map(String),
        message: d.message ?? '',
      })),
    });
  }
  return new ApiError({ status: 0, code: 'unknown_error', message: 'Something went wrong.' });
}

const FRIENDLY: Record<string, string> = {
  invalid_credentials: 'The email or password is incorrect.',
  rate_limited: 'Too many attempts. Please wait a moment and try again.',
  ai_unavailable: 'AI features are not available on this server right now.',
  ai_consent_required:
    'This AI service is external. Tick the consent box to allow your data to be sent to it.',
  ai_timeout: 'The AI service took too long to answer. Please try again.',
  ai_rate_limited: 'The AI service is busy. Please try again shortly.',
  invalid_ai_response: 'The AI service returned an unusable answer. Please try again.',
  job_platform_not_supported:
    'That site does not allow automated access. Paste the job description text instead.',
  concurrent_submission: 'Another answer was submitted at the same moment. Reload and try again.',
  not_current_question: 'That question is no longer the current one. Reload the interview.',
  network_error: 'Cannot reach the server. Check your connection and try again.',
};

/** A message safe and useful to show to a person. */
export function describeError(error: unknown): string {
  const e = toApiError(error);
  if (e.status === 429 && e.retryAfter) {
    return `Too many requests. Try again in ${e.retryAfter} seconds.`;
  }
  if (e.status === 422 && e.details.length > 0) {
    const first = e.details[0];
    const field = first?.location.filter((p) => p !== 'body').join('.');
    return field ? `${field}: ${first?.message}` : (first?.message ?? e.message);
  }
  return FRIENDLY[e.code] ?? e.message;
}
