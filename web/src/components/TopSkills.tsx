import { useQuery } from "@tanstack/react-query"; // tanstack for data fetch/cache
import { getSkills, type SearchOut } from "../api";
import { Bar, BarChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";


// Helper function for date formatting from strings
function formatDay(day: string): string {
  return new Date(day + "T12:00").toLocaleDateString("en-CA", {
    month: "short", day: "numeric", year: "numeric",
  });
}


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

      if (isLoading) return <p>Loading skills</p>;
      if (isError || !data) return <p>Couldn't load skills, try refreshing.</p>;
      if (data.skills.length == 0) return <p>No daily skill data for this search yet</p>;
      const changed = data.skills.filter((s) => s.change !== null);
      return (
        <section>
            <h2>Top Skills</h2>
            <p>Share of active postings mentioning each skill as of {formatDay(data.day!)}</p>
            <ResponsiveContainer width="100%" height={data.skills.length * 32 + 40}>
                <BarChart data={data.skills} layout="vertical" margin={{ left: 24, right: 24 }}>
                <XAxis type="number" domain={[0, 1]} tickFormatter={(v) => `${Math.round(v * 100)}%`} />
                {/* interval={0}: show every skill; Recharts otherwise skips labels it thinks may overlap */}
                <YAxis type="category" dataKey="skill" width={170} interval={0} tick={{ fontSize: 13 }} />
                <Tooltip formatter={(v) => `${Math.round(Number(v) * 100)}%`} />
                <Bar dataKey="share" fill="#4f6bed" />
                </BarChart>
            </ResponsiveContainer>
            {changed.length > 0 && (
            <ul>
                {changed.map((s) => (
                <li key={s.skill}>
                    {s.skill}: {Math.round(s.share * 100)}% ({formatChange(s.change)} vs. a week earlier)
                </li>
                ))}
            </ul>
            )}
        </section>
      )
}