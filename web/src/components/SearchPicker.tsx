import { useEffect } from "react";
import { useQuery } from "@tanstack/react-query"; // tanstack for data fetch/cache
import { getSearches, type SearchOut } from "../api";
import { capitalize } from "../format";

// arguments for the component
type Props = {
  value: SearchOut | null; 
  onChange: (search: SearchOut) => void;
};

function label(s: SearchOut): string {
  return `${capitalize(s.role)} · ${capitalize(s.region)}`;
}

export default function SearchPicker({ value, onChange }: Props) {
  const { data, isLoading, isError } = useQuery({
    queryKey: ["searches"],
    queryFn: getSearches,
  });

  // Start on the first search, so the page isn't empty on arrival
  useEffect(() => {
    if (data && data.length > 0 && value === null) onChange(data[0]);
  }, [data, value, onChange]);

  if (isLoading) return <p className="status">Waking up the server…</p>;
  if (isError || !data) return <p className="status">Couldn't reach the API. Try refreshing.</p>;

  return (
    <label className="field">
      Search
      <select
        value={value?.key ?? ""}
        onChange={(e) => {
          const picked = data.find((s) => s.key === e.target.value);
          if (picked) onChange(picked);
        }}
      >
        <option value="" disabled>Choose a role and region…</option>
        {data.map((s) => (
          <option key={s.key} value={s.key}>{label(s)}</option>
        ))}
      </select>
    </label>
  );
}