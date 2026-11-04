import {
  Bar,
  BarChart,
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';

export interface ScorePoint {
  label: string;
  score: number;
}

/** A visually hidden table gives screen-reader users (and tests) the chart's exact data. */
function DataTable({ caption, rows }: { caption: string; rows: ScorePoint[] }) {
  return (
    <table className="sr-only">
      <caption>{caption}</caption>
      <thead>
        <tr>
          <th>Item</th>
          <th>Score</th>
        </tr>
      </thead>
      <tbody>
        {rows.map((row) => (
          <tr key={row.label}>
            <td>{row.label}</td>
            <td>{row.score}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

export function ScoreTrendChart({ points, caption }: { points: ScorePoint[]; caption: string }) {
  return (
    <figure aria-label={caption}>
      <div className="h-56 w-full" aria-hidden>
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={points} margin={{ top: 8, right: 16, bottom: 0, left: -16 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
            <XAxis dataKey="label" tick={{ fontSize: 12 }} />
            <YAxis domain={[0, 100]} tick={{ fontSize: 12 }} />
            <Tooltip />
            <Line type="monotone" dataKey="score" stroke="#4f46e5" strokeWidth={2} dot />
          </LineChart>
        </ResponsiveContainer>
      </div>
      <DataTable caption={caption} rows={points} />
    </figure>
  );
}

export function ScoreBars({
  points,
  caption,
  max = 10,
}: {
  points: ScorePoint[];
  caption: string;
  max?: number;
}) {
  return (
    <figure aria-label={caption}>
      <div className="h-56 w-full" aria-hidden>
        <ResponsiveContainer width="100%" height="100%">
          <BarChart data={points} margin={{ top: 8, right: 16, bottom: 0, left: -16 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
            <XAxis dataKey="label" tick={{ fontSize: 12 }} />
            <YAxis domain={[0, max]} tick={{ fontSize: 12 }} />
            <Tooltip />
            <Bar dataKey="score" fill="#6366f1" radius={[4, 4, 0, 0]} />
          </BarChart>
        </ResponsiveContainer>
      </div>
      <DataTable caption={caption} rows={points} />
    </figure>
  );
}
