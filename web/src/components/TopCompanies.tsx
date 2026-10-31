import { useQuery } from "@tanstack/react-query";
import { getCompanies, type SearchOut } from "../api";

type Props = { search: SearchOut };

export default function TopCompanies({ search }: Props) {
  const { data, isLoading, isError } = useQuery({
    queryKey: ["companies", search.key],
    queryFn: () => getCompanies(search.role, search.region, 10),
  });

  if (isLoading) return <p className="status">Loading companies…</p>;
  if (isError || !data) return <p className="status">Couldn't load companies. Try refreshing.</p>;

  return (
    <section>
      <div className="card-head">
        <p className="eyebrow">Employers</p>
        <h2>Top hiring companies</h2>
        <p className="muted">By active postings right now</p>
      </div>
      {data.companies.length === 0 ? (
        <p className="status">No active postings with a company name yet.</p>
      ) : (
        <ol className="companies">
          {data.companies.map((c) => (
            <li key={c.company}>
              <span className="name">{c.company}</span>
              <span className="count">{c.postings}</span>
            </li>
          ))}
        </ol>
      )}
    </section>
  );
}
