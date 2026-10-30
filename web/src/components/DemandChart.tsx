import { useQuery } from "@tanstack/react-query"; // tanstack for data fetch/cache
import { getDemand, type SearchOut } from "../api";

import { CartesianGrid, Line, LineChart, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";

// "2025-07-01" -> "Jul 2025" (noon again, to avoid the UTC date shift)
function formatMonth(month: string): string {
  return new Date(month + "T12:00").toLocaleDateString("en-CA", { month: "short", year: "numeric" });
}

type Props = { search: SearchOut };

export default function DemandChart({search}: Props) {

  const { data, isLoading, isError } = useQuery({
    queryKey: ["demand", search.key],
    queryFn: () => getDemand(search.role, search.region),
  });

  if (isLoading) return <p>Demand loading…</p>;
  if (isError || !data) return <p>Couldn't reach the API. Try refreshing.</p>;
  if (data.points.length === 0) return <p>No monthly history for this search</p>;
  const breaks = data.points.filter((p) => p.note !== null);
  return (
    <section>
        <h2>Demand over time</h2>
        <p>New Job Bank postings per month</p>
        <ResponsiveContainer width="100%" height={300}>
            <LineChart data={data.points} margin={{ left: 8, right: 24, top: 16 }}>
                <CartesianGrid strokeDasharray="3 3" vertical={false} />
                <XAxis dataKey="month" tickFormatter={formatMonth} minTickGap={24} />
                <YAxis allowDecimals={false} />
                <Tooltip labelFormatter={(m) => formatMonth(String(m))} />
                <Line type="monotone" dataKey="new_postings" name="New postings" stroke="#4f6bed" dot={false} />
                {/* Reference lines must be inside the chart; drawn last so they sit on top */}
                {breaks.map((p) => (
                <ReferenceLine key={p.month} x={p.month} stroke="#c0392b" strokeDasharray="4 4"
                                label={{ value: "Data change", position: "top", fontSize: 12 }} />
                ))}
            </LineChart>
        </ResponsiveContainer>
        {breaks.map((p) => (
        <p key={p.month}><small>{formatMonth(p.month)}: {p.note}</small></p>
        ))}
    </section>
  );
}
