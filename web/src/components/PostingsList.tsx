import { useState } from "react";
import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { getPostings, type PostingOut, type SearchOut } from "../api";
import { formatDay, formatMoney, sourceName } from "../format";

const PAGE_SIZE = 10;

// "$85,000 – $100,000", one end if only one is given, or null with no salary.
// Estimates are labelled separately where it's rendered.
function salaryText(p: PostingOut): string | null {
  const parts = [p.salary_min, p.salary_max].filter((v): v is number => v !== null);
  if (parts.length === 0) return null;
  const range = parts[0] === parts[parts.length - 1]
    ? formatMoney(parts[0])
    : `${formatMoney(parts[0])} – ${formatMoney(parts[parts.length - 1])}`;
  return range;
}

type Props = { search: SearchOut };

// App renders this with key={search.key}, so switching searches starts again at page 1.
export default function PostingsList({ search }: Props) {
  const [offset, setOffset] = useState(0);

  const { data, isLoading, isError, isFetching } = useQuery({
    queryKey: ["postings", search.key, offset],
    queryFn: () => getPostings(search.role, search.region, PAGE_SIZE, offset),
    placeholderData: keepPreviousData, // keep showing the current page while the next loads
  });

  if (isLoading) return <p className="status">Loading postings…</p>;
  if (isError || !data) return <p className="status">Couldn't load postings. Try refreshing.</p>;

  const first = data.total === 0 ? 0 : offset + 1;
  const last = offset + data.postings.length;

  return (
    <section>
      <div className="card-head">
        <p className="eyebrow">Listings</p>
        <h2>Current postings</h2>
        <p className="muted">
          Active postings, newest first. The same job found on two sites can appear twice.
        </p>
      </div>

      {data.postings.length === 0 ? (
        <p className="status">No active postings for this search right now.</p>
      ) : (
        <ul className={isFetching ? "postings fetching" : "postings"}>
          {data.postings.map((p, i) => {
            const salary = salaryText(p);
            return (
              <li key={`${p.source}-${offset + i}`}>
                <div className="title">
                  {p.url ? <a href={p.url} target="_blank" rel="noopener noreferrer">{p.title}</a> : p.title}
                </div>
                <div className="meta">
                  {[p.company, p.location].filter(Boolean).join(" · ")}
                </div>
                <div className="meta">
                  {salary && (
                    <span className="salary-tag">
                      {salary}
                      {p.salary_is_estimate && <span className="estimate"> · estimated</span>}
                    </span>
                  )}
                  <span className="seen">Seen {formatDay(p.first_seen)} via {sourceName(p.source)}</span>
                </div>
              </li>
            );
          })}
        </ul>
      )}

      {data.total > PAGE_SIZE && (
        <div className="pager">
          <button onClick={() => setOffset(offset - PAGE_SIZE)} disabled={offset === 0 || isFetching}>
            ← Newer
          </button>
          <span className="num">{first}–{last} of {data.total}</span>
          <button onClick={() => setOffset(offset + PAGE_SIZE)}
                  disabled={last >= data.total || isFetching}>
            Older →
          </button>
        </div>
      )}
    </section>
  );
}
