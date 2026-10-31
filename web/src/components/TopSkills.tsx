import { useQuery } from "@tanstack/react-query"; // tanstack for data fetch/cache
import { getSkills, type SearchOut } from "../api";
import { Bar, BarChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { formatDay } from "../format";
import { SERIES, axisLine, axisTick, barCursor, tooltipStyle } from "../chartStyle";


// Helper function for formatting the change in shares
function formatChange(change: number | null): string {
  if (change === null) return "";
  const pts = Math.round(change * 100);
  if (pts === 0) return "no change";
  return pts > 0 ? `▲ ${pts} pts` : `▼ ${Math.abs(pts)} pts`;
}

type Props = { search: SearchOut };


export default function TopSkills({search}: Props) {

    const { data, isLoading, isError } = useQuery({
    queryKey: ["skills", search.key],
    queryFn: () => getSkills(search.role, search.region, 15),
    });

      if (isLoading) return <p className="status">Loading skills…</p>;
      if (isError || !data) return <p className="status">Couldn't load skills, try refreshing.</p>;
      if (data.skills.length === 0) return <p className="status">No daily skill data for this search yet</p>;
      const changed = data.skills.filter((s) => s.change !== null);
      return (
        <section>
            <div className="card-head">
                <p className="eyebrow">Skills</p>
                <h2>Most requested skills</h2>
                <p className="muted">Share of active postings mentioning each skill, as of {formatDay(data.day!)}</p>
            </div>
            <ResponsiveContainer width="100%" height={data.skills.length * 30 + 36}>
                <BarChart data={data.skills} layout="vertical" margin={{ left: 0, right: 16 }}>
                <XAxis type="number" domain={[0, 1]} tickFormatter={(v) => `${Math.round(v * 100)}%`}
                       tick={axisTick} axisLine={axisLine} tickLine={false} />
                {/* interval={0}: show every skill; Recharts otherwise skips labels it thinks may overlap */}
                <YAxis type="category" dataKey="skill" width={150} interval={0}
                       tick={{ ...axisTick, fill: "var(--text-2)", fontSize: 13 }} axisLine={false} tickLine={false} />
                <Tooltip formatter={(v) => [`${Math.round(Number(v) * 100)}% of postings`, "Share"]}
                         cursor={barCursor} {...tooltipStyle} />
                {/* Thin bars with a rounded data end, square at the baseline */}
                <Bar dataKey="share" fill={SERIES} barSize={18} radius={[0, 4, 4, 0]} />
                </BarChart>
            </ResponsiveContainer>
            {changed.length > 0 && (
            <ul className="changes">
                {changed.map((s) => (
                <li key={s.skill}>
                    {s.skill}: <span className="num">{Math.round(s.share * 100)}%</span>{" "}
                    <span className={s.change! > 0 ? "up" : s.change! < 0 ? "down" : ""}>
                        {formatChange(s.change)}
                    </span>{" "}
                    <span className="muted">vs. a week earlier</span>
                </li>
                ))}
            </ul>
            )}
        </section>
      )
}
