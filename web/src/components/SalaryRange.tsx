import { useQuery } from "@tanstack/react-query";
import { getDemand, type SearchOut } from "../api";
import { formatMoney, formatMonth } from "../format";

// Below this many salaries the range is shown, but flagged as a small sample.
const SMALL_SAMPLE = 10;

type Props = { search: SearchOut };

export default function SalaryRange({ search }: Props) {
  // Same key as DemandChart, so this reads the cached response instead of fetching again.
  // Job Bank's monthly salaries are the reliable series; daily salary samples are still thin.
  const { data, isLoading, isError } = useQuery({
    queryKey: ["demand", search.key],
    queryFn: () => getDemand(search.role, search.region),
  });

  if (isLoading) return <p className="status">Loading salaries…</p>;
  if (isError || !data) return <p className="status">Couldn't load salaries. Try refreshing.</p>;

  // Newest month that has salary figures
  const latest = [...data.points].reverse().find((p) => p.median !== null);
  const head = (
    <div className="card-head">
      <p className="eyebrow">Pay</p>
      <h2>Salary range</h2>
      {latest && <p className="muted">Annual pay in Job Bank postings, {formatMonth(latest.month)}</p>}
    </div>
  );
  if (!latest || latest.p25 === null || latest.median === null || latest.p75 === null) {
    return (
      <section>
        {head}
        <p className="status">No salary data for this search yet.</p>
      </section>
    );
  }

  const small = latest.salary_sample_size < SMALL_SAMPLE;
  return (
    <section>
      {head}
      <dl className="salary">
        <div>
          <dt>25th pct</dt>
          <dd>{formatMoney(latest.p25)}</dd>
        </div>
        <div className="median">
          <dt>Median</dt>
          <dd>{formatMoney(latest.median)}</dd>
        </div>
        <div>
          <dt>75th pct</dt>
          <dd>{formatMoney(latest.p75)}</dd>
        </div>
      </dl>
      <p className={small ? "footnote warn" : "footnote"}>
        From <span className="num">{latest.salary_sample_size}</span> posting
        {latest.salary_sample_size === 1 ? "" : "s"} with a stated salary
        {small && ": a small sample, so treat it as a rough guide"}.
      </p>
    </section>
  );
}
