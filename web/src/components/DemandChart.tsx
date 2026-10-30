import { useQuery } from "@tanstack/react-query"; // tanstack for data fetch/cache
import { getDemand, type SearchOut } from "../api";

import { CartesianGrid, Line, LineChart, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { formatMonth } from "../format";
import { SERIES, axisLine, axisTick, gridStroke, tooltipStyle } from "../chartStyle";

type Props = { search: SearchOut };

export default function DemandChart({search}: Props) {

  const { data, isLoading, isError } = useQuery({
    queryKey: ["demand", search.key],
    queryFn: () => getDemand(search.role, search.region),
  });

  if (isLoading) return <p className="status">Demand loading…</p>;
  if (isError || !data) return <p className="status">Couldn't reach the API. Try refreshing.</p>;
  if (data.points.length === 0) return <p className="status">No monthly history for this search</p>;
  const breaks = data.points.filter((p) => p.note !== null);
  return (
    <section>
        <div className="card-head">
            <p className="eyebrow">Demand</p>
            <h2>New postings per month</h2>
            <p className="muted">Job Bank postings since {formatMonth(data.points[0].month)}</p>
        </div>
        <ResponsiveContainer width="100%" height={300}>
            <LineChart data={data.points} margin={{ left: 0, right: 16, top: 20 }}>
                <CartesianGrid stroke={gridStroke} vertical={false} />
                <XAxis dataKey="month" tickFormatter={formatMonth} minTickGap={32}
                       tick={axisTick} axisLine={axisLine} tickLine={false} />
                <YAxis allowDecimals={false} width={44} tick={axisTick} axisLine={false} tickLine={false} />
                <Tooltip labelFormatter={(m) => formatMonth(String(m))}
                         cursor={{ stroke: "var(--text-3)", strokeDasharray: "3 3" }} {...tooltipStyle} />
                <Line type="monotone" dataKey="new_postings" name="New postings" stroke={SERIES}
                      strokeWidth={2} dot={false}
                      activeDot={{ r: 5, stroke: "var(--surface)", strokeWidth: 2, fill: SERIES }} />
                {/* Reference lines must be inside the chart; drawn last so they sit on top */}
                {breaks.map((p) => (
                <ReferenceLine key={p.month} x={p.month} stroke="var(--warn)" strokeDasharray="4 4"
                                label={{ value: "Data change", position: "top", fontSize: 12, fill: "var(--warn)" }} />
                ))}
            </LineChart>
        </ResponsiveContainer>
        {breaks.map((p) => (
        <p key={p.month} className="break-note">
            <strong>⚠ {formatMonth(p.month)}</strong>
            <span>{p.note}</span>
        </p>
        ))}
    </section>
  );
}
